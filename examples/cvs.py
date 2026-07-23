"""
CVS.com 页面访问 - 基于 httpcloak + iv8 的 Akamai 绕过

CVS 使用 Akamai Bot Manager v2/v3，流程与 lowes_product.py 相同：
  1. httpcloak Session GET 页面，获取种子 Cookie
  2. 检测到 Akamai 挑战页，提取 Akamai sensor JS
  3. iv8 加载挑战页 + 模拟鼠标事件，逻辑时间推进
  4. 从 netLog.entries 捕获 sensor_data POST
  5. httpcloak 回传 sensor_data，获取有效 _abck，再次请求真实页面
"""
import json
import os
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import httpcloak
import iv8

TARGET_URL = "https://www.cvs.com/shop/cvs-health-distilled-water-128-oz-prodid-1190732"
BASE_URL = "https://www.cvs.com/"
PROXY = "http://127.0.0.1:7890"


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "priority": "u=0, i",
    "sec-ch-ua": '"Chromium";v="146", "Google Chrome";v="146", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA,
}

_AKAM_PATTERN = re.compile(r'^/[A-Za-z0-9_\-]{10,}/[A-Za-z0-9_\-]+/')


def is_akamai_challenge(html_text):
    return (
            'sec-if-cpt-container' in html_text
            or 'scf-akamai' in html_text
            or ('_abck' in html_text and len(html_text) < 50000)
    )


def extract_akamai_scripts(html, base_url):
    scripts = {}
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        # 绝对 URL 直接用，相对路径拼 base_url
        full_url = src if src.startswith("http") else urljoin(base_url, src)
        # 跳过太短或明显无关的
        if len(full_url) < 20:
            continue
        path_part = src if not src.startswith("http") else src.split("/", 3)[-1]
        if "/akam/" in path_part or "akam" in path_part.lower():
            scripts["bootstrap"] = full_url
        elif any(p in path_part for p in ["h8u_e", "sensor", "l_"]):
            scripts["sensor"] = full_url
        elif _AKAM_PATTERN.match("/" + path_part.lstrip("/")):
            scripts.setdefault(full_url, full_url)
        # very.co.uk: Akamai sensor path 形如 /VTK.../... 深度 >=3，长度足够
        elif src.startswith("/") and src.count("/") >= 3 and len(src) >= 20:
            scripts.setdefault(full_url, full_url)
    return scripts


