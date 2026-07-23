import json
import re
import time
from urllib.parse import urljoin

import iv8
from curl_cffi import requests

PAGE_URL = "https://www.very.co.uk/search/water"
BASE_URL = "https://www.very.co.uk"
# 与 iv8 0.1.4 的 profile=chrome124_win 对齐:0.1.4 修复了旧版 UA=124/brands=125 的不一致,
# 现在 navigator.userAgent 与 userAgentData.brands 都是干净的 Chrome/124。
# (0.1.2 时 brands 曾误报 v125+Not.A/Brand;v24,那套 125 对齐在 0.1.4 下反而不匹配,已回退到 124。)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# sec-ch-ua 必须等于 navigator.userAgentData.brands 的序列化(0.1.4 输出 v124 + Not-A.Brand;v99)。
SEC_CH_UA = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'

DOCUMENT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "max-age=0",
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

SCRIPT_HEADERS = {
    "accept": "*/*",
    "accept-language": DOCUMENT_HEADERS["accept-language"],
    "referer": PAGE_URL,
    "sec-ch-ua": DOCUMENT_HEADERS["sec-ch-ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "same-origin",
    "user-agent": UA,
}

XHR_HEADERS = {
    "accept": "*/*",
    "accept-language": DOCUMENT_HEADERS["accept-language"],
    "origin": BASE_URL,
    "referer": PAGE_URL,
    "sec-ch-ua": DOCUMENT_HEADERS["sec-ch-ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": UA,
    "content-type": "text/plain;charset=UTF-8",
}

# Akamai bmak pixel(/akam/<ver>/<id>)= 遥测,body 是 form-urlencoded。
# 注意:这不是 very 验证 _abck 的那一发,真正的 sensor_data POST 走下面的混淆动态路径。
AKAM_PIXEL_HEADERS = {
    **{k: v for k, v in XHR_HEADERS.items() if k != "content-type"},
    "content-type": "application/x-www-form-urlencoded",
}
AKAM_PIXEL_RE = re.compile(r"/akam/\d+/[A-Za-z0-9_]+")


def classify_request(method, url, body):
    """区分 very 的三类回传请求(真正验证 _abck 的是 'sensor')。"""
    if "/akam/" in url and AKAM_PIXEL_RE.search(url):
        return "akam-pixel"            # bmak 遥测,form-urlencoded
    if method == "GET" and "/_bm/get_params" in url:
        return "bm-get-params"
    if method == "POST" and body:
        b = body.lstrip()
        # v3 sensor_data:混淆随机路径(无 ?v=)、body 为 {...} JSON 或含 sensor_data → 这就是关键的那一发
        if "sensor_data" in body or b.startswith("{") or b.startswith("["):
            return "sensor"
        return "post"
    return "other"


def chrome_environment(cookies):
    return {
        "location": {
            "protocol": "https:",
            "hostname": "www.very.co.uk",
            "host": "www.very.co.uk",
            "port": "",
            "pathname": "/search/water",
            "href": PAGE_URL,
            "search": "",
            "hash": "",
            "origin": BASE_URL,
        },
        "navigator": {
            "userAgent": UA,
            "appVersion": UA.removeprefix("Mozilla/"),
            "platform": "Win32",
            "vendor": "Google Inc.",
            "vendorSub": "",
            "productSub": "20030107",
            "appName": "Netscape",
            "appCodeName": "Mozilla",
            "product": "Gecko",
            "language": "en-GB",
            "languages": ["en-GB", "en-US", "en"],
            "onLine": True,
            "cookieEnabled": True,
            "webdriver": False,
            "pdfViewerEnabled": True,
            "hardwareConcurrency": 12,
            "maxTouchPoints": 0,
            "deviceMemory": 8.0,
            "userAgentData": {
                "platform": "Windows",
                "architecture": "x86",
                "bitness": "64",
                "model": "",
                "platformVersion": "10.0.0",
                "mobile": False,
                "wow64": False,
            },
            "connection": {
                "type": "wifi",
                "effectiveType": "4g",
                "downlinkMax": 10.0,
                "rtt": 50.0,
                "downlink": 10.0,
                "saveData": False,
            },
            "plugins": {"enabled": True},
        },
        "window": {
            "name": "",
            "status": "",
            "origin": BASE_URL,
            "innerWidth": 1920,
            "innerHeight": 969,
            "outerWidth": 1920,
            "outerHeight": 1040,
            "screenLeft": 0,
            "screenTop": 0,
            "screenX": 0,
            "screenY": 0,
            "length": 0,
            "devicePixelRatio": 1.0,
            "scrollX": 0.0,
            "scrollY": 0.0,
            "closed": False,
            "hasOpener": False,
            "isSecureContext": True,
            # crossOriginIsolated / originAgentCluster / credentialless are NOT
            # settable here in iv8 0.1.2 — they are derived from page.load()
            # response headers (COEP/COOP/Origin-Agent-Cluster), so omit them.
        },
        "screen": {
            "width": 1920,
            "height": 1080,
            "availWidth": 1920,
            "availHeight": 1040,
            "availLeft": 0,
            "availTop": 0,
            "colorDepth": 24,
            "pixelDepth": 24,
            "isExtended": False,
            "orientation": {"type": "landscape-primary", "angle": 0},
        },
        "document": {
            "domain": "www.very.co.uk",
            "referrer": "",
            "readyState": "complete",
            "visibilityState": "visible",
            "lastModified": "01/01/1970 00:00:00",
            "dir": "",
            "designMode": "off",
            "wasDiscarded": False,
            "prerendering": False,
            "cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        },
        "media": {
            "displayMode": "browser",
            "displayState": "normal",
            "prefersColorScheme": "light",
            "prefersContrast": "no-preference",
            "prefersReducedMotion": "no-preference",
            "prefersReducedData": "no-preference",
            "forcedColors": "none",
            "colorGamut": "srgb",
            "scripting": "enabled",
            "update": "fast",
            "pointer": "fine",
            "hover": "hover",
            "anyPointer": "fine",
            "anyHover": "hover",
            "resizable": True,
            "invertedColors": False,
            "deviceSupportsHDR": False,
        },
        "webgl": {
            "VENDOR": "WebKit",
            "RENDERER": "WebKit WebGL",
            "VERSION": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
            "SHADING_LANGUAGE_VERSION": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
            "UNMASKED_VENDOR_WEBGL": "Google Inc. (NVIDIA)",
            "UNMASKED_RENDERER_WEBGL": (
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 (0x00001F82) "
                "Direct3D11 vs_5_0 ps_5_0, D3D11)"
            ),
            "version": {
                "webgl1": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
                "webgl2": "WebGL 2.0 (OpenGL ES 3.0 Chromium)",
            },
            "shadingLanguageVersion": {
                "webgl1": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
                "webgl2": "WebGL GLSL ES 3.00 (OpenGL ES GLSL ES 3.0 Chromium)",
            },
            "MAX_TEXTURE_SIZE": 16384,
            "MAX_CUBE_MAP_TEXTURE_SIZE": 16384,
            "MAX_TEXTURE_IMAGE_UNITS": 16,
            "MAX_COMBINED_TEXTURE_IMAGE_UNITS": 32,
            "MAX_VERTEX_TEXTURE_IMAGE_UNITS": 16,
            "MAX_VERTEX_ATTRIBS": 16,
            "MAX_VERTEX_UNIFORM_VECTORS": 4095,
            "MAX_VARYING_VECTORS": 30,
            "MAX_FRAGMENT_UNIFORM_VECTORS": 1024,
            "MAX_RENDERBUFFER_SIZE": 16384,
            "MAX_VIEWPORT_DIMS": {"0": 32767, "1": 32767},
            "RED_BITS": 8,
            "GREEN_BITS": 8,
            "BLUE_BITS": 8,
            "ALPHA_BITS": 8,
            "DEPTH_BITS": 24,
            "STENCIL_BITS": 0,
            "SUBPIXEL_BITS": 4,
            "ALIASED_LINE_WIDTH_RANGE": {"0": 1.0, "1": 1.0},
            "ALIASED_POINT_SIZE_RANGE": {"0": 1.0, "1": 1024.0},
            "MAX_TEXTURE_MAX_ANISOTROPY_EXT": 16.0,
            "POLYGON_OFFSET_CLAMP_EXT": 0.0,
            "SHADER_PRECISION": {
                "VERTEX_SHADER": {
                    "LOW_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "MEDIUM_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "HIGH_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "LOW_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                    "MEDIUM_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                    "HIGH_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                },
                "FRAGMENT_SHADER": {
                    "LOW_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "MEDIUM_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "HIGH_FLOAT": {"rangeMin": 127, "rangeMax": 127, "precision": 23},
                    "LOW_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                    "MEDIUM_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                    "HIGH_INT": {"rangeMin": 31, "rangeMax": 30, "precision": 0},
                },
            },
        },
        "webgl2": {
            "MAX_COMBINED_UNIFORM_BLOCKS": 24,
            "MAX_UNIFORM_BUFFER_BINDINGS": 24,
            "MAX_UNIFORM_BLOCK_SIZE": 65536,
            "MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS": 212988,
            "MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS": 200704,
            "UNIFORM_BUFFER_OFFSET_ALIGNMENT": 256,
            "MAX_VERTEX_UNIFORM_COMPONENTS": 16380,
            "MAX_VERTEX_UNIFORM_BLOCKS": 12,
            "MAX_VERTEX_OUTPUT_COMPONENTS": 120,
            "MAX_VARYING_COMPONENTS": 120,
            "MAX_FRAGMENT_UNIFORM_COMPONENTS": 4096,
            "MAX_FRAGMENT_UNIFORM_BLOCKS": 12,
            "MAX_FRAGMENT_INPUT_COMPONENTS": 120,
            "MIN_PROGRAM_TEXEL_OFFSET": -8,
            "MAX_PROGRAM_TEXEL_OFFSET": 7,
            "MAX_DRAW_BUFFERS": 8,
            "MAX_COLOR_ATTACHMENTS": 8,
            "MAX_SAMPLES": 8,
            "MAX_3D_TEXTURE_SIZE": 2048,
            "MAX_ARRAY_TEXTURE_LAYERS": 2048,
            "MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS": 120,
            "MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS": 4,
            "MAX_TRANSFORM_FEEDBACK_SEPARATE_COMPONENTS": 4,
            "MAX_TEXTURE_LOD_BIAS": 2.0,
        },
        "audioContext": {
            "baseLatency": 0.01,
            "outputLatency": 0.02,
        },
        "visualViewport": {
            "scale": 1.0,
            "offsetLeft": 0.0,
            "offsetTop": 0.0,
            "pageLeft": 0.0,
            "pageTop": 0.0,
        },
        "storage": {
            "usage": 0.0,
            "quota": 2400014910258.0,
            "persisted": False,
            "usageDetails": {
                "indexedDB": 0.0,
                "caches": 0.0,
                "serviceWorkerRegistrations": 0.0,
                "fileSystem": 0.0,
            },
        },
        "performance": {
            "navigation": {"type": 0.0, "redirectCount": 0.0},
            "memory": {
                "usedJSHeapSize": 5765120.0,
                "totalJSHeapSize": 6991872.0,
                "jsHeapSizeLimit": 4294705152.0,
            },
        },
        "batteryManager": {
            "charging": True,
            "chargingTime": 0.0,
            "dischargingTime": float("inf"),
            "level": 1.0,
        },
        "history": {
            "length": 1,
            "scrollRestoration": "auto",
        },
        "webrtc": {
            "ice": {
                "defaultHostIPv4": "192.168.0.100",
                "defaultMdnsHostname": "",
            },
        },
        # "chrome": {
        #     "app": {
        #         "isInstalled": False,
        #         "InstallState": {
        #             "DISABLED": "disabled",
        #             "INSTALLED": "installed",
        #             "NOT_INSTALLED": "not_installed",
        #         },
        #         "RunningState": {
        #             "CANNOT_RUN": "cannot_run",
        #             "READY_TO_RUN": "ready_to_run",
        #             "RUNNING": "running",
        #         },
        #     },
        #     "loadTimes": {
        #         "navigationType": "Other",
        #         "npnNegotiatedProtocol": "h2",
        #         "connectionInfo": "h2",
        #         "wasFetchedViaSpdy": True,
        #         "wasNpnNegotiated": True,
        #         "wasAlternateProtocolAvailable": False,
        #     },
        # },
        "chrome": {
            "loadTimes": {
                "navigationType": "Other",
                "npnNegotiatedProtocol": "h2",
                "connectionInfo": "h2",
                "wasFetchedViaSpdy": True,
                "wasNpnNegotiated": True,
                "wasAlternateProtocolAvailable": False,
            },
        },
    }


def inject_cookies(html, cookies):
    if not cookies:
        return html
    setters = "\n".join(
        f"document.cookie = {json.dumps(f'{k}={v}; path=/; secure; SameSite=None')};"
        for k, v in cookies.items()
    )
    snippet = f"<script>{setters}</script>"
    return re.sub(r"(<body\b[^>]*>)", r"\1" + snippet, html, count=1, flags=re.I)


# iv8 0.1.4 把 document.readyState 钉死为 "complete"(环境层改不动)。页面 <head> 脚本在 body 尚未
# 解析时,若按 `if(body){} else if(readyState==='loading'){defer} else {body.classList...}` 分支,
# 会掉进 else 访问 null.body 崩溃(very 挑战/拦截页都有这段加 hostname-class 的脚本)。
# 注入 shim:body 未出现时 readyState 返回 'loading'(真实浏览器此刻的值),脚本改走 DOMContentLoaded
# 延迟分支;body 出现后仍返回 'complete',不影响 Akamai 的后置 readyState 检查。
READYSTATE_SHIM = (
    "<script>(function(){try{Object.defineProperty(document,'readyState',"
    "{configurable:true,get:function(){return document.body?'complete':'loading';}});}catch(e){}})();</script>"
)


def inject_readystate_shim(html):
    """把 shim 插到尽量靠前:<head> 后 → <html> 后 → 文档最前(必须先于页面自身脚本运行)。"""
    for pat in (r"(<head\b[^>]*>)", r"(<html\b[^>]*>)"):
        new, n = re.subn(pat, r"\1" + READYSTATE_SHIM, html, count=1, flags=re.I)
        if n:
            return new
    return READYSTATE_SHIM + html


# page.load 里脚本是异步执行的,内部报错不会冒泡成 Python 异常 → 在 JS 侧全局捕获。
# (真实 Error 会被 iv8 映射成 Python 内建异常且不带栈;iv8.JSError 只在 throw 非 Error 时出现且无栈,
#  故不能用 except iv8.JSError.frames,只能靠这里捕获 e.stack 再交给 JSError.parse_stack。)
ERROR_CAPTURE_JS = r"""
window.__iv8_errors__ = [];
window.addEventListener('error', function(ev){
  var e = ev && ev.error;
  window.__iv8_errors__.push({
    message: (e && e.name ? e.name + ': ' + e.message : (ev && ev.message)),
    stack: (e && e.stack) ? e.stack : ''
  });
});
window.addEventListener('unhandledrejection', function(ev){
  var r = ev && ev.reason;
  window.__iv8_errors__.push({
    message: 'UnhandledRejection: ' + String(r && r.message || r),
    stack: (r && r.stack) ? r.stack : ''
  });
});
"""


def dump_js_errors(ctx, label=""):
    """读取 JS 侧捕获的错误,用 iv8.JSError.parse_stack 打印栈帧。"""
    raw = ctx.eval("JSON.stringify(window.__iv8_errors__ || [])", to_py=True)
    errors = json.loads(raw) if isinstance(raw, str) else (raw or [])
    if not errors:
        return
    print(f"[JS-ERRORS{(' ' + label) if label else ''}] 捕获 {len(errors)} 条:")
    for i, e in enumerate(errors):
        print(f"  ({i}) {e.get('message')}")
        for func, file, row, col in iv8.JSError.parse_stack(e.get("stack") or ""):
            print(f"        at {func or '<anonymous>'} ({file}:{row}:{col})")


def run_iv8(html, resources, cookies, mocked_resources=None):
    html = inject_readystate_shim(html)  # 必须在页面自身脚本前生效,先注入
    html = inject_cookies(html, cookies)
    with iv8.JSContext(
            environment=chrome_environment(cookies),
            config={"time": {"mode": "system"}, "features": {"profile": "chrome124_win"}},
            time_mode="system",
    ) as ctx:
        ctx.eval(ERROR_CAPTURE_JS)  # 必须在 page.load 之前装
        for url, body in (mocked_resources or {}).items():
            ctx.add_resource(url, body, 200, {"content-type": "application/json"})
        ctx.expose({"baseURL": PAGE_URL, "html": html, "resources": resources}, "s1")
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)")
        for ms in [100, 500, 1000, 3000, 5000, 10000, 15000]:
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})")
        dump_js_errors(ctx)
        return json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))


