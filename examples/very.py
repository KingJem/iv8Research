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
#
# Flow overview:
#   very.co.uk uses Akamai Bot Manager v3.  A clean request gets:
#     • 403 Access Denied with an Akamai sensor script tag
#   The sensor script fingerprints the browser and POSTs to the pixel
#   endpoint (same path as the script, without ?v=...).  On a valid
#   submission the server responds 200 and sets ak_bmsc; a subsequent
#   page request is allowed through.
#
#   Key iv8 wiring needed:
#     1. document.currentScript.src / getAttribute('src')  — Akamai reads
#        this to build the pixel POST URL at runtime.
#     2. XHR bridge                                        — relay the POST
#        through Python's curl_cffi session so real cookies are updated.
#     3. Browser API stubs                                 — sendBeacon,
#        performance, crypto.getRandomValues (sensor checks these).
#
#   Limitation: a valid _abck cookie (ending without ~-1~-1~-1~-1~-1)
#   requires the sensor data to pass Akamai's ML model AND a non-
#   datacenter IP.  The script correctly executes all steps; the final
#   403 is an IP-reputation block, not a code issue.
# ============================================================

import json
import re
from urllib.parse import urlparse

import iv8
from curl_cffi import requests as cffi_requests

TARGET_URL = "https://www.very.co.uk/search/headphones"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

PROXY = "http://127.0.0.1:7890"

session = cffi_requests.Session(impersonate="chrome124", proxies={"http": PROXY, "https": PROXY})

# ============================================================
# Step 1: Initial request — collect _abck / bm_sz cookies and
#         the Akamai sensor script URL from the 403 page.
# ============================================================
print("[1] GET very.co.uk search page (expecting Akamai 403 + sensor JS)...")
resp1 = session.get(TARGET_URL, headers=HEADERS, allow_redirects=True, timeout=30)
print(f"    HTTP {resp1.status_code}, body={len(resp1.text)} chars")

abck_init = session.cookies.get("_abck")
bm_sz = session.cookies.get("bm_sz")
print(f"    _abck (initial): {str(abck_init)[:60]}...")
print(f"    bm_sz:           {str(bm_sz)[:60]}...")

sensor_m = re.search(r'src="(/[^"]+\?v=[^"]+)"', resp1.text)
assert sensor_m, "Sensor script <script src=> not found in response"
sensor_path = sensor_m.group(1)
sensor_url = "https://www.very.co.uk" + sensor_path
sensor_pixel_url = "https://www.very.co.uk" + sensor_path.split("?")[0]
print(f"    Sensor JS:  {sensor_path[:80]}")
print(f"    Pixel POST: {sensor_pixel_url}")

# ============================================================
# Step 2: Fetch the Akamai sensor JS
# ============================================================
print("\n[2] Fetching Akamai sensor JS...")
resp_sensor = session.get(sensor_url, headers={
    "User-Agent": UA,
    "Referer": TARGET_URL,
    "Accept": "*/*",
    "Sec-Fetch-Dest": "script",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-origin",
}, timeout=30)
print(f"    HTTP {resp_sensor.status_code}, size={len(resp_sensor.text)} chars")
sensor_js = resp_sensor.text

# ============================================================
# Step 3: Run Akamai sensor JS in iv8 with XHR bridge
# ============================================================
print("\n[3] Running Akamai sensor JS in iv8 (XHR bridge active)...")

captured = {"abck": None, "ak_bmsc": None, "post_url": None}

environment = {
    "location": {
        "href": TARGET_URL,
        "origin": "https://www.very.co.uk",
        "protocol": "https:",
        "host": "www.very.co.uk",
        "hostname": "www.very.co.uk",
        "port": "",
        "pathname": urlparse(TARGET_URL).path,
        "search": "",
        "hash": "",
    },
    "navigator": {
        "userAgent": UA,
        "language": "en-GB",
        "languages": ["en-GB", "en-US", "en"],
    },
}

current_script_obj = {"src": sensor_url}