def create_environment(page_url):
    parsed = urlparse(page_url)
    return {
        "navigator": {
            "userAgent": UA,
            "platform": "Win32",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "language": "en-US",
            "languages": ["en-US", "en"],
            "webdriver": False,
        },
        "screen": {
            "width": 1920,
            "height": 1080,
            "colorDepth": 24,
            "availWidth": 1920,
            "availHeight": 1040,
        },
        "window": {
            "innerWidth": 1920,
            "innerHeight": 969,
            "outerWidth": 1920,
            "outerHeight": 1040,
            "devicePixelRatio": 1.0,
        },
        "location": {
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
        "document": {
            "referrer": "",
            "visibilityState": "visible",
        },
    }


JS_REINFORCE = """(function() {
    try {
        var fakeRuntime = {
            OnInstalledReason: { CHROME_UPDATE:'chrome_update', INSTALL:'install', SHARED_MODULE_UPDATE:'shared_module_update', UPDATE:'update' },
            OnRestartRequiredReason: { APP_UPDATE:'app_update', OS_UPDATE:'os_update', PERIODIC:'periodic' },
            PlatformArch: { ARM:'arm', ARM64:'arm64', MIPS:'mips', MIPS64:'mips64', X86_32:'x86-32', X86_64:'x86-64' },
            PlatformOs: { ANDROID:'android', CROS:'cros', LINUX:'linux', MAC:'mac', OPENBSD:'openbsd', WIN:'win' },
            RequestUpdateCheckStatus: { NO_UPDATE:'no_update', THROTTLED:'throttled', UPDATE_AVAILABLE:'update_available' },
            id: undefined
        };
        if (!window.chrome) {
            try { Object.defineProperty(window, 'chrome', { value: { runtime: fakeRuntime, app: {}, csi: function(){ return {}; }, loadTimes: function(){ return {}; } }, configurable: true, writable: true }); } catch(e) { window.chrome = { runtime: fakeRuntime }; }
        } else if (!window.chrome.runtime) {
            try { window.chrome.runtime = fakeRuntime; } catch(e) {}
        }
    } catch(e) {}

    try {
        if (window.history && (window.history.length | 0) === 0) {
            try { Object.defineProperty(window.history, 'length', { value: 2, configurable: true }); } catch(e) {}
        }
    } catch(e) {}

    try {
        if (!window.performance) window.performance = {};
        var now = Date.now();
        var nav = now - 5000;
        if (!window.performance.timing || !window.performance.timing.navigationStart) {
            var t = {
                navigationStart: nav, fetchStart: nav + 10, domainLookupStart: nav + 20, domainLookupEnd: nav + 30,
                connectStart: nav + 40, secureConnectionStart: nav + 50, connectEnd: nav + 100,
                requestStart: nav + 110, responseStart: nav + 200, responseEnd: nav + 400,
                domLoading: nav + 410, domInteractive: nav + 800, domContentLoadedEventStart: nav + 850,
                domContentLoadedEventEnd: nav + 870, domComplete: nav + 1500, loadEventStart: nav + 1510,
                loadEventEnd: nav + 1520, unloadEventStart: 0, unloadEventEnd: 0, redirectStart: 0, redirectEnd: 0,
            };
            try { Object.defineProperty(window.performance, 'timing', { value: t, configurable: true }); } catch(e) { window.performance.timing = t; }
        }
        if (typeof window.performance.now !== 'function') {
            var _start = Date.now();
            window.performance.now = function(){ return Date.now() - _start; };
        }
    } catch(e) {}

    try {
        if (document.readyState !== 'complete' && document.readyState !== 'interactive') {
            try { Object.defineProperty(document, 'readyState', { get: function(){ return 'complete'; }, configurable: true }); } catch(e) {}
        }
        try { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); } catch(e) {}
        try { Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true }); } catch(e) {}
    } catch(e) {}

    try { document.hasFocus = function(){ return true; }; } catch(e) {}

    try {
        if (!navigator.plugins || navigator.plugins.length === undefined) {
            try { Object.defineProperty(navigator, 'plugins', { value: { length: 0, item: function(){ return null; }, namedItem: function(){ return null; }, refresh: function(){} }, configurable: true }); } catch(e) {}
        }
    } catch(e) {}
})();"""


def simulate_user_input(ctx):
    ctx.eval("""
        (function() {
            try {
                var doc = document.documentElement || document.body;
                if (!doc) return;
                var x = 200, y = 200;
                var n = 25 + Math.floor(Math.random() * 15);
                for (var i = 0; i < n; i++) {
                    x += Math.floor((Math.random() - 0.5) * 60);
                    y += Math.floor((Math.random() - 0.5) * 60);
                    if (x < 5) x = 5; if (x > 1900) x = 1900;
                    if (y < 5) y = 5; if (y > 1060) y = 1060;
                    try { __iv8__.input.dispatchMouseEvent({ type:'mousemove', target:doc, clientX:x, clientY:y, button:0, buttons:0 }); } catch(e) {}
                    try { __iv8__.input.dispatchPointerEvent({ type:'pointermove', target:doc, clientX:x, clientY:y, button:0, buttons:0, pointerId:1, pointerType:'mouse' }); } catch(e) {}
                }
                try { __iv8__.input.dispatchMouseEvent({ type:'mousedown', target:doc, clientX:x, clientY:y, button:0, buttons:1 }); } catch(e) {}
                try { __iv8__.input.dispatchMouseEvent({ type:'mouseup',   target:doc, clientX:x, clientY:y, button:0, buttons:0 }); } catch(e) {}
                try { __iv8__.input.dispatchMouseEvent({ type:'click',     target:doc, clientX:x, clientY:y, button:0, buttons:0 }); } catch(e) {}
            } catch(e) {}
        })();
    """)


def inject_cookies_to_iv8(ctx, session, domain=".cvs.com"):
    akamai_keys = ("_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi", "bm_s", "bm_sc", "bm_so", "bm_ss", "AKA_A2")
    jar = {c.name: c.value for c in session.cookies if c.name in akamai_keys}
    if not jar:
        return []
    js_lines = [
        f"document.cookie = {json.dumps(k)} + '=' + {json.dumps(v)} + '; path=/; domain={json.dumps(domain)}';"
        for k, v in jar.items()
    ]
    ctx.eval("(function(){ try { " + " ".join(js_lines) + " } catch(e) {} })();")
    return list(jar.keys())


def find_sensor_data(entries):
    candidates = []
    for e in entries:
        if e.get("method") != "POST":
            continue
        url = e.get("url", "") or ""
        body = e.get("body", "") or ""
        # 标准 sensor_data 格式
        if "sensor_data" in body:
            return url, body
        # very.co.uk Akamai v3：body 是 {"body":"..."} JSON，POST 到页面同路径（无 ?v= 参数）
        if "?v=" not in url and len(body) > 500 and body.startswith("{"):
            return url, body
        # 其他 Akamai 特征 URL
        if any(k in url for k in ["h8u_e", "sensor", "/_bm/"]):
            candidates.append((url, body, len(body)))
    if candidates:
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates[0][0], candidates[0][1]
    return None, None


def run_akamai_bypass(session, html, page_url, resources):
    environment = create_environment(page_url)

    with iv8.JSContext(environment=environment,
                       config={"time": {"mode": "logical"}, "timezone": "America/New_York"}) as ctx:
        snapshot = {
            "baseURL": page_url,
            "html": unescape(html),
            "resources": resources,
        }
        ctx.expose(snapshot, "s1")

        injected = inject_cookies_to_iv8(ctx, session)
        if injected:
            print(f"    [iv8] 注入初始 cookies: {injected}")

        ctx.eval(JS_REINFORCE)
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1);")
        ctx.eval(JS_REINFORCE)

        for tick in range(50):
            simulate_user_input(ctx)
            ctx.eval("window.__iv8__.eventLoop.advance(200);")
            if tick % 10 == 9:
                entries = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
                if any("sensor_data" in str(e.get("body", "")) for e in entries if e.get("method") == "POST"):
                    print(f"    [iv8] tick={tick} 发现 sensor_data POST，提前结束")
                    break

        ctx.eval("window.__iv8__.eventLoop.advance(3000);")

        entries = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
        print(f"    [iv8] netLog 捕获到 {len(entries)} 个请求")

        debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cvs_netlog_debug.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
            print(f"    [iv8] netLog 已保存到 {debug_path}")
        except Exception:
            pass

        return find_sensor_data(entries)