# 只匹配 Akamai sensor 脚本:相对路径、无 .js/.mjs/资源扩展名的混淆路径。
# very 的 app 模块(/sa/global-assets-fe/*.js 等)是异步/worker 加载,sensor 流程不需要,跳过以免一直下载。
_ASSET_EXT_RE = re.compile(r"\.(?:js|mjs|css|json|woff2?|ttf|png|jpe?g|svg|gif|ico|map)$", re.I)


def is_akamai_sensor_src(src):
    if src.startswith("http") or src.startswith("//"):
        return False  # 只要同源相对路径
    path = src.split("?", 1)[0].rstrip("/")
    if _ASSET_EXT_RE.search(path):
        return False  # 带 .js 等扩展名的都是 app 资源,不是 sensor
    return path.count("/") >= 1 and len(path) >= 12  # 混淆路径有一定长度


def fetch_scripts(session, html):
    resources = {}
    all_srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)
    sensor_srcs = [s for s in all_srcs if is_akamai_sensor_src(s)]
    skipped = [s for s in all_srcs if s not in sensor_srcs]
    print(f"fetch_scripts: 命中 sensor {len(sensor_srcs)} 个 / 跳过 {len(skipped)} 个 app 脚本")
    for s in skipped:
        print("  skip", s.split("?")[0][:80])
    for src in sensor_srcs:
        url = urljoin(PAGE_URL, src.replace("&amp;", "&"))
        response = session.get(url, headers=SCRIPT_HEADERS, timeout=45)
        print("  sensor", response.status_code, len(response.text), url.split("?")[0])
        if response.status_code == 200:
            resources[url] = response.text
            resources[src] = response.text
            resources[src.replace("&amp;", "&")] = response.text
    return resources


