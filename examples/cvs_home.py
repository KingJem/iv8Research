"""CVS 主页 akamai cookie 验证 —— 复用 cvs.py 的 iv8 Akamai 流程,目标改为主页。
流程: httpcloak GET 主页 → 若 challenge 则 iv8 跑 sensor_data → POST 到 /m9c.../ 同款 URL → 验证 _abck → 再 GET 主页确认真实内容。"""
import json, os, re, time
import httpcloak
import cvs as C   # 复用 cvs.py 的 create_environment / extract_akamai_scripts / run_akamai_bypass 等

HOME = "https://www.cvs.com/"
PROXY = C.PROXY
HEADERS = C.HEADERS

def jar(s): return {c.name: c.value for c in s.cookies}
def akamai_only(d):
    return {k: d[k] for k in ("_abck","bm_s","bm_so","bm_ss","bm_sz","bm_sv","ak_bmsc","AKA_A2") if k in d}

def main():
    print("="*60); print("CVS 主页 akamai cookie 验证"); print("="*60)
    s = httpcloak.Session(preset="chrome-146-windows", proxy=PROXY)

    print(f"\n[Step 1] GET {HOME}")
    r1 = s.get(HOME, headers=HEADERS, timeout=20)
    d1 = jar(s)
    print(f"    status={r1.status_code} protocol={r1.protocol} len={len(r1.text)}")
    print(f"    challenge? {C.is_akamai_challenge(r1.text)}  cookies={list(akamai_only(d1).keys())}")

    if not C.is_akamai_challenge(r1.text) and r1.status_code == 200:
        print("    [成功] 主页无挑战,httpcloak 指纹直接过 Akamai,cookie 已签发")
    else:
        # 有挑战 → 走 iv8 sensor_data 流程(和你抓包同款 POST URL)
        print("    [信息] 检测到挑战,提取 Akamai 脚本并用 iv8 生成 sensor_data ...")
        scripts = C.extract_akamai_scripts(r1.text, HOME)
        print(f"    脚本 {len(scripts)} 个: {[u[:70] for u in scripts.values()][:4]}")
        sh = {**HEADERS, "accept":"*/*", "sec-fetch-dest":"script", "sec-fetch-mode":"no-cors",
              "sec-fetch-site":"same-origin", "referer":HOME}
        resources = {}
        for u in scripts.values():
            if u in resources: continue
            try:
                rj = s.get(u, headers=sh, timeout=20); resources[u] = rj.text
                print(f"    js {rj.status_code} {len(rj.text)}B  {u[:70]}")
            except Exception as e: print("    js fail", e)
        sensor_url, sensor_body = C.run_akamai_bypass(s, r1.text, HOME, resources)
        if sensor_url:
            print(f"    sensor POST URL: {sensor_url}")
            print(f"    sensor body len: {len(sensor_body)}")
            ph = {"accept":"*/*","content-type":"text/plain;charset=UTF-8","user-agent":C.UA,
                  "sec-ch-ua":HEADERS["sec-ch-ua"],"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"Windows"',
                  "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
                  "referer":HOME,"origin":"https://www.cvs.com","accept-language":"en-US,en;q=0.9"}
            rs = s.post(sensor_url, data=sensor_body.encode() if isinstance(sensor_body,str) else sensor_body, headers=ph, timeout=20)
            print(f"    POST status={rs.status_code}")
        else:
            print("    [错误] 未捕获 sensor_data")

    # 验证: 取 akamai cookie,用全新 session 回放主页,看是否出真实内容
    ak = akamai_only(jar(s))
    print(f"\n[验证] 用 akamai-only cookie 全新 session 回放主页: {list(ak.keys())}")
    abck = ak.get("_abck","")
    print(f"    _abck = {abck[:60]}...  状态={'~0~ VALID' if '~0~' in abck else ('~-1~ (CVS 正常)' if '~-1~' in abck else '?')}")
    s2 = httpcloak.Session(preset="chrome-146-windows", proxy=PROXY)
    ck = "; ".join(f"{k}={v}" for k,v in ak.items())
    r2 = s2.get(HOME, headers={**HEADERS,"cookie":ck}, timeout=20)
    real = ("CVS" in r2.text) and not C.is_akamai_challenge(r2.text)
    print(f"    回放 status={r2.status_code} len={len(r2.text)} 真实内容={real}")

    with open("cvs_home_cookies.json","w",encoding="utf-8") as f:
        json.dump({"akamai":ak,"all":jar(s),"ua":C.UA}, f, ensure_ascii=False, indent=2)
    print("    saved -> cvs_home_cookies.json")
    print("\n[结论]", "akamai cookie 有效,主页出真实内容" if real else "未出真实内容,需排查")

if __name__ == "__main__":
    main()
