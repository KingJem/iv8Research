"""BJs.com 主站 Akamai cookie 获取/验证。
bjs 主站是 Akamai v3 行为挑战(sec-if-cpt-container,同 very/CVS),好指纹也被挑战,
必须跑 sensor JS 回传刷 _abck。流程: httpcloak GET -> 提取动态 sensor 脚本 -> iv8 跑 + 模拟输入
-> netLog 抓 sensor_data POST -> 回传 -> 再 GET 验证。复用 cvs.py 的 JS 补丁与输入模拟。"""
import json, os, re, time
from html import unescape
from urllib.parse import urljoin
import httpcloak
import cvs as C
import iv8

HOME = "https://www.bjs.com/"
PROXY = "http://127.0.0.1:7890"
UA = C.UA
HEADERS = dict(C.HEADERS)
AK = ("_abck","bm_s","bm_so","bm_ss","bm_sz","bm_sv","bm_sc","bm_mi","ak_bmsc","AKA_A2")
DOMAIN = ".bjs.com"

def jar(s): return {c.name: c.value for c in s.cookies}
def ak_only(d): return {k: d[k] for k in AK if k in d}
def is_challenge(t):
    return ('sec-if-cpt-container' in t or 'scf-akamai' in t
            or ('_abck' in t and len(t) < 50000) or 'Access Denied' in t or len(t) < 2000)

def extract_scripts(html):
    """bjs 挑战页: 动态深路径脚本 /XXXX/.../...(?v=...&t=...)。返回 {url:url}"""
    out = {}
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        if src.startswith("http") or src.startswith("//"):
            continue
        if src.count("/") < 2 or len(src) < 15:
            continue
        out[urljoin(HOME, src)] = urljoin(HOME, src)
    return out

def run_bjs_bypass(session, html, page_url, resources):
    env = C.create_environment(page_url)
    with iv8.JSContext(environment=env,
                       config={"time": {"mode": "logical"}, "timezone": "America/New_York"}) as ctx:
        ctx.expose({"baseURL": page_url, "html": unescape(html), "resources": resources}, "s1")
        # 注入初始 cookie(域改 bjs)
        ak = {c.name: c.value for c in session.cookies if c.name in
              ("_abck","ak_bmsc","bm_sz","bm_sv","bm_mi","bm_s","bm_sc","bm_so","bm_ss","AKA_A2")}
        if ak:
            js = " ".join(f"document.cookie = {json.dumps(k)} + '=' + {json.dumps(v)} + '; path=/; domain={DOMAIN}';"
                          for k, v in ak.items())
            ctx.eval("(function(){ try { " + js + " } catch(e) {} })();")
            print(f"    [iv8] 注入初始 cookies: {list(ak.keys())}")
        ctx.eval(C.JS_REINFORCE)
        ctx.eval("window.__iv8__.page.load(window.__iv8__.data.s1);")
        ctx.eval(C.JS_REINFORCE)
        for tick in range(50):
            C.simulate_user_input(ctx)
            ctx.eval("window.__iv8__.eventLoop.advance(200);")
            if tick % 10 == 9:
                ents = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
                if any("sensor_data" in str(e.get("body","")) for e in ents if e.get("method")=="POST"):
                    print(f"    [iv8] tick={tick} 发现 sensor_data POST"); break
        ctx.eval("window.__iv8__.eventLoop.advance(3000);")
        ents = ctx.eval("window.__iv8__.netLog.entries", to_py=True) or []
        print(f"    [iv8] netLog 捕获 {len(ents)} 个请求")
        with open("bjs_netlog_debug.json","w",encoding="utf-8") as f:
            json.dump(ents, f, ensure_ascii=False, indent=2)
        # 找 POST: sensor_data / akam pixel / 同路径回传
        posts = [e for e in ents if e.get("method")=="POST"]
        for e in posts:
            print(f"      POST {str(e.get('url',''))[:70]}  body_len={len(str(e.get('body','')))}")
        for e in posts:
            b = str(e.get("body","") or "")
            if "sensor_data" in b: return e["url"], b
        for e in posts:
            u = str(e.get("url","") or ""); b = str(e.get("body","") or "")
            if "/akam/" in u or "pixel" in u or len(b) > 300:
                return u, b
        return None, None

def main():
    print("="*60); print("BJs.com 主站 Akamai cookie 获取"); print("="*60)
    s = httpcloak.Session(preset="chrome-146-windows", proxy=PROXY)
    print(f"\n[Step 1] GET {HOME}")
    r1 = s.get(HOME, headers=HEADERS, timeout=20)
    chal = is_challenge(r1.text)
    print(f"    status={r1.status_code} len={len(r1.text)} challenge={chal} cookies={list(ak_only(jar(s)).keys())}")

    if chal:
        with open("bjs_challenge.html","w",encoding="utf-8") as f: f.write(r1.text)
        print("\n[Step 2] 提取动态 sensor 脚本...")
        scripts = extract_scripts(r1.text)
        for u in scripts: print(f"      {u[:90]}")
        if not scripts:
            print("    [错误] 无脚本"); return
        print("\n[Step 3] 下载脚本...")
        sh = {**HEADERS, "accept":"*/*","sec-fetch-dest":"script","sec-fetch-mode":"no-cors",
              "sec-fetch-site":"same-origin","referer":HOME}
        resources = {}
        for u in scripts:
            try:
                rj = s.get(u, headers=sh, timeout=20); resources[u] = rj.text
                print(f"      {rj.status_code} {len(rj.text)}B  {u[:70]}")
            except Exception as e: print("      下载失败", e)
        print("\n[Step 4] iv8 跑 Akamai JS...")
        t0=time.time()
        surl, sbody = run_bjs_bypass(s, r1.text, HOME, resources)
        print(f"    iv8 耗时 {time.time()-t0:.2f}s")
        if not surl:
            print("    [错误] 未捕获 sensor POST,查看 bjs_netlog_debug.json"); 
        else:
            print(f"\n[Step 5] POST sensor -> {surl[:80]}  len={len(sbody)}")
            ph = {"accept":"*/*","content-type":"text/plain;charset=UTF-8","user-agent":UA,
                  "sec-ch-ua":HEADERS["sec-ch-ua"],"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"Windows"',
                  "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
                  "referer":HOME,"origin":"https://www.bjs.com","accept-language":"en-US,en;q=0.9"}
            rs = s.post(surl, data=sbody.encode() if isinstance(sbody,str) else sbody, headers=ph, timeout=20)
            print(f"    POST status={rs.status_code}")
            abck = jar(s).get("_abck","")
            print(f"    _abck={'~0~ VALID' if '~0~' in abck else ('~-1~ 未通过' if '~-1~' in abck else '?')}  {abck[:60]}")

    print("\n[验证] 再 GET 主页...")
    r2 = s.get(HOME, headers={**HEADERS,"referer":HOME}, timeout=20)
    real = (r2.status_code==200) and not is_challenge(r2.text)
    print(f"    status={r2.status_code} len={len(r2.text)} 真实内容={real}")
    title = re.search(r'<title[^>]*>([^<]+)</title>', r2.text)
    print(f"    标题: {title.group(1).strip() if title else '(无)'}")
    with open("bjs_cookies.json","w",encoding="utf-8") as f:
        json.dump({"akamai":ak_only(jar(s)),"all":jar(s),"ua":UA}, f, ensure_ascii=False, indent=2)
    print("\n[结论]", "BJs Akamai 通过,出真实内容 ✅" if real else "仍被挑战,iv8 sensor 未能让 _abck 生效 ❌")

if __name__ == "__main__":
    main()
