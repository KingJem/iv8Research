import json
import re
import time
from html import unescape
from urllib.parse import urljoin

from curl_cffi import requests
import iv8

BASE_URL = "https://www.chewy.com/"
SEARCH_URL = "https://www.chewy.com/s"
SEARCH_PARAMS = {"query": "water", "nav-submit-button": ""}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "priority": "u=0, i",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA,
}


def parse_cookies(cookie_str: str) -> dict:
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


# ===== Step 1: GET challenge page (expect 429 + KPSDK challenge) =====
print("[1] GET chewy search (expecting 429 challenge) ...")
r1 = requests.get(SEARCH_URL, params=SEARCH_PARAMS, headers=HEADERS, impersonate="chrome124")
print(f"    status={r1.status_code}")

html_raw = r1.text
html = unescape(html_raw)

script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
if not script_srcs:
    raise RuntimeError("No <script src> found in challenge page")

ips_path = script_srcs[0]
ips_url = urljoin(BASE_URL, ips_path)
print(f"[2] ips.js URL: {ips_url[:100]}...")

# ===== Step 2: fetch ips.js =====
r_js = requests.get(ips_url, headers={
    **HEADERS,
    "accept": "*/*",
    "referer": BASE_URL,
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": None,
}, cookies=dict(r1.cookies), impersonate="chrome124")
print(f"    js status={r_js.status_code}  length={len(r_js.text)}")

session_cookies = {**dict(r1.cookies), **dict(r_js.cookies)}

# ===== Step 3: run ips.js in iv8, intercept /tl POST =====
print("[3] Running iv8 ...")
start = time.time()

environment = {
    "location": {
        "ancestorOrigins": {},
        "href": BASE_URL,
        "origin": "https://www.chewy.com",
        "protocol": "https:",
        "host": "www.chewy.com",
        "hostname": "www.chewy.com",
        "port": "",
        "pathname": "/",
        "search": "",
        "hash": "",
    },
    "navigator": {
        "userAgent": UA,
        "platform": "Win32",
        "hardwareConcurrency": 8,
        "language": "en-US",
        "languages": ["en-US", "en"],
    },
    "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
}

tl_url = None
tl_body = ""
tl_hdrs = {}
tl_cookie = ""