def get_cookies_dict(session):
    return {c.name: c.value for c in session.cookies}


def main():
    print("=" * 60)
    print("CVS.com 访问 - httpcloak + iv8 Akamai 绕过")
    print("=" * 60)

    session = httpcloak.Session(preset="chrome-146-windows", proxy=PROXY)

    print(f"\n[Step 1] GET {TARGET_URL}")
    r1 = session.get(TARGET_URL, headers=HEADERS,timeout=16)
    print(f"    status={r1.status_code}  protocol={r1.protocol}  len={len(r1.text)}")
    print(f"    cookies: {list(get_cookies_dict(session).keys())}")

    if r1.status_code == 200 and not is_akamai_challenge(r1.text):
        print("    [成功] 无挑战，直接获取到内容")
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cvs.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(r1.text)
        title = re.search(r'<title[^>]*>([^<]+)</title>', r1.text)
        print(f"    标题: {title.group(1).strip() if title else '(无)'}")
        print(f"    已保存到 {out}")
        return

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cvs_base_url.html")

    with open(out, "w", encoding="utf-8") as f:
        f.write(r1.text)

    print("    [信息] 检测到 Akamai 挑战页")

    print("\n[Step 2] 提取 Akamai 脚本...")
    scripts = extract_akamai_scripts(r1.text, BASE_URL)
    print(f"    找到 {len(scripts)} 个脚本:")
    for name, url in scripts.items():
        print(f"      [{name}] {url[:90]}")

    if not scripts:
        print("    [错误] 未找到 Akamai 脚本，保存挑战页")
        with open("cvs_challenge_debug.html", "w", encoding="utf-8") as f:
            f.write(r1.text)
        return

    print("\n[Step 3] 下载脚本...")
    script_headers = {
        **HEADERS,
        "accept": "*/*",
        "sec-fetch-dest": "script",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-site": "same-origin",
        "referer": TARGET_URL,
    }
    resources = {}
    for name, url in scripts.items():
        if url in resources:
            continue
        try:
            r_js = session.get(url, headers=script_headers)
            resources[url] = r_js.text
            print(f"    [{name}] status={r_js.status_code}  {len(r_js.text)} bytes")
        except Exception as e:
            print(f"    [{name}] 下载失败: {e}")

    if not resources:
        print("    [错误] 所有脚本下载失败")
        return

    print("\n[Step 4] iv8 运行 Akamai JS...")
    t0 = time.time()
    sensor_url, sensor_body = run_akamai_bypass(session, r1.text, TARGET_URL, resources)
    print(f"    iv8 耗时: {time.time() - t0:.2f}s")

    if not sensor_url or not sensor_body:
        print("    [错误] 未捕获到 sensor_data，查看 cvs_netlog_debug.json")
        return

    print(f"    sensor POST URL: {sensor_url[:100]}")
    print(f"    sensor body 长度: {len(sensor_body)}")

    print("\n[Step 5] POST sensor_data...")
    post_headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "text/plain;charset=UTF-8",
        "user-agent": UA,
        "sec-ch-ua": HEADERS["sec-ch-ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "referer": TARGET_URL,
        "origin": "https://www.cvs.com",
    }
    r_sensor = session.post(
        sensor_url,
        data=sensor_body.encode() if isinstance(sensor_body, str) else sensor_body,
        headers=post_headers,
    )
    print(f"    status={r_sensor.status_code}")
    print(f"    Set-Cookie: {r_sensor.headers.get('set-cookie', '(none)')[:200]}")

    abck = get_cookies_dict(session).get("_abck", "")
    if abck:
        print(f"    _abck: {abck[:100]}...")
        if "~0~" in abck:
            print("    [成功] _abck ~0~ 有效")
        elif "~-1~" in abck:
            print("    [警告] _abck ~-1~ sensor 校验未通过")

    print("\n[验证] 再次 GET 目标页...")
    r2 = session.get(TARGET_URL, headers={**HEADERS, "referer": "https://www.cvs.com/"})
    print(f"    status={r2.status_code}  len={len(r2.text)}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cvs.html")
    if r2.status_code == 200 and not is_akamai_challenge(r2.text):
        with open(out, "w", encoding="utf-8") as f:
            f.write(r2.text)
        title = re.search(r'<title[^>]*>([^<]+)</title>', r2.text)
        print(f"    标题: {title.group(1).strip() if title else '(无)'}")
        print(f"    [成功] 已保存到 {out}")
    else:
        with open("cvs_challenge2.html", "w", encoding="utf-8") as f:
            f.write(r2.text)
        print("    [失败] 仍有挑战，已保存到 cvs_challenge2.html")

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
