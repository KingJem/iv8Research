# -*- coding: utf-8 -*-
"""
按 docs/iv8_补环境教程.md 的技巧再战 Akamai：
  1. §9.5  在 Akamai 脚本之前 head 注入完整 window.chrome（含 runtime/csi/loadTimes）
  2. §5.5  用 __iv8__.input.dispatchMouseEvent 派发【可信】鼠标轨迹，喂行为传感器
  3. §4.6  netLog -> 真实请求 -> add_resource -> eventLoop 推进 的标准回放流程

判定成功的唯一标准：用回放后的 cookie 取到 >100KB 的真实搜索页（不是 status==0）。
"""
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

# §9.5：完整 window.chrome 桩，必须在 Akamai 脚本之前执行
CHROME_PATCH = """
<script>(function(){
  var lt = {
    requestTime: Date.now()/1000, startLoadTime: Date.now()/1000,
    commitLoadTime: Date.now()/1000, finishDocumentLoadTime: Date.now()/1000,
    finishLoadTime: Date.now()/1000, firstPaintTime: Date.now()/1000,
    firstPaintAfterLoadTime: 0, navigationType: "Other",
    wasFetchedViaSpdy: true, wasNpnNegotiated: true,
    npnNegotiatedProtocol: "h2", wasAlternateProtocolAvailable: false,
    connectionInfo: "h2"
  };
  window.chrome = {
    app: {
      isInstalled: false,
      InstallState: {DISABLED:"disabled", INSTALLED:"installed", NOT_INSTALLED:"not_installed"},
      RunningState: {CANNOT_RUN:"cannot_run", READY_TO_RUN:"ready_to_run", RUNNING:"running"},
      getDetails: function(){ return null; },
      getIsInstalled: function(){ return false; },
      runningState: function(){ return "cannot_run"; }
    },
    runtime: {
      OnInstalledReason: {INSTALL:"install", UPDATE:"update", CHROME_UPDATE:"chrome_update", SHARED_MODULE_UPDATE:"shared_module_update"},
      OnRestartRequiredReason: {APP_UPDATE:"app_update", OS_UPDATE:"os_update", PERIODIC:"periodic"},
      PlatformArch: {ARM:"arm", ARM64:"arm64", MIPS:"mips", MIPS64:"mips64", X86_32:"x86-32", X86_64:"x86-64"},
      PlatformNaclArch: {ARM:"arm", MIPS:"mips", MIPS64:"mips64", X86_32:"x86-32", X86_64:"x86-64"},
      PlatformOs: {ANDROID:"android", CROS:"cros", LINUX:"linux", MAC:"mac", OPENBSD:"openbsd", WIN:"win"},
      RequestUpdateCheckStatus: {NO_UPDATE:"no_update", THROTTLED:"throttled", UPDATE_AVAILABLE:"update_available"},
      connect: function(){ return {}; },
      sendMessage: function(){ },
      id: undefined
    },
    csi: function(){ return {onloadT: Date.now(), startE: Date.now()-100, pageT: 0, tran: 15}; },
    loadTimes: function(){ return lt; }
  };
})();</script>
"""


def inject_head_chrome(html):
    """把 chrome 补丁作为 <head> 里的第一个脚本插入，确保先于 Akamai 脚本执行。"""
    if re.search(r"<head\b[^>]*>", html, re.I):
        return re.sub(r"(<head\b[^>]*>)", r"\1" + CHROME_PATCH, html, count=1, flags=re.I)
    if re.search(r"<html\b[^>]*>", html, re.I):
        return re.sub(r"(<html\b[^>]*>)", r"\1<head>" + CHROME_PATCH + "</head>", html, count=1, flags=re.I)
    return CHROME_PATCH + html