with iv8.JSContext(
    environment=environment,
    config={"time": {"mode": "logical"}},
) as ctx:
    snapshot = {
        "baseURL": BASE_URL,
        "html": html,
        "headers": [[k, v] for k, v in r1.headers.items()],
        "resources": {ips_url: r_js.text},
    }
    ctx.expose(snapshot, "snapshot")

    ctx.eval("""(function() {
        try {
            // iv8 0.1.4 未实现 FileList 的 wrapper,ips.js 访问 dataTransfer.files 会抛 C++ 异常
            // 并在 JSContext 销毁时使进程崩溃(exit 127)。覆盖 getter 返回空数组,绕开该原生路径。
            if (window.DataTransfer && DataTransfer.prototype) {
                Object.defineProperty(DataTransfer.prototype, 'files', {
                    configurable: true, get: function(){ return []; }
                });
            }
        } catch(e) {}
        try {
            if (typeof window.TouchEvent === 'undefined') {
                window.TouchEvent = function TouchEvent(type, init) {
                    var e = new Event(type, init || {});
                    e.touches = e.targetTouches = e.changedTouches = [];
                    return e;
                };
            }
            if (typeof window.Touch === 'undefined') {
                window.Touch = function Touch(init) { Object.assign(this, init || {}); };
            }
        } catch(e) {}
        try {
            var _ce = Document.prototype.createEvent;
            Document.prototype.createEvent = function(type) {
                try { return _ce.call(this, type); }
                catch(e) {
                    var evt = new Event(type || 'Event', {bubbles: true, cancelable: true});
                    if (type === 'TouchEvent') { evt.touches = evt.targetTouches = evt.changedTouches = []; }
                    return evt;
                }
            };
        } catch(e) {}
        try {
            var _as = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
                try { return _as.call(this, init); }
                catch(e) { return document.createElement('div'); }
            };
        } catch(e) {}
        try {
            if (navigator.permissions && navigator.permissions.query) {
                var _pq = navigator.permissions.query.bind(navigator.permissions);
                navigator.permissions.query = function(desc) {
                    if (!desc || !desc.name) return Promise.resolve({state: 'prompt'});
                    return _pq(desc).catch(function() { return {state: 'prompt'}; });
                };
            }
        } catch(e) {}
    })();""")

    ctx.eval("__iv8__.page.load(__iv8__.data.snapshot);")

    for tick in range(60):
        entries = ctx.eval("__iv8__.netLog.entries", to_py=True) or []

        with open("netlog_dump.json", "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

        tl_entry = next((e for e in entries if "/tl" in e.get("url", "")), None)
        if tl_entry:
            tl_url = tl_entry.get("url", "")
            tl_body = tl_entry.get("body", "") or tl_entry.get("postData", {}).get("text", "")
            tl_hdrs = {h[0]: h[1] for h in tl_entry.get("headers", []) if isinstance(h, list)}
            tl_cookie = tl_entry.get("cookieHeader", "")
            print(f"    [iv8] /tl found at tick={tick}: {tl_url[:80]}")
            print(f"    [iv8] body_len={len(tl_body)}  cookie={tl_cookie[:80]}")
            break

        if tick % 10 == 0:
            urls = [e.get("url", "")[:60] for e in entries if e.get("url", "").startswith("http")]
            print(f"    [tick {tick:02d}] netLog={len(entries)} entries  urls={urls}")

        ctx.eval("__iv8__.eventLoop.sleep(100);")
    else:
        print("    [warn] /tl not found after 60 ticks")

print(f"    iv8 done in {time.time() - start:.2f}s")

# ===== Step 3b: POST /tl to activate KP_UIDz-ssn =====

if not tl_url:
    print("[warn] /tl URL not captured — check netlog_dump.json")
    import sys; sys.exit(1)

print(f"[3b] POST {tl_url[:80]}...")
tl_headers = {
    **HEADERS,
    "accept": "*/*",
    "referer": BASE_URL,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "content-type": tl_hdrs.get("content-type", "application/octet-stream"),
}
if tl_hdrs.get("x-kpsdk-ct"):
    tl_headers["x-kpsdk-ct"] = tl_hdrs["x-kpsdk-ct"]
if tl_hdrs.get("x-kpsdk-im"):
    tl_headers["x-kpsdk-im"] = tl_hdrs["x-kpsdk-im"]

tl_cookies = {**session_cookies, **parse_cookies(tl_cookie)}

r_tl = requests.post(
    tl_url,
    data=tl_body.encode() if isinstance(tl_body, str) else tl_body,
    headers=tl_headers,
    cookies=tl_cookies,
    impersonate="chrome124",
)
print(f"    /tl status={r_tl.status_code}  set-cookie={r_tl.headers.get('set-cookie', '')[:80]}")
# Kasada 重试需要 /tl 响应回传的 x-kpsdk-ct 令牌(header 或 body)
ct = r_tl.headers.get("x-kpsdk-ct", "")
print(f"    /tl resp headers: {list(r_tl.headers.keys())}")
print(f"    x-kpsdk-ct: {ct[:60] if ct else '(none in headers)'}  body[:120]={r_tl.text[:120]!r}")
session_cookies.update(dict(r_tl.cookies))

# ===== Step 4: retry with activated cookies + x-kpsdk-ct =====
merged_cookies = {**session_cookies}
print(f"    merged cookies: {list(merged_cookies.keys())}")

retry_headers = {**HEADERS, "referer": BASE_URL, "sec-fetch-site": "same-origin"}
if ct:
    retry_headers["x-kpsdk-ct"] = ct

print("[4] Retrying search ...")
r2 = requests.get(
    SEARCH_URL,
    params=SEARCH_PARAMS,
    headers=retry_headers,
    cookies=merged_cookies,
    impersonate="chrome124",
)
print(f"    status={r2.status_code}  length={len(r2.text)}")
low = r2.text.lower()
print("    有商品?", ("data-testid" in low or "product" in low or "add to cart" in low or "chewy" in low and r2.status_code==200 and len(r2.text)>50000))
print(r2.text[:600])
