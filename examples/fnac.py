# [NOT WORKING]
# ============================================================
# 免责声明 / Disclaimer
# 本示例仅供学习 iv8 API 用法参考，不构成对任何网站的攻击或未授权访问。
# 使用者应自行遵守目标网站的服务条款及所在地区法律法规。
# 作者不对任何滥用行为承担责任。
#
# This example is for educational purposes only.
# Users must comply with all applicable laws and terms of service.
# The author assumes no responsibility for any misuse.
# ============================================================

import json
import re
from urllib.parse import urlparse, parse_qs, quote

import iv8
from curl_cffi import requests as cffi_requests

TARGET_URL = (
    "https://www.fnac.com/a23121778/"
    "Pour-une-poignee-de-dollars-Edition-Collector-Limitee-et-Numerotee-"
    "Edition-Speciale-Fnac-SteelBook-Blu-ray-4K-Ultra-HD-Clint-Eastwood-Blu-ray-4K"
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

PROXY = "socks5h://127.0.0.1:7890"
session = cffi_requests.Session(impersonate="chrome124", proxy=PROXY)

# ============================================================
# Step 1-3: Navigate through Queue-it (same as before)
# ============================================================
print("[1] GET fnac.com product page (Queue-it flow)...")

resp1 = session.get(TARGET_URL, headers=HEADERS, allow_redirects=False)
print(f"    Step 1: HTTP {resp1.status_code}")
loc1 = resp1.headers.get("Location", "")
assert loc1 and "queue" in loc1, f"Expected Queue-it redirect, got: {loc1}"

resp2 = session.get(loc1, headers={**HEADERS, "Sec-Fetch-Site": "cross-site", "Referer": "https://www.fnac.com/"}, allow_redirects=False)
print(f"    Step 2 (Queue-it): HTTP {resp2.status_code}")
loc2 = resp2.headers.get("Location", "")
assert loc2, "No redirect from Queue-it"

resp3 = session.get(loc2, headers={**HEADERS, "Sec-Fetch-Site": "cross-site", "Referer": "https://queue.fnac.com/"}, allow_redirects=False)
print(f"    Step 3 (queueittoken validation): HTTP {resp3.status_code}")
loc3 = resp3.headers.get("Location", "") or TARGET_URL
print(f"    QueueITAccepted set: {'QueueITAccepted' in resp3.headers.get('Set-Cookie','')}")

resp4 = session.get(loc3, headers={**HEADERS, "Sec-Fetch-Site": "same-origin", "Referer": "https://www.fnac.com/"}, allow_redirects=True)
print(f"    Step 4 (product page): HTTP {resp4.status_code}, body={len(resp4.text)} chars")

html4 = resp4.text
final_url = str(resp4.url)

# ============================================================
# Step 4: Parse DataDome challenge params
# ============================================================
dd_m = re.search(r"var dd\s*=\s*(\{[^}]+\})", html4)
if not dd_m:
    print("\nNo DataDome challenge — product page received directly!")
    title_m = re.search(r'<title[^>]*>([^<]+)</title>', html4)
    print(f"Title: {title_m.group(1) if title_m else 'unknown'}")
    print(html4[:3000])
    exit(0)

dd_obj_str = dd_m.group(1)
cid = re.search(r"'cid'\s*:\s*'([^']+)'", dd_obj_str).group(1)
hsh = re.search(r"'hsh'\s*:\s*'([^']+)'", dd_obj_str).group(1)
t_val = re.search(r"'t'\s*:\s*'([^']+)'", dd_obj_str).group(1)
s_val = re.search(r"'s'\s*:\s*(\d+)", dd_obj_str).group(1)
e_val = re.search(r"'e'\s*:\s*'([^']+)'", dd_obj_str).group(1)
host_val = re.search(r"'host'\s*:\s*'([^']+)'", dd_obj_str).group(1)
cookie_val = re.search(r"'cookie'\s*:\s*'([^']+)'", dd_obj_str).group(1)

print(f"\n[5] DataDome detected: host={host_val}, cid={cid[:20]}...")

# ============================================================
# Step 5: Fetch all JS needed for the DataDome challenge page
# ============================================================

# c.js: main DataDome challenge runner
dd_cjs_url = "https://ct.captcha-delivery.com/c.js"
dd_cjs = session.get(dd_cjs_url, headers={
    "Referer": final_url, "Accept": "*/*",
    "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site",
}).text
print(f"    c.js: {len(dd_cjs)} chars")

# Akamai Bot Manager script on fnac.com
akam_m = re.search(r'src="(https://www\.fnac\.com/akam/[^"]+)"', html4)
akam_js = ""
if akam_m:
    akam_js = session.get(akam_m.group(1), headers={
        "Referer": final_url, "Accept": "*/*",
        "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-origin",
    }).text
    print(f"    Akamai BM script: {len(akam_js)} chars")

# Akamai sensor script (the big one with fingerprinting logic)
sensor_m = re.search(r'src="(/ON7JQ5[^"]+)"', html4)
sensor_js = ""
sensor_url = ""
if sensor_m:
    sensor_url = "https://www.fnac.com" + sensor_m.group(1)
    sensor_js = session.get(sensor_url, headers={
        "Referer": final_url, "Accept": "*/*",
        "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-origin",
    }).text
    print(f"    Sensor script: {len(sensor_js)} chars at {sensor_url[:60]}")

# ============================================================
# Step 6: Execute challenge in iv8 with real network bridge
# ============================================================
print(f"\n[6] Running DataDome challenge in iv8 (with XHR network bridge)...")

environment = {
    "location": {
        "href": final_url,
        "origin": "https://www.fnac.com",
        "protocol": "https:",
        "host": "www.fnac.com",
        "hostname": "www.fnac.com",
        "port": "",
        "pathname": urlparse(final_url).path,
        "search": "",
        "hash": "",
    },
    "navigator": {
        "userAgent": UA,
        "language": "fr-FR",
        "languages": ["fr-FR", "fr", "en-US", "en"],
    },
}

captured = {"datadome_cookie": None, "iframe_src": None}

# ── helper: XHR bridge (used in both parent and iframe contexts) ──────────────
def make_xhr_bridge(ctx_ref, label="XHR"):
    def real_fetch(method, url, body, headers_json):
        method = str(method).upper()
        url = str(url)
        req_headers = json.loads(str(headers_json)) if headers_json and str(headers_json) != "null" else {}
        req_body = str(body) if body and str(body) not in ("null", "undefined", "") else None
        req_headers.setdefault("User-Agent", UA)
        print(f"  [{label}→Python] {method} {url[:80]}")
        try:
            resp = session.request(method, url, data=req_body, headers=req_headers, timeout=20)
            print(f"  [{label}→Python] → {resp.status_code} ({len(resp.text)} bytes)")
            set_cookie = resp.headers.get("Set-Cookie", "")
            if "datadome=" in set_cookie:
                m = re.search(r"datadome=([^;]+)", set_cookie)
                if m:
                    captured["datadome_cookie"] = m.group(1)
                    print(f"  [{label}→Python] ✓ datadome cookie: {captured['datadome_cookie'][:50]}...")
                    session.cookies.set("datadome", captured["datadome_cookie"], domain=".fnac.com")
            ctx_ref[0].add_resource(url=url, body=resp.text, status=resp.status_code,
                                    headers=dict(resp.headers))
        except Exception as ex:
            print(f"  [{label}→Python] ERROR: {ex}")
            ctx_ref[0].add_resource(url=url, body="", status=503, headers={})
    return real_fetch

XHR_HOOK = """
(function() {
    var _origOpen = XMLHttpRequest.prototype.open;
    var _origSend = XMLHttpRequest.prototype.send;
    var _origSetHdr = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function(m, u) {
        this.__m = m; this.__u = u; this.__h = {};
        return _origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(n, v) {
        this.__h[n] = v; return _origSetHdr.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        __iv8__.data.realFetch(this.__m, this.__u, body||null, JSON.stringify(this.__h||{}));
        return _origSend.apply(this, arguments);
    };
})();
"""

# ── Step 6a: run parent page in iv8, intercept iframe creation ───────────────
print(f"\n[6] Running challenge page in iv8, capturing iframe src...")

parent_ctx_ref = [None]

with iv8.JSContext(environment=environment) as ctx:
    parent_ctx_ref[0] = ctx
    ctx.expose(make_xhr_bridge(parent_ctx_ref, "parent-XHR"), "realFetch")
    ctx.eval(XHR_HOOK)

    # Hook createElement to capture the DataDome iframe src
    ctx.eval("""
        window.__dd_iframe_src__ = null;
        (function() {
            var _orig = document.createElement.bind(document);
            document.createElement = function(tag) {
                var el = _orig(tag);
                if (tag.toLowerCase() === 'iframe') {
                    Object.defineProperty(el, 'src', {
                        set: function(v) {
                            if (v && v.indexOf('captcha-delivery.com') !== -1) {
                                window.__dd_iframe_src__ = v;
                                console.log('[iv8] DataDome iframe src captured: ' + v.substring(0, 80));
                            }
                            this.setAttribute('src', v);
                        },
                        get: function() { return this.getAttribute('src') || ''; }
                    });
                }
                return el;
            };
        })();
    """)

    snapshot = {
        "baseURL": final_url,
        "html": html4,
        "headers": [],
        "resources": {},
    }
    if akam_m:
        snapshot["resources"][akam_m.group(1)] = akam_js
    if sensor_url:
        snapshot["resources"][sensor_url] = sensor_js
    snapshot["resources"][dd_cjs_url] = dd_cjs

    ctx.expose(snapshot, "snapshot")
    ctx.eval("window.__iv8__.page.load(window.__iv8__.data.snapshot)")
    ctx.eval("window.__iv8__.eventLoop.sleep(2000)")
    ctx.eval("window.__iv8__.eventLoop.drain()")

    iframe_src = ctx.eval("window.__dd_iframe_src__")
    print(f"    Captured iframe src: {str(iframe_src)[:120] if iframe_src else 'NOT FOUND'}")

    if not iframe_src or str(iframe_src) == "None":
        # Reconstruct iframe URL manually from dd params (c.js formula)
        iframe_src = (
            f"https://{host_val}/captcha/"
            f"?initialCid={quote(cid)}"
            f"&hash={quote(hsh)}"
            f"&cid={quote(cookie_val)}"
            f"&t={quote(t_val)}"
            f"&referer={quote(final_url)}"
            f"&s={s_val}"
            f"&e={e_val}"
        )
        print(f"    Reconstructed iframe src: {iframe_src[:120]}")

    iframe_src = str(iframe_src)

# ── Step 6b: fetch DataDome iframe HTML ──────────────────────────────────────
print(f"\n[6b] Fetching DataDome iframe HTML...")
resp_iframe = session.get(iframe_src, headers={
    "User-Agent": UA,
    "Referer": final_url,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Sec-Fetch-Dest": "iframe",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
})
print(f"    HTTP {resp_iframe.status_code}, body={len(resp_iframe.text)} chars")

# ── Step 6c: run iframe JS inside iv8, with XHR bridge ───────────────────────
print(f"\n[6c] Running DataDome iframe JS in iv8...")

iframe_env = {
    "location": {
        "href": iframe_src,
        "origin": f"https://{host_val}",
        "protocol": "https:",
        "host": host_val,
        "hostname": host_val,
        "port": "",
        "pathname": "/captcha/",
        "search": "?" + iframe_src.split("?", 1)[1] if "?" in iframe_src else "",
        "hash": "",
    },
    "navigator": {
        "userAgent": UA,
        "language": "fr-FR",
        "languages": ["fr-FR", "fr", "en-US", "en"],
    },
}

# Collect scripts referenced in the iframe
iframe_scripts_urls = re.findall(r'src="(https?://[^"]+\.js[^"]*)"', resp_iframe.text)
iframe_script_srcs = {}
for s_url in iframe_scripts_urls:
    try:
        js_content = session.get(s_url, headers={"Referer": iframe_src, "Accept": "*/*"}).text
        iframe_script_srcs[s_url] = js_content
        print(f"    Fetched iframe script: {s_url[:80]} ({len(js_content)} chars)")
    except Exception as ex:
        print(f"    Failed to fetch {s_url[:60]}: {ex}")

iframe_ctx_ref = [None]

with iv8.JSContext(environment=iframe_env) as ictx:
    iframe_ctx_ref[0] = ictx

    ictx.expose(make_xhr_bridge(iframe_ctx_ref, "iframe-XHR"), "realFetch")
    ictx.eval(XHR_HOOK)

    # Intercept postMessage to capture DataDome's cookie reply
    ictx.eval("""
        window.__dd_postmsg__ = null;
        var _origPostMsg = window.parent.postMessage;
        window.parent = {
            postMessage: function(data, origin) {
                window.__dd_postmsg__ = data;
                console.log('[iv8-iframe] postMessage: ' + JSON.stringify(data).substring(0, 100));
            }
        };
    """)

    iframe_snapshot = {
        "baseURL": iframe_src,
        "html": resp_iframe.text,
        "headers": [],
        "resources": iframe_script_srcs,
    }
    ictx.expose(iframe_snapshot, "snapshot")
    ictx.eval("window.__iv8__.page.load(window.__iv8__.data.snapshot)")
    ictx.eval("window.__iv8__.eventLoop.sleep(5000)")
    ictx.eval("window.__iv8__.eventLoop.drain()")

    postmsg = ictx.eval("window.__dd_postmsg__", to_py=True)
    print(f"    postMessage data: {str(postmsg)[:200] if postmsg else 'none'}")

    iframe_net = ictx.eval("window.__iv8__.netLog.entries", to_py=True)
    print(f"    Iframe network entries: {len(iframe_net) if iframe_net else 0}")
    if iframe_net:
        for e in (iframe_net or [])[:5]:
            print(f"      {e.get('url','')[:100]}")

    # Extract datadome from postMessage
    if postmsg and not captured["datadome_cookie"]:
        try:
            msg_data = postmsg if isinstance(postmsg, dict) else json.loads(str(postmsg))
            raw_cookie = msg_data.get("cookie", "")
            m = re.search(r"datadome=([^;]+)", raw_cookie)
            if m:
                captured["datadome_cookie"] = m.group(1)
                print(f"    ✓ datadome from postMessage: {captured['datadome_cookie'][:50]}...")
                session.cookies.set("datadome", captured["datadome_cookie"], domain=".fnac.com")
        except Exception as ex:
            print(f"    postMessage parse error: {ex}")

datadome_cookie_value = captured["datadome_cookie"]
print(f"\n    DataDome cookie: {datadome_cookie_value[:60] if datadome_cookie_value else 'NOT OBTAINED'}")

# ============================================================
# Step 7: Retry with DataDome cookie
# ============================================================
print(f"\n[7] Retrying product page with all cookies...")
print(f"    Session cookies: {list(session.cookies.keys())}")

resp_final = session.get(
    TARGET_URL,
    headers={**HEADERS, "Referer": "https://www.fnac.com/"},
    allow_redirects=True,
)
print(f"    HTTP {resp_final.status_code}, body={len(resp_final.text)} chars")

html_final = resp_final.text

# Detect if still on challenge page
if "datadome" in html_final and "var dd" in html_final:
    print("    Still on DataDome challenge page.")
    dd_m2 = re.search(r"var dd\s*=\s*(\{[^}]+\})", html_final)
    if dd_m2:
        print(f"    New dd: {dd_m2.group(1)[:100]}")
else:
    title_m = re.search(r'<title[^>]*>([^<]+)</title>', html_final)
    print(f"\n    Title: {title_m.group(1).strip() if title_m else 'N/A'}")

    for pat in [r'itemprop="price"[^>]*content="([^"]+)"', r'"price"\s*:\s*"?([\d,\.]+)"?']:
        m = re.search(pat, html_final, re.IGNORECASE)
        if m:
            print(f"    Price: {m.group(1)}")
            break

    avail_m = re.search(r'"availability"\s*:\s*"([^"]+)"', html_final)
    if avail_m:
        print(f"    Availability: {avail_m.group(1)}")

    print("\n--- Body preview (first 3000 chars) ---")
    print(html_final[:3000])
