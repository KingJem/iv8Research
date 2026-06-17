import json
import re
import time

import iv8
from curl_cffi import requests

from retry_very_iv8_chrome import (
    BASE_URL,
    DOCUMENT_HEADERS,
    PAGE_URL,
    XHR_HEADERS,
    chrome_environment,
    fetch_scripts,
    inject_cookies,
)


def replay_and_inject(ctx, session, entry):
    method = entry.get("method")
    url = entry.get("url", "")
    body = entry.get("body", "")
    if not url.startswith(BASE_URL):
        return False
    if method == "GET" and url == PAGE_URL:
        return False

    headers = {k: v for k, v in XHR_HEADERS.items() if k != "content-type"}
    if method == "GET":
        response = session.get(url, headers=headers, timeout=45)
    elif method == "POST" and body:
        response = session.post(url, headers=XHR_HEADERS, data=body, timeout=45)
    else:
        return False

    content_type = response.headers.get("content-type", "text/plain")
    ctx.add_resource(url, response.text, response.status_code, {"content-type": content_type})
    print(
        "live replay",
        method,
        response.status_code,
        len(response.text),
        url.split("?")[0],
    )
    if response.text:
        print("  response", re.sub(r"\s+", " ", response.text[:180]))
    return True


def main():
    session = requests.Session(impersonate="chrome146")
    page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
    print("initial", page.status_code, len(page.text), sorted(session.cookies.get_dict()))
    resources = fetch_scripts(session, page.text)
    cookies = session.cookies.get_dict()
    html = inject_cookies(page.text, cookies)

    with iv8.JSContext(
        environment=chrome_environment(cookies),
        config={"time": {"mode": "system"}, "features": {"profile": "chrome124_win"}},
        time_mode="system",
    ) as ctx:
        ctx.expose(
            {
                "baseURL": PAGE_URL,
                "html": html,
                "resources": resources,
                "headers": dict(page.headers),
            },
            "s1",
        )
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)")
        print("chrome", ctx.eval("JSON.stringify(window.chrome)", to_py=True))

        processed = set()
        for step, ms in enumerate([20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 8000, 12000], 1):
            print("advance step", step, ms)
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})")
            entries = json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))
            for index, entry in enumerate(entries):
                key = (index, entry.get("method"), entry.get("url"), entry.get("body"))
                if key in processed:
                    continue
                processed.add(key)
                replay_and_inject(ctx, session, entry)

        entries = json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))
        print("netlog", [(e.get("method"), e.get("url", "")[:90], len(e.get("body", ""))) for e in entries])
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
