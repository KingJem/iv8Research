# -- coding: utf-8 -*-
"""
bol.com 产品页爬取 - 基于 iv8 的 Akamai 绕过
参考文档: iv8-python-v8-js-reverse.md 第五部分"通用 5 步 Akamai 绕过"
"""
import json
import os
import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
import iv8

# ── 配置 ──────────────────────────────────────────────
PRODUCT_URL = "https://www.bol.com/be/nl/p/intex-family-frame-zwembad-450x220x84cm-opzetzwembad/9200000040709668/"
BASE_URL = "https://www.bol.com/"

# 代理设置（None 表示不使用代理）
PROXY = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "nl-BE,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "max-age=0",
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


def is_akamai_challenge(html_text):
    """判断是否是 Akamai 挑战页"""
    indicators = [
        'sec-if-cpt-container',
        'scf-akamai',
        'akamai',
        '_abck',
        'bm_sz',
    ]
    html_lower = html_text.lower()
    for ind in indicators:
        if ind.lower() in html_lower and len(html_text) < 50000:
            return True
    return False


def extract_akamai_scripts(html, base_url):
    """
    Step 2: 动态提取 Akamai 脚本路径
    从挑战页中提取 bootstrap 和 sensor 脚本
    """
    scripts = {}
    # 匹配 src 属性中的脚本路径
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        # 只处理相对路径、深度足够的脚本
        if src.startswith("http") or src.startswith("//"):
            continue
        if src.count("/") < 3 or len(src) < 20:
            continue

        full_url = urljoin(base_url, src)

        # 区分 bootstrap 和 sensor 脚本
        if "/akam/" in src or "akam" in src.lower():
            scripts["bootstrap"] = full_url
        elif any(p in src for p in ["h8u_e", "sensor", "l_"]):
            scripts["sensor"] = full_url
        else:
            # 其他脚本也保存，用 URL 作为 key
            scripts[full_url] = full_url

    return scripts


