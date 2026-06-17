import json

import iv8
from curl_cffi import requests

from retry_very_iv8_chrome import (
    DOCUMENT_HEADERS,
    PAGE_URL,
    chrome_environment,
    fetch_scripts,
    inject_cookies,
)


WATCH_APIS = [
    "window.chrome",
    "chrome.loadTimes",
    "document.cookie",
    "XMLHttpRequest.prototype.open",
    "XMLHttpRequest.prototype.send",
    "location.reload",
    "navigator.userAgent",
    "navigator.webdriver",
]


def main():
    session = requests.Session(impersonate="chrome146")
    page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
    print("initial", page.status_code, len(page.text), sorted(session.cookies.get_dict()))
    resources = fetch_scripts(session, page.text)
    cookies = session.cookies.get_dict()
    html = inject_cookies(page.text, cookies)

    print("Open Chrome DevTools and connect to the iv8 inspector on port 9229.")
    print("Watch APIs:", ", ".join(WATCH_APIS))

    with iv8.JSContext(
        mode="debug",
        environment=chrome_environment(cookies),
        config={"time": {"mode": "system"}, "features": {"profile": "chrome124_win"}},
        ignore_apis=[],
        time_mode="system",
    ).with_devtools(port=9229, watch_apis=WATCH_APIS, enable_console=False) as ctx:
        ctx.expose(
            {
                "baseURL": PAGE_URL,
                "html": html,
                "resources": resources,
                "headers": dict(page.headers),
            },
            "s1",
        )
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)", name="very_page_load.js")
        for ms in [20, 50, 100, 200, 500, 1000, 2000, 5000]:
            print("advance", ms)
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})", name=f"advance_{ms}.js")
        entries = json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))
        print("netlog", [(e.get("method"), e.get("url", "")[:90], len(e.get("body", ""))) for e in entries])


if __name__ == "__main__":
    main()