def real_fetch(method, url, body, headers_json):
    method = str(method).upper()
    url = str(url)
    req_headers = (json.loads(str(headers_json))
                   if headers_json and str(headers_json) not in ("null", "undefined")
                   else {})
    req_body = str(body) if body and str(body) not in ("null", "undefined", "") else None
    req_headers.setdefault("User-Agent", UA)
    req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    req_headers["Referer"] = TARGET_URL
    print(f"  [XHR→Python] {method} {url[:100]}")
    if not url.startswith("http"):
        return
    try:
        resp = session.request(method, url, data=req_body, headers=req_headers, timeout=20,
                               proxies={"http": PROXY, "https": PROXY})
        print(f"  [XHR→Python] → HTTP {resp.status_code} ({len(resp.content)} bytes)")
        set_cookie = resp.headers.get("Set-Cookie", "")
        if "_abck=" in set_cookie:
            m = re.search(r"_abck=([^;]+)", set_cookie)
            if m:
                captured["abck"] = m.group(1)
                captured["post_url"] = url
                print(f"  [XHR→Python] ✓ _abck: {m.group(1)[:80]}...")
                session.cookies.set("_abck", m.group(1), domain=".very.co.uk")
        if "ak_bmsc=" in set_cookie:
            m = re.search(r"ak_bmsc=([^;]+)", set_cookie)
            if m:
                captured["ak_bmsc"] = m.group(1)
                print(f"  [XHR→Python] ✓ ak_bmsc received")
                session.cookies.set("ak_bmsc", m.group(1), domain=".very.co.uk")
    except Exception as ex:
        print(f"  [XHR→Python] ERROR: {ex}")


with iv8.JSContext(environment=environment) as ctx:
    ctx.expose(real_fetch, "realFetch")
    ctx.expose(current_script_obj, "currentScriptObj")

    ctx.eval("""
        // currentScript.src + getAttribute needed by Akamai to resolve its pixel POST URL
        Object.defineProperty(document, 'currentScript', {
            get: function() { return window.__iv8__.data.currentScriptObj; },
            configurable: true
        });
        window.__iv8__.data.currentScriptObj.getAttribute = function(attr) {
            return attr === 'src' ? window.__iv8__.data.currentScriptObj.src : null;
        };

        // Browser API stubs
        if (!navigator.sendBeacon) {
            navigator.sendBeacon = function(u, d) { return true; };
        }
        if (!window.performance) {
            window.performance = {
                now: function() { return Date.now(); },
                timing: { navigationStart: Date.now() - 5000 }
            };
        }
        if (!window.crypto || !window.crypto.getRandomValues) {
            window.crypto = window.crypto || {};
            window.crypto.getRandomValues = function(arr) {
                for (var i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
                return arr;
            };
        }

        // XHR bridge
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
            __iv8__.data.realFetch(this.__m, this.__u, body || null,
                                   JSON.stringify(this.__h || {}));
            return _origSend.apply(this, arguments);
        };
    """)

    ctx.eval(sensor_js)  # runs sensor; XHR fires inside eventLoop.sleep below
    ctx.eval("window.__iv8__.eventLoop.sleep(3000)")
    ctx.eval("window.__iv8__.eventLoop.drain()")

print(f"\n    _abck after sensor:  {str(session.cookies.get('_abck', ''))[:80]}...")
print(f"    ak_bmsc collected:   {'yes' if captured['ak_bmsc'] else 'no'}")
print(f"    Sensor POST URL:     {captured['post_url']}")

# ============================================================
# Step 4: Retry target URL with all Akamai cookies
# ============================================================
print(f"\n[4] Retrying search page with all Akamai cookies...")
print(f"    Cookies: {list(session.cookies.keys())}")

abck_cookie = session.cookies.get("_abck", "")
valid_abck = bool(abck_cookie) and "-1~-1~-1~-1~-1" not in abck_cookie
print(f"    _abck valid (no ~-1~-1~-1~-1~-1 suffix): {valid_abck}")

resp_final = session.get(
    TARGET_URL,
    headers={**HEADERS, "Referer": "https://www.very.co.uk/"},
    allow_redirects=True,
    timeout=30,
)
print(f"    HTTP {resp_final.status_code}, body={len(resp_final.text)} chars")

html = resp_final.text
title_m = re.search(r"<title[^>]*>([^<]+)</title>", html)
print(f"    Title: {title_m.group(1).strip() if title_m else 'N/A'}")

if resp_final.status_code == 200 and "Access Denied" not in html:
    print("\n    ✓ Successfully bypassed Akamai Bot Manager — got real search page!")
    products = re.findall(r'"name"\s*:\s*"([^"]{10,80})"', html)
    if products:
        print(f"\n    Sample products found ({len(products)} total):")
        for p in products[:8]:
            print(f"      - {p}")
    print("\n--- Body preview (first 2000 chars) ---")
    print(html[:2000])
else:
    print("\n    Still blocked / access denied.")
    if valid_abck:
        print(f"    _abck looks valid but server still returned {resp_final.status_code}.")
        print(f"    This is a datacenter/VPN IP-reputation block by Akamai.")
        print(f"    A residential or UK-based IP would be needed to bypass this layer.")
    else:
        print(f"    _abck has ~-1~-1~-1~-1~-1 — sensor data was rejected by Akamai ML.")
        print(f"    The iv8 fingerprint environment needs more realistic browser API stubs.")
    print("\n--- Body preview (first 1500 chars) ---")


    with open('data.html','w',encoding='utf-8') as f:
        f.write(html)

# 出口IP会验证