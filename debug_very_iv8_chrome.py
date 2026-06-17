from retry_very_iv8_chrome import (
    DOCUMENT_HEADERS,
    PAGE_URL,
    SCRIPT_HEADERS,
    chrome_environment,
    fetch_scripts,
    inject_cookies,
)

import json

import iv8
from curl_cffi import requests


def main():
    session = requests.Session(impersonate="chrome146")
    page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
    print("initial", page.status_code, len(page.text), sorted(session.cookies.get_dict()))
    resources = fetch_scripts(session, page.text)
    cookies = session.cookies.get_dict()
    html = inject_cookies(page.text, cookies)

    with iv8.JSContext(
        mode="debug",
        environment=chrome_environment(cookies),
        config={
            "time": {"mode": "system"},
            "features": {"profile": "chrome124_win"},
        },
        ignore_apis=[],
        time_mode="system",
    ) as ctx:
        print("monitor mode:", ctx.get_browser_api_monitor_mode())
        ctx.expose({"baseURL": PAGE_URL, "html": html, "resources": resources}, "s1")
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)", devtools=False)
        print("chrome:", ctx.eval("JSON.stringify(window.chrome)", to_py=True, devtools=False))
        for ms in [100, 500, 1000, 3000, 5000, 10000]:
            print("advance", ms)
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})", devtools=False)
        entries = json.loads(
            ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True, devtools=False)
        )
        print("netlog", [(e.get("method"), e.get("url", "")[:100], len(e.get("body", ""))) for e in entries])


if __name__ == "__main__":
    main()
