import json
import re
import time
from urllib.parse import urljoin

import iv8
from curl_cffi import requests


PAGE_URL = "https://www.very.co.uk/search/water.end"
BASE_URL = "https://www.very.co.uk"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

DOCUMENT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "max-age=0",
    "priority": "u=0, i",
    "sec-ch-ua": '"Google Chrome";v="146", "Chromium";v="146", "Not_A Brand";v="99"',
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


def chrome_environment(cookies):
    return {
        "location": {
            "protocol": "https:",
            "hostname": "www.very.co.uk",
            "host": "www.very.co.uk",
            "port": "",
            "pathname": "/search/water.end",
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
        "chrome": {
            "app": {
                "isInstalled": False,
                "InstallState": {
                    "DISABLED": "disabled",
                    "INSTALLED": "installed",
                    "NOT_INSTALLED": "not_installed",
                },
                "RunningState": {
                    "CANNOT_RUN": "cannot_run",
                    "READY_TO_RUN": "ready_to_run",
                    "RUNNING": "running",
                },
            },
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


def run_iv8(html, resources, cookies, mocked_resources=None):
    html = inject_cookies(html, cookies)
    with iv8.JSContext(
        environment=chrome_environment(cookies),
        config={"time": {"mode": "system"}, "features": {"profile": "chrome124_win"}},
        time_mode="system",
    ) as ctx:
        for url, body in (mocked_resources or {}).items():
            ctx.add_resource(url, body, 200, {"content-type": "application/json"})
        ctx.expose({"baseURL": PAGE_URL, "html": html, "resources": resources}, "s1")
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)")
        print("chrome:", ctx.eval("JSON.stringify(window.chrome)", to_py=True))
        for ms in [100, 500, 1000, 3000, 5000, 10000, 15000]:
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})")
        return json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))


def fetch_scripts(session, html):
    resources = {}
    scripts = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)
    for src in scripts:
        url = urljoin(PAGE_URL, src.replace("&amp;", "&"))
        response = session.get(url, headers=SCRIPT_HEADERS, timeout=45)
        print("script", response.status_code, len(response.text), url.split("?")[0])
        if response.status_code == 200:
            resources[url] = response.text
            resources[src] = response.text
            resources[src.replace("&amp;", "&")] = response.text
    return resources


def replay_entries(session, entries):
    for entry in entries:
        method = entry.get("method")
        url = entry.get("url", "")
        body = entry.get("body", "")
        if not url.startswith(BASE_URL):
            continue
        if method == "GET" and "/_bm/get_params" in url:
            response = session.get(
                url,
                headers={k: v for k, v in XHR_HEADERS.items() if k != "content-type"},
                timeout=45,
            )
            print("replay GET", response.status_code, len(response.text), response.text[:100])
        elif method == "POST" and body:
            response = session.post(url, headers=XHR_HEADERS, data=body, timeout=45)
            print("replay POST", response.status_code, len(response.text), url.split("?")[0])


def main():
    session = requests.Session(impersonate="chrome146")
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