def _abck_state(session):
    abck = session.cookies.get_dict().get("_abck", "")
    return "~0~" if "~0~" in abck else ("~-1~" if "~-1~" in abck else "?")


def replay_entries(session, entries):
    for entry in entries:
        method = entry.get("method")
        url = entry.get("url", "")
        body = entry.get("body", "")
        if not url.startswith(BASE_URL):
            continue
        kind = classify_request(method, url, body)
        if kind == "sensor":
            # very 关键:v3 sensor_data POST(混淆动态路径),text/plain 回传
            response = session.post(url, headers=XHR_HEADERS, data=body, timeout=45)
            print("replay SENSOR", response.status_code, len(response.text), url[len(BASE_URL):][:60],
                  "| body", len(body), "| _abck", _abck_state(session))
        elif kind == "akam-pixel":
            response = session.post(url, headers=AKAM_PIXEL_HEADERS, data=body, timeout=45)
            print("replay AKAM-PIXEL", response.status_code, len(response.text), url.split("?")[0])
        elif kind == "bm-get-params":
            response = session.get(
                url,
                headers={k: v for k, v in XHR_HEADERS.items() if k != "content-type"},
                timeout=45,
            )
            print("replay GET", response.status_code, len(response.text), response.text[:100])
        elif kind == "post":
            response = session.post(url, headers=XHR_HEADERS, data=body, timeout=45)
            print("replay POST", response.status_code, len(response.text), url.split("?")[0])