def create_environment(page_url):
    """创建 iv8 运行环境配置"""
    parsed = urlparse(page_url)
    return {
        "navigator": {
            "userAgent": UA,
            "platform": "Win32",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "language": "nl-BE",
            "languages": ["nl-BE", "nl", "en-US", "en"],
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


# ── 环境补丁：补齐 Akamai 检测的关键浏览器 API ────────────────────
JS_REINFORCE = """(function() {
    // chrome.runtime — Akamai 会检测这个
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

    // history.length 兜底
    try {
        if (window.history && (window.history.length | 0) === 0) {
            try { Object.defineProperty(window.history, 'length', { value: 2, configurable: true }); } catch(e) {}
        }
    } catch(e) {}

    // performance.timing 兜底
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

    // document.readyState / hidden / visibilityState 兜底
    try {
        if (document.readyState !== 'complete' && document.readyState !== 'interactive') {
            try { Object.defineProperty(document, 'readyState', { get: function(){ return 'complete'; }, configurable: true }); } catch(e) {}
        }
        try { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); } catch(e) {}
        try { Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true }); } catch(e) {}
    } catch(e) {}

    // hasFocus
    try { document.hasFocus = function(){ return true; }; } catch(e) {}

    // navigator.plugins 兜底
    try {
        if (!navigator.plugins || navigator.plugins.length === undefined) {
            try { Object.defineProperty(navigator, 'plugins', { value: { length: 0, item: function(){ return null; }, namedItem: function(){ return null; }, refresh: function(){} }, configurable: true }); } catch(e) {}
        }
    } catch(e) {}
})();"""


def simulate_user_input(ctx):
    """模拟鼠标移动事件，让 sensor_data 包含真实输入轨迹"""
    ctx.eval("""
        (function() {
            try {
                var doc = document.documentElement || document.body;
                if (!doc) return;
                var pts = [];
                var n = 25 + Math.floor(Math.random() * 15);
                var x = 200, y = 200;
                for (var i = 0; i < n; i++) {
                    x += Math.floor((Math.random() - 0.5) * 60);
                    y += Math.floor((Math.random() - 0.5) * 60);
                    if (x < 5) x = 5; if (x > 1900) x = 1900;
                    if (y < 5) y = 5; if (y > 1060) y = 1060;
                    pts.push([x, y]);
                }
                pts.forEach(function(p, i) {
                    try {
                        __iv8__.input.dispatchMouseEvent({
                            type: 'mousemove', target: doc,
                            clientX: p[0], clientY: p[1],
                            button: 0, buttons: 0
                        });
                    } catch(e) {}
                    try {
                        __iv8__.input.dispatchPointerEvent({
                            type: 'pointermove', target: doc,
                            clientX: p[0], clientY: p[1],
                            button: 0, buttons: 0,
                            pointerId: 1, pointerType: 'mouse'
                        });
                    } catch(e) {}
                });
            } catch(e) {}
        })();
    """)


def inject_cookies_to_iv8(ctx, cookies, domain=".bol.com"):
    """将 curl_cffi session 的 cookie 注入到 iv8 的 document.cookie"""
    akamai_cookies = {k: v for k, v in cookies.items() if k in (
        "_abck", "ak_bmsc", "bm_sz", "bm_sv", "bm_mi", "bm_s", "bm_sc",
        "bm_so", "bm_ss", "AKA_A2", "BUI", "XSC", "XSRF-TOKEN"
    )}

    if not akamai_cookies:
        return []

    js_lines = []
    for k, v in akamai_cookies.items():
        js_lines.append(
            f"document.cookie = {json.dumps(k)} + '=' + "
            f"{json.dumps(v)} + '; path=/; domain={json.dumps(domain)}';"
        )

    ctx.eval("(function(){ try { " + " ".join(js_lines) + " } catch(e) {} })();")
    return list(akamai_cookies.keys())


def find_sensor_data_in_netlog(entries):
    """
    在 netLog.entries 中找到 Akamai sensor POST
    返回 (url, body) 或 (None, None)
    """
    candidates = []

    for e in entries:
        if e.get("method") != "POST":
            continue

        url = e.get("url", "") or ""
        body = e.get("body", "") or ""

        # 优先匹配：body 包含 sensor_data
        if "sensor_data" in body:
            return url, body

        # 次优先：URL 中包含特征
        if any(k in url for k in ["h8u_e", "sensor", "/_bm/"]):
            candidates.append((url, body, len(body)))

    if candidates:
        # 取 body 最长的
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates[0][0], candidates[0][1]

    return None, None


def run_akamai_bypass(session, html, page_url, resources):
    """
    Step 4: iv8 运行 Akamai JS
    使用 netLog 捕获 XHR/fetch 请求
    """
    environment = create_environment(page_url)

    with iv8.JSContext(environment=environment, config={"time": {"mode": "logical"}}) as ctx:
        # 准备 snapshot 数据
        snapshot = {
            "baseURL": page_url,
            "html": unescape(html),
            "resources": resources,
        }
        ctx.expose(snapshot, "s1")

        # 注入初始 cookie
        injected = inject_cookies_to_iv8(ctx, session.cookies)
        if injected:
            print(f"    [iv8] 注入初始 cookies: {injected}")

        # 注入环境补丁（在 page.load 之前）
        ctx.eval(JS_REINFORCE)

        # 加载页面（同步执行 HTML 中的 script 标签）
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1);")

        # 加载后再补一次（兜底）
        ctx.eval(JS_REINFORCE)

        # 推进逻辑事件循环 + 模拟用户输入
        for tick in range(50):
            simulate_user_input(ctx)
            ctx.eval("window.__iv8__.eventLoop.advance(200);")

            # 每 10 个 tick 检查一下是否有 sensor_data
            if tick % 10 == 9:
                entries = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
                for e in entries:
                    if e.get("method") == "POST" and "sensor_data" in str(e.get("body", "")):
                        print(f"    [iv8] tick={tick} 发现 sensor_data POST")
                        break

        # 最终再推进一下确保完成
        ctx.eval("window.__iv8__.eventLoop.advance(3000);")

        # 从 netLog.entries 提取 sensor_data
        entries = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
        print(f"    [iv8] netLog 捕获到 {len(entries)} 个请求")

        # 保存 netLog 用于调试
        debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bol_netlog_debug.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
            print(f"    [iv8] netLog 已保存到 {debug_path}")
        except Exception:
            pass

        return find_sensor_data_in_netlog(entries)


def main():
    print("=" * 60)
    print("bol.com 产品页爬取 - iv8 Akamai 绕过")
    print("=" * 60)

    # Step 1: GET 页面，获取种子 Cookie
    print("\n[Step 1] GET 产品页...")
    session = requests.Session(impersonate="chrome124")

    # 访问目标产品页
    r1 = session.get(PRODUCT_URL, headers=HEADERS, proxy=PROXY, timeout=30)
    print(f"    产品页状态: {r1.status_code}, cookies: {list(r1.cookies.keys())}")
    print(f"    内容长度: {len(r1.text)}")

    # 如果没有挑战，直接返回
    if r1.status_code == 200 and not is_akamai_challenge(r1.text):
        print("    [成功] 没有挑战页，直接获取到内容")
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bol_product.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(r1.text)
        print(f"    已保存到 {output_path}")

        # 尝试解析一些产品信息
        title_match = re.search(r'<title>([^<]+)</title>', r1.text)
        if title_match:
            print(f"    产品标题: {title_match.group(1)}")
        return

    if r1.status_code != 200:
        print(f"    [警告] 状态码 {r1.status_code}，可能被封")
        err_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"bol_error_{r1.status_code}.html")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(r1.text)
        return

    html = r1.text
    print("    [信息] 检测到 Akamai 挑战页")

    # Step 2: 动态提取 Akamai 脚本路径
    print("\n[Step 2] 提取 Akamai 脚本...")
    scripts = extract_akamai_scripts(html, BASE_URL)
    print(f"    找到 {len(scripts)} 个脚本:")
    for name, url in scripts.items():
        print(f"      [{name}] {url[:80]}...")

    if not scripts:
        print("    [错误] 未找到 Akamai 脚本")
        # 保存 HTML 用于调试
        debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bol_challenge_debug.html")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    已保存挑战页到 {debug_path}")
        return

    # Step 3: 同一 Session 下载脚本
    print("\n[Step 3] 下载脚本...")
    script_headers = {
        **HEADERS,
        "accept": "*/*",
        "sec-fetch-dest": "script",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-site": "same-origin",
        "referer": PRODUCT_URL,
    }

    resources = {}
    for name, url in scripts.items():
        if url in resources:
            continue
        try:
            r_js = session.get(url, headers=script_headers, proxy=PROXY, timeout=30)
            resources[url] = r_js.text
            print(f"    {name}: {r_js.status_code}, {len(r_js.text)} bytes")
        except Exception as e:
            print(f"    {name}: 下载失败 - {e}")

    if not resources:
        print("    [错误] 所有脚本下载失败")
        return

    # Step 4: iv8 运行 Akamai JS
    print("\n[Step 4] iv8 运行 Akamai JS...")
    start_time = time.time()

    sensor_url, sensor_body = run_akamai_bypass(session, html, PRODUCT_URL, resources)

    print(f"    iv8 运行耗时: {time.time() - start_time:.2f}s")

    if not sensor_url or not sensor_body:
        print("    [错误] 未捕获到 sensor_data")
        return

    print(f"    捕获到 sensor POST:")
    print(f"      URL: {sensor_url[:100]}...")
    print(f"      Body 长度: {len(sensor_body)}")

    # Step 5: 回传 sensor_data，验证通过
    print("\n[Step 5] POST sensor_data...")
    post_headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "nl-BE,nl;q=0.9",
        "content-type": "text/plain;charset=UTF-8",
        "user-agent": UA,
        "sec-ch-ua": HEADERS["sec-ch-ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "referer": PRODUCT_URL,
        "origin": "https://www.bol.com",
    }

    r_sensor = session.post(
        sensor_url,
        data=sensor_body.encode() if isinstance(sensor_body, str) else sensor_body,
        headers=post_headers,
        proxy=PROXY,
        timeout=30,
    )
    print(f"    状态: {r_sensor.status_code}")
    print(f"    Set-Cookie: {r_sensor.headers.get('set-cookie', '(none)')[:200]}")
    session.cookies.update(r_sensor.cookies)

    # 检查 _abck 状态
    abck = session.cookies.get("_abck", domain=".bol.com") or session.cookies.get("_abck")
    if abck:
        print(f"    _abck: {abck[:100]}...")
        if "~0~" in abck:
            print("    [成功] _abck 包含 ~0~ (有效)")
        elif "~-1~" in abck:
            print("    [警告] _abck 包含 ~-1~ (sensor 校验未通过)")

    # 再次请求产品页
    print("\n[验证] 再次请求产品页...")
    r2 = session.get(PRODUCT_URL, headers=HEADERS, proxy=PROXY, timeout=30)
    print(f"    状态: {r2.status_code}, 长度: {len(r2.text)}")

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bol_product.html")
    if r2.status_code == 200 and not is_akamai_challenge(r2.text):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(r2.text)
        print(f"    [成功] 已保存到 {output_path}")
    else:
        challenge_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bol_challenge.html")
        with open(challenge_path, "w", encoding="utf-8") as f:
            f.write(r2.text)
        print(f"    [失败] 仍有挑战，保存到 {challenge_path}")

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
