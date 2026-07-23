"""Chewy.com Kasada(KPSDK)绕过 —— httpcloak 版

链路:GET 搜索页(429 挑战)→ 取 ips.js → iv8 跑出 /tl POST → 回传激活 KP_UIDz-ssn → 重试搜索。
请求库用 httpcloak(非 curl_cffi)。**版本高度一致**:httpcloak preset / UA / sec-ch-ua / iv8
environment.navigator.userAgent 全部对齐 Chrome 146,避免 TLS 指纹与 JS 环境版本不一致被判异常。

本机(py310)跑:python examples/chewy.py
"""
import json
import re
import sys
import time
from html import unescape
from urllib.parse import urljoin

import httpcloak
import iv8

BASE_URL = "https://www.chewy.com/"
SEARCH_URL = "https://www.chewy.com/s"
SEARCH_PARAMS = {"query": "water", "nav-submit-button": ""}

# —— 全链对齐 Chrome 146 ——
PRESET = "chrome-146-windows"                       # httpcloak TLS 指纹
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
SEC_CH_UA = '"Chromium";v="146", "Google Chrome";v="146", "Not-A.Brand";v="99"'

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-US,en;q=0.9",
    "priority": "u=0, i",
    "sec-ch-ua": SEC_CH_UA,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA,
}

s = httpcloak.Session(preset=PRESET, timeout=30)

# 手动累积 cookie(httpcloak Response 无 .cookies、jar 读取不透明;iv8 0.1.4 的头值/cookieHeader 是 list)
COOKIES = {}


def _first(v):
    """iv8 netLog 与 httpcloak 响应头的值可能是 list,取首元素为 str。"""
    if isinstance(v, (list, tuple)):
        return str(v[0]) if v else ""
    return "" if v is None else str(v)


def collect_setcookie(resp):
    sc = resp.headers.get("set-cookie") if hasattr(resp.headers, "get") else None
    if not sc:
        return
    for item in (sc if isinstance(sc, (list, tuple)) else [sc]):
        first = str(item).split(";")[0].strip()
        if "=" in first:
            k, _, v = first.partition("=")
            COOKIES[k.strip()] = v.strip()


def parse_cookies(cookie_str):
    out = {}
    cookie_str = ";".join(cookie_str) if isinstance(cookie_str, (list, tuple)) else (cookie_str or "")
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


# ===== Step 1: GET 挑战页(期望 429 + KPSDK 挑战) =====
print(f"[1] GET chewy search (preset={PRESET}, UA=Chrome/146) ...")
r1 = s.get(SEARCH_URL, params=SEARCH_PARAMS, headers=HEADERS)
collect_setcookie(r1)
print(f"    status={r1.status_code}")
html = unescape(r1.text)

script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
if not script_srcs:
    raise RuntimeError("挑战页没有 <script src>")
ips_url = urljoin(BASE_URL, script_srcs[0])
print(f"[2] ips.js URL: {ips_url[:100]}...")

# ===== Step 2: 取 ips.js =====
r_js = s.get(ips_url, headers={**HEADERS, "accept": "*/*", "referer": BASE_URL,
                               "sec-fetch-dest": "script", "sec-fetch-mode": "no-cors",
                               "sec-fetch-site": "same-origin"})
collect_setcookie(r_js)
print(f"    js status={r_js.status_code}  length={len(r_js.text)}")

# ===== Step 3: iv8 跑 ips.js,抓 /tl POST =====
print("[3] Running iv8 ...")
start = time.time()

# iv8 环境的 UA 必须和 httpcloak preset 同版本(Chrome 146),否则 Kasada 会发现 TLS↔JS 指纹不一致
environment = {
    "location": {"ancestorOrigins": {}, "href": BASE_URL, "origin": "https://www.chewy.com",
                 "protocol": "https:", "host": "www.chewy.com", "hostname": "www.chewy.com",
                 "port": "", "pathname": "/", "search": "", "hash": ""},
    "navigator": {"userAgent": UA, "platform": "Win32", "hardwareConcurrency": 8,
                  "language": "en-US", "languages": ["en-US", "en"]},
    "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
}

tl_url, tl_body, tl_hdrs, tl_cookie = None, "", {}, ""