def main():
    session = requests.Session(impersonate="chrome124")
    page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
    print("initial", page.status_code, len(page.text), sorted(session.cookies.get_dict()))
    resources = fetch_scripts(session, page.text)

    first_entries = run_iv8(page.text, resources, session.cookies.get_dict())
    print("first netlog", [(e.get("method"), e.get("url", "")[:90], len(e.get("body", ""))) for e in first_entries])

    mocked = {}
    for entry in first_entries:
        url = entry.get("url", "")
        if entry.get("method") == "GET" and "/_bm/get_params" in url:
            response = session.get(
                url,
                headers={k: v for k, v in XHR_HEADERS.items() if k != "content-type"},
                timeout=45,
            )
            mocked[url] = response.text
            print("mock get_params", response.status_code, response.text[:120])

    second_entries = run_iv8(page.text, resources, session.cookies.get_dict(), mocked)
    print("second netlog", [(e.get("method"), e.get("url", "")[:90], len(e.get("body", ""))) for e in second_entries])
    sensor_hits = [e for e in second_entries
                   if e.get("url", "").startswith(BASE_URL)
                   and classify_request(e.get("method"), e.get("url", ""), e.get("body", "")) == "sensor"]
    if sensor_hits:
        print(f"[SENSOR] netLog 捕获到 {len(sensor_hits)} 个 v3 sensor_data POST:",
              [e["url"][len(BASE_URL):][:60] for e in sensor_hits])
    else:
        print("[SENSOR] ⚠️ netLog 未捕获到 sensor_data POST —— iv8 未生成关键请求,无可回传"
              "(需排查 sensor 脚本是否进 resources 并被执行)")
    replay_entries(session, second_entries)
    print("cookies after replay", sorted(session.cookies.get_dict()))

    for attempt in range(1, 6):
        final_page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
        title_match = re.search(r"<title>(.*?)</title>", final_page.text, re.I | re.S)
        title = title_match.group(1).strip() if title_match else ""
        print("final", attempt, final_page.status_code, len(final_page.text), title)
        print(re.sub(r"\s+", " ", final_page.text[:220]))
        if len(final_page.text) > 100000:
            with open("very_water_search.html", "w", encoding="utf-8") as f:
                f.write(final_page.text)
            print("SUCCESS_REAL_SEARCH_PAGE")
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
