import json
import re
import time
from html import unescape
from urllib.parse import urljoin

from curl_cffi import requests
import iv8

TARGET_URL = "https://www.ebay.com/itm/357558441418?_trkparms=5373%3A0%7C5374%3AFeatured"
BASE_URL = "https://www.ebay.com/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
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

# ===== Step 1: GET target page (expect 403 + Akamai challenge) =====
print("[1] GET eBay item page ...")
session = requests.Session(impersonate="chrome124")
r1 = session.get(TARGET_URL, headers=HEADERS)
print(f"    status={r1.status_code}  cookies={list(r1.cookies.keys())}")

html_raw = r1.text
html = unescape(html_raw)

script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
if not script_srcs:
    raise RuntimeError("No <script src> found in challenge page")

akam_path = script_srcs[0]
akam_url = urljoin(BASE_URL, akam_path)
print(f"[2] Akamai script: {akam_url[:100]}...")

# ===== Step 2: fetch Akamai bootstrap JS =====
r_js = session.get(akam_url, headers={
    **HEADERS,
    "accept": "*/*",
    "referer": TARGET_URL,
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "same-origin",
})
print(f"    js status={r_js.status_code}  length={len(r_js.text)}")

# ===== Step 3: run Akamai JS in iv8, capture sensor_data POST =====
print("[3] Running iv8 ...")
start_t = time.time()

environment = {
    "location": {
        "ancestorOrigins": {},
        "href": TARGET_URL,
        "origin": "https://www.ebay.com",
        "protocol": "https:",
        "host": "www.ebay.com",
        "hostname": "www.ebay.com",
        "port": "",
        "pathname": "/itm/357558441418",
        "search": "?_trkparms=5373%3A0%7C5374%3AFeatured",
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

sensor_url = None
sensor_body = ""
sensor_hdrs = {}

with iv8.JSContext(
    environment=environment,
    config={"time": {"mode": "logical"}},
) as ctx:
    snapshot = {
        "baseURL": BASE_URL,
        "html": html,
        "headers": [[k, v] for k, v in r1.headers.items()],
        "resources": {akam_url: r_js.text},
    }
    ctx.expose(snapshot, "snapshot")

    ctx.eval("""(function() {
        try {
            if (typeof window.TouchEvent === 'undefined') {
                window.TouchEvent = function(type, init) {
                    var e = new Event(type, init || {});
                    e.touches = e.targetTouches = e.changedTouches = [];
                    return e;
                };
            }
        } catch(e) {}
        try {
            var _ce = Document.prototype.createEvent;
            Document.prototype.createEvent = function(type) {
                try { return _ce.call(this, type); }
                catch(e) { return new Event(type || 'Event', {bubbles:true, cancelable:true}); }
            };
        } catch(e) {}
        try {
            var _as = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init) {
                try { return _as.call(this, init); }
                catch(e) { return document.createElement('div'); }
            };
        } catch(e) {}
    })();""")

    ctx.eval("__iv8__.page.load(__iv8__.data.snapshot);")

    akam_base = akam_path.split("?")[0]
    for tick in range(80):
        entries = ctx.eval("__iv8__.netLog.entries", to_py=True) or []

        with open("netlog_dump.json", "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

        sensor = None
        for e in entries:
            url = e.get("url", "")
            if e.get("method") == "POST" and any(k in url for k in ["sensor_data", "h8u_e", akam_base]):
                sensor = e
                break
        if sensor is None:
            posts = [e for e in entries if e.get("method") == "POST"]
            if posts:
                sensor = posts[0]

        if sensor:
            sensor_url = sensor.get("url", "")
            sensor_body = sensor.get("body", "") or sensor.get("postData", {}).get("text", "")
            sensor_hdrs = {h[0]: h[1] for h in sensor.get("headers", []) if isinstance(h, list)}
            print(f"    [iv8] sensor POST found at tick={tick}: {sensor_url[:80]}")
            print(f"    [iv8] body_len={len(sensor_body)}  hdrs={list(sensor_hdrs.keys())}")
            break

        if tick % 10 == 0:
            urls = [e.get("url", "")[:70] for e in entries if e.get("url", "").startswith("http")]
            print(f"    [tick {tick:02d}] entries={len(entries)}  urls={urls}")

        ctx.eval("__iv8__.eventLoop.sleep(100);")
    else:
        print("    [warn] sensor POST not found after 80 ticks")

print(f"    iv8 done in {time.time() - start_t:.2f}s")

# ===== Step 4: POST sensor_data to activate cookies =====
if not sensor_url:
    print("[warn] No sensor POST captured — check netlog_dump.json")
    import sys; sys.exit(1)

print(f"[4] POST sensor_data to {sensor_url[:80]}...")
post_headers = {
    **HEADERS,
    "accept": "*/*",
    "content-type": sensor_hdrs.get("content-type", "text/plain;charset=UTF-8"),
    "referer": TARGET_URL,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}
for k in ("pragma", "cache-control"):
    if k in sensor_hdrs:
        post_headers[k] = sensor_hdrs[k]

print(sensor_body.encode())
print(sensor_url)
r_sensor = session.post(
    sensor_url,
    data=sensor_body.encode() if isinstance(sensor_body, str) else sensor_body,
    headers=post_headers,
)
print(f"    status={r_sensor.status_code}  set-cookie={r_sensor.headers.get('set-cookie', '')[:80]}")
session.cookies.update(r_sensor.cookies)
print(r_sensor.cookies)
# ===== Step 5: retry target page with activated cookies =====
print("[5] GET eBay item page with activated cookies ...")
r2 = session.get(TARGET_URL, headers={**HEADERS, "referer": BASE_URL, "sec-fetch-site": "same-origin"})
print(f"    status={r2.status_code}  length={len(r2.text)}")

with open('data.html','w',encoding="utf-8") as f:
    f.write(r2.text)
