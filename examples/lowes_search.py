import json
import re
import sys
import time
from html import unescape
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
import iv8

SEARCH_URL = "https://www.lowes.com/search?searchTerm=dishwasher+soap"
BASE_URL = "https://www.lowes.com/"

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

JS_HEADERS = {
    **HEADERS,
    "accept": "*/*",
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "same-origin",
}

_AKAM_PATTERN = re.compile(r'^/[A-Za-z0-9_\-]{10,}/[A-Za-z0-9_\-]+/')

JS_PATCHES = """(function() {
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
})();"""


def is_akamai_challenge(html_text):
    return 'sec-if-cpt-container' in html_text or 'scf-akamai' in html_text


def install_xhr_bridge(ctx, session, page_url):
    """Bridge XHR requests through curl_cffi so _bm/get_params is really fetched."""

    def real_fetch(method, url, body, headers_json):
        method = str(method).upper()
        url = str(url)
        req_headers = json.loads(str(headers_json)) if headers_json else {}
        req_body = str(body) if body and str(body) != "null" else None
        print(f"    [bridge] {method} {url[:80]}")
        try:
            r = session.request(
                method, url,
                data=req_body.encode() if req_body else None,
                headers={**JS_HEADERS, "referer": page_url, **req_headers},
            )
            print(f"    [bridge] -> {r.status_code}  len={len(r.text)}")
            session.cookies.update(r.cookies)
            ctx.add_resource(
                url=url,
                body=r.text,
                status=r.status_code,
                headers=dict(r.headers),
            )
        except Exception as exc:
            print(f"    [bridge] error: {exc}")
            ctx.add_resource(url=url, body="", status=500, headers={})

    ctx.expose(real_fetch, "realFetch")

    ctx.eval("""
        (function() {
            var _origOpen  = XMLHttpRequest.prototype.open;
            var _origSend  = XMLHttpRequest.prototype.send;
            var _origSetHdr = XMLHttpRequest.prototype.setRequestHeader;

            XMLHttpRequest.prototype.open = function(method, url) {
                this.__method  = method;
                this.__url     = url;
                this.__headers = {};
                return _origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                this.__headers[name] = value;
                return _origSetHdr.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
                __iv8__.data.realFetch(
                    this.__method,
                    this.__url,
                    body,
                    JSON.stringify(this.__headers || {})
                );
                return _origSend.apply(this, arguments);
            };
        })();
    """)


def solve_challenge(session, page_url, base_url, resp):
    html = unescape(resp.text)

    script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    akam_scripts = [s for s in script_srcs if _AKAM_PATTERN.match(s)]
    print(f"    Akamai scripts: {len(akam_scripts)}")
    if not akam_scripts:
        return False

    resources = {}
    for path in akam_scripts:
        url = urljoin(base_url, path)
        r = session.get(url, headers={**JS_HEADERS, "referer": page_url})
        print(f"    fetched {url[:80]}  status={r.status_code}  len={len(r.text)}")
        resources[url] = r.text

    akam_path = akam_scripts[0]
    akam_base = akam_path.split("?")[0]

    parsed = urlparse(page_url)
    environment = {
        "location": {
            "ancestorOrigins": {},
            "href": page_url,
            "origin": f"{parsed.scheme}://{parsed.netloc}",
            "protocol": f"{parsed.scheme}:",
            "host": parsed.netloc,
            "hostname": parsed.netloc,
            "port": "",
            "pathname": parsed.path,
            "search": ("?" + parsed.query) if parsed.query else "",
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
    sensor_cookie = ""

    start_t = time.time()
    with iv8.JSContext(environment=environment, config={"time": {"mode": "logical"}}) as ctx:
        ctx.expose({
            "baseURL": base_url,
            "html": html,
            "headers": [[k, v] for k, v in resp.headers.items()],
            "resources": resources,
        }, "snapshot")
        ctx.eval(JS_PATCHES)
        # install XHR bridge before page.load so _bm/get_params is truly fetched
        install_xhr_bridge(ctx, session, page_url)
        ctx.eval("__iv8__.page.load(__iv8__.data.snapshot);")

        for tick in range(80):
            entries = ctx.eval("__iv8__.netLog.entries", to_py=True) or []

            with open("netlog_dump.json", "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)

            sensor = None
            for e in entries:
                if e.get("method") == "POST" and any(k in e.get("url", "") for k in ["sensor_data", "h8u_e", akam_base]):
                    sensor = e
                    break
            if sensor is None:
                posts = [e for e in entries if e.get("method") == "POST"]
                if posts:
                    sensor = posts[0]

            if sensor:
                sensor_url = sensor.get("url", "")
                sensor_body = sensor.get("body", "") or sensor.get("postData", {}).get("text", "")
                sensor_cookie = sensor.get("cookieHeader", "")
                print(f"    [iv8] sensor POST at tick={tick}: {sensor_url[:80]}")
                print(f"    [iv8] body_len={len(sensor_body)}  cookie={sensor_cookie[:60]}")
                break

            if tick % 10 == 0:
                urls = [e.get("url", "")[:60] for e in entries if e.get("url", "").startswith("http")]
                print(f"    [tick {tick:02d}] entries={len(entries)}  urls={urls}")
            ctx.eval("__iv8__.eventLoop.sleep(100);")
        else:
            print("    [warn] sensor POST not found after 80 ticks")

    print(f"    iv8 done in {time.time() - start_t:.2f}s")

    if not sensor_url:
        return False

    if sensor_cookie:
        for part in sensor_cookie.split(";"):
            part = part.strip()
            if "=" in part:
                ck, _, cv = part.partition("=")
                session.cookies.set(ck.strip(), cv.strip(), domain="www.lowes.com")

    post_headers = {
        **HEADERS,
        "accept": "*/*",
        "content-type": "application/json",
        "referer": page_url,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    r_sensor = session.post(
        sensor_url,
        data=sensor_body.encode() if isinstance(sensor_body, str) else sensor_body,
        headers=post_headers,
    )
    print(f"    POST status={r_sensor.status_code}  set-cookie={r_sensor.headers.get('set-cookie', '')[:80]}")
    session.cookies.update(r_sensor.cookies)
    print(f"    cookies after POST: {list(session.cookies.keys())}")
    return r_sensor.status_code in (200, 201)


# ===== main =====
session = requests.Session(impersonate="chrome124")

for attempt in range(4):
    print(f"\n[GET attempt {attempt + 1}] {SEARCH_URL}")
    resp = session.get(SEARCH_URL, headers=HEADERS)
    print(f"    status={resp.status_code}  len={len(resp.text)}")

    if not is_akamai_challenge(resp.text):
        print("    [info] No challenge — saving result")
        with open("lowes_search.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("    saved to lowes_search.html")
        break

    print(f"    [info] Akamai challenge on attempt {attempt + 1}, solving...")
    ok = solve_challenge(session, SEARCH_URL, BASE_URL, resp)
    if not ok:
        print("    [warn] solve_challenge failed")
        sys.exit(1)
else:
    print("[warn] Still challenged after 4 attempts — check netlog_dump.json")
    sys.exit(1)