def feed_mouse(ctx):
    """§5.5：派发可信鼠标 + 指针轨迹，给 Akamai 行为传感器提供熵。"""
    ctx.eval(
        """
        (function(){
          var t = document.body || document.documentElement;
          function move(x, y){
            try { window.__iv8__.input.dispatchPointerEvent({type:'pointermove', target:t, clientX:x, clientY:y, button:-1, buttons:0, pointerType:'mouse', isPrimary:true}); } catch(e){}
            try { window.__iv8__.input.dispatchMouseEvent({type:'mousemove', target:t, clientX:x, clientY:y, button:0, buttons:0}); } catch(e){}
          }
          var x=80, y=140;
          for (var i=0; i<60; i++){
            x += 7 + (i % 5);
            y += (i % 2 ? 3 : -2);
            move(x, y);
          }
          try { window.__iv8__.input.dispatchMouseEvent({type:'mousedown', target:t, clientX:x, clientY:y, button:0, buttons:1}); } catch(e){}
          try { window.__iv8__.input.dispatchMouseEvent({type:'mouseup',   target:t, clientX:x, clientY:y, button:0, buttons:0}); } catch(e){}
          try { window.__iv8__.input.dispatchMouseEvent({type:'click',     target:t, clientX:x, clientY:y, button:0, buttons:0}); } catch(e){}
        })();
        """
    )


def replay_and_inject(ctx, session, entry):
    method = entry.get("method")
    url = entry.get("url", "")
    body = entry.get("body", "")
    if not url.startswith(BASE_URL) or url == PAGE_URL:
        return False
    headers = {k: v for k, v in XHR_HEADERS.items() if k != "content-type"}
    if method == "GET":
        response = session.get(url, headers=headers, timeout=45)
    elif method == "POST" and body:
        response = session.post(url, headers=XHR_HEADERS, data=body, timeout=45)
    else:
        return False
    ct = response.headers.get("content-type", "text/plain")
    ctx.add_resource(url, response.text, response.status_code, {"content-type": ct})
    # §4.6：注入响应后排空已到期任务，让 JS 的 XHR 回调命中
    ctx.eval("window.__iv8__.eventLoop.drain()")
    print("live replay", method, response.status_code, len(response.text), url.split("?")[0])
    return True


def abck_status(session):
    v = session.cookies.get_dict().get("_abck", "")
    p = v.split("~")
    return p[1] if len(p) > 1 else "(none)"


def main():
    session = requests.Session(impersonate="chrome146")
    page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
    print("initial", page.status_code, len(page.text), "_abck", abck_status(session))



    resources = fetch_scripts(session, page.text)
    cookies = session.cookies.get_dict()
    html = inject_head_chrome(inject_cookies(page.text, cookies))

    with iv8.JSContext(
            environment=chrome_environment(cookies),
            config={"time": {"mode": "system"}, "features": {"profile": "chrome124_win"}},
            time_mode="system", mode='debug'
    ).with_devtools(
        port=9229,

        # watch_apis: 访问这些 API 时自动触发断点，无需在 JS 里写 vdebugger
        # 在 DevTools 调用栈面板可看到是哪行代码触发了本次访问
        watch_apis=[
            # "navigator.userAgent",
            # "navigator.webdriver",
            # "document.cookie",
            "window.chrome",
        ],
    ) as ctx:
        ctx.expose(
            {"baseURL": PAGE_URL, "html": html, "resources": resources, "headers": dict(page.headers)},
            "s1",
        )
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1)")
        print("chrome.runtime typeof:", ctx.eval("typeof window.chrome.runtime", to_py=True))

        processed = set()
        for step, ms in enumerate([20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 8000, 12000], 1):
            feed_mouse(ctx)  # 每步都喂一点行为数据
            ctx.eval(f"window.__iv8__.eventLoop.advance({ms})")
            entries = json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))
            for index, entry in enumerate(entries):
                key = (index, entry.get("method"), entry.get("url"), entry.get("body"))
                if key in processed:
                    continue
                processed.add(key)
                replay_and_inject(ctx, session, entry)

        entries = json.loads(ctx.eval("JSON.stringify(window.__iv8__.netLog.entries)", to_py=True))
        print("netlog", [(e.get("method"), e.get("url", "")[:80], len(e.get("body", ""))) for e in entries])
        print("cookies after replay", sorted(session.cookies.get_dict()), "_abck", abck_status(session))

    for attempt in range(1, 6):
        final_page = session.get(PAGE_URL, headers=DOCUMENT_HEADERS, timeout=45)
        size = len(final_page.text)
        has_water = "water" in final_page.text.lower()
        has_challenge = "sec-if-cpt" in final_page.text.lower()
        print(
            f"final {attempt} {final_page.status_code} size={size} water={has_water} challenge={has_challenge} _abck={abck_status(session)}")
        if size > 100000 and not has_challenge:
            with open("very_water_search_iv8.html", "w", encoding="utf-8") as f:
                f.write(final_page.text)
            print("SUCCESS_REAL_SEARCH_PAGE")
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
