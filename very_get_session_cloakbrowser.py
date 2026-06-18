# -*- coding: utf-8 -*-
"""
用 CloakBrowser (真实 Chromium 146) 加载 very.co.uk，
等待 Akamai sensor 跑完，导出 cookie 并检查 _abck 是否校验通过。

Akamai 的 _abck 格式: <hash>~<status>~...
  status == -1  →  未校验（拦截页）
  status ==  0  →  已校验（绕过成功）

必须用装了 cloakbrowser 的 py310 环境运行:
  C:/Users/YanchuangJin/miniforge3/envs/py310/python.exe very_get_session_cloakbrowser.py
"""
import asyncio
import json
import os

os.environ.setdefault("DEBUG", "cloakbrowser")

from cloakbrowser import launch_async

PAGE_URL = "https://www.very.co.uk/"
# 如需 UK 出口可填代理串，例如 "http://user:pass@host:port"；None = 直连
PROXY = None
HEADLESS = False
COOKIE_OUT = "very_cloakbrowser_cookies.json"


def abck_status(value: str) -> str:
    parts = value.split("~")
    return parts[1] if len(parts) > 1 else "?"


async def main():
    browser = None
    try:
        browser = await launch_async(
            proxy=PROXY,
            headless=HEADLESS,
            humanize=True,
            geoip=bool(PROXY),
        )
        context = await browser.new_context()
        page = await context.new_page()

        print("UA:", await page.evaluate("navigator.userAgent"))
        print("正在访问:", PAGE_URL)
        await page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=120000)

        # 轮询 _abck，最多等约 30 秒，看它能否从 -1 翻到 0
        validated = False
        for i in range(1, 16):
            await asyncio.sleep(2)
            cookies_list = await page.context.cookies()
            jar = {c["name"]: c["value"] for c in cookies_list}
            abck = jar.get("_abck", "")
            status = abck_status(abck) if abck else "(无)"
            print(f"[{i:02d}] _abck status={status}  cookies={sorted(jar)}")
            if status == "0":
                validated = True
                break

        cookies_list = await page.context.cookies()
        jar = {c["name"]: c["value"] for c in cookies_list}
        abck = jar.get("_abck", "")

        print("\n==== 结果 ====")
        print("page title:", await page.title())
        print("_abck =", abck)
        print("_abck status =", abck_status(abck) if abck else "(无 _abck)")
        print("校验通过 (status==0):", validated)
        print("全部 cookie 名:", sorted(jar))

        with open(COOKIE_OUT, "w", encoding="utf-8") as f:
            json.dump(
                {"cookies": jar, "cookies_full": cookies_list, "validated": validated},
                f,
                ensure_ascii=False,
                indent=2,
            )
        print("cookie 已写入:", COOKIE_OUT)

    except Exception as e:
        print("异常:", repr(e))
    finally:
        if browser:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