with iv8.JSContext(environment=environment, config={"time": {"mode": "logical"}}) as ctx:
    ctx.expose({"baseURL": BASE_URL, "html": html,
                "headers": [[str(k), str(v)] for k, v in dict(r1.headers).items()],
                "resources": {ips_url: str(r_js.text)}}, "snapshot")

    ctx.eval("""(function() {
        try {  // iv8 0.1.4 未实现 FileList wrapper,ips.js 访问 dataTransfer.files 会崩(exit 127)
            if (window.DataTransfer && DataTransfer.prototype) {
                Object.defineProperty(DataTransfer.prototype, 'files', {configurable:true, get:function(){return [];}});
            }
        } catch(e) {}
        try {
            if (typeof window.TouchEvent === 'undefined') {
                window.TouchEvent = function(type, init){ var e=new Event(type, init||{}); e.touches=e.targetTouches=e.changedTouches=[]; return e; };
            }
            if (typeof window.Touch === 'undefined') { window.Touch = function(init){ Object.assign(this, init||{}); }; }
        } catch(e) {}
        try {
            var _ce = Document.prototype.createEvent;
            Document.prototype.createEvent = function(type){ try{return _ce.call(this,type);}catch(e){ var evt=new Event(type||'Event',{bubbles:true,cancelable:true}); if(type==='TouchEvent'){evt.touches=evt.targetTouches=evt.changedTouches=[];} return evt; } };
        } catch(e) {}
        try {
            var _as = Element.prototype.attachShadow;
            Element.prototype.attachShadow = function(init){ try{return _as.call(this,init);}catch(e){return document.createElement('div');} };
        } catch(e) {}
        try {
            if (navigator.permissions && navigator.permissions.query) {
                var _pq = navigator.permissions.query.bind(navigator.permissions);
                navigator.permissions.query = function(desc){ if(!desc||!desc.name) return Promise.resolve({state:'prompt'}); return _pq(desc).catch(function(){return {state:'prompt'};}); };
            }
        } catch(e) {}
    })();""")

    ctx.eval("__iv8__.page.load(__iv8__.data.snapshot);")
    for tick in range(60):
        entries = ctx.eval("__iv8__.netLog.entries", to_py=True) or []
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
            print(f"    [tick {tick:02d}] netLog={len(entries)} entries")
        ctx.eval("__iv8__.eventLoop.sleep(100);")
    else:
        print("    [warn] 60 tick 内没抓到 /tl")

print(f"    iv8 done in {time.time() - start:.2f}s")

if not tl_url:
    print("[warn] 未捕获 /tl")
    sys.exit(1)

# ===== Step 3b: 回传 /tl 激活 KP_UIDz-ssn =====
print(f"[3b] POST {tl_url[:80]}...")
tl_headers = {**HEADERS, "accept": "*/*", "referer": BASE_URL,
              "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
              "content-type": tl_hdrs.get("content-type", "application/octet-stream")}
for h in ("x-kpsdk-ct", "x-kpsdk-im"):
    if tl_hdrs.get(h):
        tl_headers[h] = _first(tl_hdrs[h])
tl_headers.pop("sec-fetch-user", None)

r_tl = s.post(tl_url, data=tl_body.encode() if isinstance(tl_body, str) else tl_body,
              headers=tl_headers, cookies={**COOKIES, **parse_cookies(tl_cookie)})
collect_setcookie(r_tl)
print(f"    /tl status={r_tl.status_code}")
ct = _first(r_tl.headers.get("x-kpsdk-ct", "")) if hasattr(r_tl.headers, "get") else ""
print(f"    x-kpsdk-ct: {ct[:60] if ct else '(none)'}")

# ===== Step 4: 带激活 cookie + x-kpsdk-ct 重试 =====
print(f"[4] Retrying search ... (cookies: {list(COOKIES.keys())})")
retry_headers = {**HEADERS, "referer": BASE_URL, "sec-fetch-site": "same-origin"}
retry_headers.pop("sec-fetch-user", None)
if ct:
    retry_headers["x-kpsdk-ct"] = ct

r2 = s.get(SEARCH_URL, params=SEARCH_PARAMS, headers=retry_headers, cookies=COOKIES)
print(f"    status={r2.status_code}  length={len(r2.text)}")
low = r2.text.lower()
real = r2.status_code == 200 and len(r2.text) > 50000 and ("data-testid" in low or "add to cart" in low or "product" in low)
print(f"    [结果] {'✅ 出真实搜索页' if real else '⚠️ 仍是挑战/未出值'}")
print("   ", re.sub(r"\s+", " ", r2.text[:300]))
