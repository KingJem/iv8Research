"""Sam's Club PerimeterX(PX)绕过 —— 独立示例(脱离 spiders_2 框架)

两段完整链路:
  1) iv8 补环境铸 PX cookies(_px3/_pxvid/pxcts/_pxde)
  2) 用 cookies 调 samsclub 搜索接口(/api/node/vivaldi/browse/v2/products/search)拿真实数据

依赖:iv8 · requests · curl_cffi · 同目录 px_init.js(PX sensor,缺失会自动下载)
本机(py310)直接跑:
    python examples/samsclub_px_example.py                 # 完整链路:铸 cookie → 调接口
    python examples/samsclub_px_example.py --keyword "milk" --club 4996
    python examples/samsclub_px_example.py --worker         # (内部子进程用,勿手动)

说明:iv8 的 V8 isolate 在子线程里跑 PX SDK 会异常(SDK 顶层 try/catch 吞错,keys=[]),
故 fetch_px_cookies() 默认 fork 一个干净子进程跑 iv8,通过 stdout 回传 cookies JSON。
PX token 与回放 IP 解耦(好 token 换任意 UA/TLS/IP 都能回放),故调接口的代理可选。

⚠️ token 质量取决于**铸造时的采集 IP 信誉**(PX 给出的评分):
  - 干净/住宅 IP(如生产服务器)铸的 token → 搜索接口 200 出值(本地/服务器已确认有效);
  - 中国开发机直连、oxylabs 数据中心段(172.121 等)铸的 token → PX 评分低 → 搜索接口 **412
    ("are-you-human")**。这是 IP 信誉问题,非脚本逻辑问题。要出值请在 PX-clean IP 上铸 token。
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time

import iv8
import requests as py_requests
from curl_cffi import requests as cc_requests

SAMS_HOME_URL = 'https://www.samsclub.com/'
PX_JS_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), 'px_init.js'))
PX_APP_ID = 'PXsLC3j22K'  # PX app id;sensor 真实路径 = /px/<PX_APP_ID>/init.js(首页提取不到时兜底)
PX_COOKIE_KEYS = ('_pxvid', '_px3', 'pxcts', '_pxde')
SEARCH_API = 'https://www.samsclub.com/api/node/vivaldi/browse/v2/products/search'

DEFAULT_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# 采集画像池:每个都是一套自洽的 Chromium 指纹(UA/平台/硬件/屏幕/webgl/impersonate 互相匹配)。
# 采 token 时随机取一个,避免所有 token 都用同一套环境被 PX 聚类判低分。
# 只保留标准 curl_cffi 0.15.3 支持的 impersonate 目标。只放 Chromium(PX_BRIDGE_JS 注入 window.chrome)。
PX_PROFILES = [
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 8, 'deviceMemory': 8,
     'screen': {'width': 1920, 'height': 1080, 'availWidth': 1920, 'availHeight': 1040, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (NVIDIA)', 'renderer': 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'chrome131'},
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 12, 'deviceMemory': 8,
     'screen': {'width': 2560, 'height': 1440, 'availWidth': 2560, 'availHeight': 1400, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (Intel)', 'renderer': 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'chrome133a'},
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 16, 'deviceMemory': 16,
     'screen': {'width': 1920, 'height': 1080, 'availWidth': 1920, 'availHeight': 1032, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (AMD)', 'renderer': 'ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'chrome136'},
    {'ua': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
     'platform': 'MacIntel', 'vendor': 'Google Inc.', 'hardwareConcurrency': 8, 'deviceMemory': 8,
     'screen': {'width': 1440, 'height': 900, 'availWidth': 1440, 'availHeight': 875, 'colorDepth': 30},
     'webgl': {'vendor': 'Google Inc. (Apple)', 'renderer': 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)'},
     'impersonate': 'chrome145_macos'},
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 8, 'deviceMemory': 16,
     'screen': {'width': 1536, 'height': 864, 'availWidth': 1536, 'availHeight': 824, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (Intel)', 'renderer': 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'edge101'},
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 24, 'deviceMemory': 16,
     'screen': {'width': 2560, 'height': 1440, 'availWidth': 2560, 'availHeight': 1392, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (NVIDIA)', 'renderer': 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'chrome124'},
    {'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
     'platform': 'Win32', 'vendor': 'Google Inc.', 'hardwareConcurrency': 8, 'deviceMemory': 16,
     'screen': {'width': 1920, 'height': 1080, 'availWidth': 1920, 'availHeight': 1032, 'colorDepth': 24},
     'webgl': {'vendor': 'Google Inc. (AMD)', 'renderer': 'ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)'},
     'impersonate': 'chrome146_windows'},
    {'ua': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
     'platform': 'MacIntel', 'vendor': 'Google Inc.', 'hardwareConcurrency': 10, 'deviceMemory': 8,
     'screen': {'width': 1512, 'height': 982, 'availWidth': 1512, 'availHeight': 944, 'colorDepth': 30},
     'webgl': {'vendor': 'Google Inc. (Apple)', 'renderer': 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)'},
     'impersonate': 'chrome144_macos'},
]

# ─────────────────────────── PX cookie 生成(iv8 补环境) ───────────────────────────

PX_BRIDGE_JS = """
document.__fakeScript = document.createElement('script');
document.__fakeScript.src = 'https://www.samsclub.com/px/PXsLC3j22K/init.js';
Object.defineProperty(document, 'scripts', {get:function(){return [document.__fakeScript];},configurable:true});
Object.defineProperty(document, 'currentScript', {get:function(){return document.__fakeScript;},configurable:true});
window.MessageChannel = __iv8__.wrapNative(function(){
    var p1={onmessage:null,close:function(){}},p2={onmessage:null,close:function(){}};
    p1.postMessage=function(d){if(p2.onmessage)setTimeout(function(){p2.onmessage({data:d});},0);};
    p2.postMessage=function(d){if(p1.onmessage)setTimeout(function(){p1.onmessage({data:d});},0);};
    return {port1:p1,port2:p2};
},'MessageChannel');
window.chrome={runtime:{},loadTimes:function(){},csi:function(){},app:{}};

window.__px_xhr_list__ = [];
var _X=XMLHttpRequest;
window.XMLHttpRequest = __iv8__.wrapNative(function(){
    var x=new _X(),o=x.open,r=x.setRequestHeader;
    var info={xhr:x,method:'GET',url:'',headers:{},body:null,state:'open'};
    x.open=function(m,u){info.method=m;info.url=u;return o.call(x,m,u);};
    x.setRequestHeader=function(n,v){info.headers[n]=v;return r.call(x,n,v);};
    x.send=function(b){info.body=b; info.state='sent'; window.__px_xhr_list__.push(info);};
    return x;
},'XMLHttpRequest');
var _F=fetch;
window.fetch=__iv8__.wrapNative(function(u,o){
    var q={method:(o&&o.method)||'GET',url:'',headers:(o&&o.headers)||{},body:(o&&o.body)||null};
    if(typeof u==='string')q.url=u;else if(u)q.url=u.url||u.href||'';
    q._isFetch=true;window.__px_xhr_list__.push(q);
    return new Promise(function(r){q._resolve=r;});
},'fetch');
"""

PX_JS_TTL_SECONDS = 3 * 24 * 3600  # 超过 3 天强制重下,避免 PX 轮换 sensor 后 token 被 412


def build_environment(profile):
    return {
        'location': {'href': SAMS_HOME_URL, 'origin': 'https://www.samsclub.com',
                     'host': 'www.samsclub.com', 'hostname': 'www.samsclub.com'},
        'navigator': {'userAgent': profile['ua'], 'platform': profile['platform'], 'language': 'en-US',
                      'hardwareConcurrency': profile['hardwareConcurrency'], 'deviceMemory': profile['deviceMemory'],
                      'maxTouchPoints': 0, 'vendor': profile['vendor']},
        'screen': {**profile['screen']},
        'webgl': {**profile['webgl']},
    }


def _download_px_init_js(log, proxies=None, ua=None, impersonate='chrome124'):
    ua = ua or DEFAULT_UA
    r = cc_requests.get(SAMS_HOME_URL, headers={'User-Agent': ua, 'Accept': 'text/html'},
                        impersonate=impersonate, timeout=30, proxies=proxies)
    html = r.text
    log(f'PX 首页 status={r.status_code} len={len(html)}')
    m = re.search(r'(/px/[A-Za-z0-9_\-]{6,}/init\.js)', html)
    if m:
        path = m.group(1)
    else:
        m2 = re.search(r'(PX[A-Za-z0-9]{8,})', html)
        app_id = m2.group(1) if m2 else PX_APP_ID
        path = f'/px/{app_id}/init.js'
        log(f'首页未命中 sensor 路径,用 app_id={app_id} 兜底 → {path}')
    js_url = SAMS_HOME_URL.rstrip('/') + path
    log(f'下载 PX init.js: {js_url}')
    rj = cc_requests.get(js_url, headers={'User-Agent': ua, 'Referer': SAMS_HOME_URL},
                         impersonate=impersonate, timeout=30, proxies=proxies)
    if rj.status_code != 200 or len(rj.text) < 1000:
        raise RuntimeError(f'下载 PX init.js 失败: {rj.status_code} (url={js_url} len={len(rj.text)})')
    with open(PX_JS_LOCAL, 'w', encoding='utf-8') as f:
        f.write(rj.text)
    log(f'PX init.js 已更新缓存: {len(rj.text):,} bytes')
    return rj.text


def fetch_px_init_js(log=print, proxies=None, ua=None, impersonate='chrome124'):
    """优先用未过期缓存;过期重下;重下失败回退旧缓存(有旧 sensor 也能采到 cookie)。"""
    have_cache = os.path.exists(PX_JS_LOCAL) and os.path.getsize(PX_JS_LOCAL) > 1000
    if have_cache:
        age = time.time() - os.path.getmtime(PX_JS_LOCAL)
        if age < PX_JS_TTL_SECONDS:
            with open(PX_JS_LOCAL, 'r', encoding='utf-8') as f:
                log(f'PX init.js 命中缓存 (age={age / 3600:.1f}h)')
                return f.read()
        log(f'PX init.js 缓存过期 (age={age / 3600:.1f}h)，重新下载')
    else:
        log('PX init.js 无缓存,下载中')
    try:
        return _download_px_init_js(log, proxies=proxies, ua=ua, impersonate=impersonate)
    except Exception as e:
        if have_cache:
            with open(PX_JS_LOCAL, 'r', encoding='utf-8') as f:
                log(f'重下失败({type(e).__name__}: {e})，回退旧缓存(stale)')
                return f.read()
        raise


def _fetch_px_cookies_inproc(logger=None, max_rounds=30, proxies=None):
    """进程内跑 iv8 补环境,返回 PX cookies dict。必须在主线程才稳定。"""
    log = logger.info if logger else print
    profile = random.choice(PX_PROFILES)
    ua = profile['ua']
    environment = build_environment(profile)
    log(f'采集画像: impersonate={profile["impersonate"]} platform={profile["platform"]} '
        f'cores={profile["hardwareConcurrency"]} ua={ua}')

    px_js = fetch_px_init_js(log=log, proxies=proxies, ua=ua, impersonate=profile['impersonate'])
    log(f'PX init.js loaded: {len(px_js):,} bytes')

    session = py_requests.Session()
    session.headers.update({'User-Agent': ua, 'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9',
                            'Origin': 'https://www.samsclub.com', 'Referer': 'https://www.samsclub.com/'})
    if proxies:
        session.proxies = proxies

    ctx = iv8.JSContext(environment=environment, time_mode='logical')
    px_cookies = {}
    try:
        ctx.eval("__iv8__.page.load({baseURL:'https://www.samsclub.com/',"
                 "html:'<html><head></head><body></body></html>',resources:{}});")
        ctx.eval(PX_BRIDGE_JS)
        ctx.eval(px_js, name='https://www.samsclub.com/px/PXsLC3j22K/init.js')
        try:
            _keys = ctx.eval('Object.keys(window.PXsLC3j22K||{}).join(",")')
            log(f'PX SDK keys=[{_keys}]')
        except Exception as e:
            log(f'PX SDK 检查失败: {e}')

        total = 0
        for round_num in range(1, max_rounds + 1):
            ctx.eval('__iv8__.eventLoop.sleep(300)')
            xhr_list = ctx.eval('window.__px_xhr_list__', to_py=True) or []
            pending = [r for r in xhr_list if r.get('state') == 'sent']
            if pending:
                for req in pending:
                    url = req.get('url', '')
                    if not any(d in url for d in ('px-cloud.net', 'px-cdn.net', 'ift.px-cloud.net')):
                        req['state'] = 'skip'
                        continue
                    method = req.get('method', 'GET')
                    req_headers = req.get('headers') or {}
                    body = req.get('body')
                    log(f'[iv8 r{round_num}] {method} {url[:130]}')
                    try:
                        if method == 'POST':
                            resp = session.post(url, data=body, headers=req_headers, timeout=15)
                        else:
                            resp = session.get(url, headers=req_headers, timeout=15)
                        log(f'  → {resp.status_code} ({len(resp.text)}B)')
                        ctx.add_resource(url=url, body=resp.text, status=resp.status_code, headers=dict(resp.headers))
                        req_idx = xhr_list.index(req)
                        resp_text_escaped = json.dumps(resp.text)
                        ctx.eval(f"""
                            (function(){{
                                var list = window.__px_xhr_list__;
                                if(list[{req_idx}] && list[{req_idx}].xhr) {{
                                    var x = list[{req_idx}].xhr;
                                    Object.defineProperty(x,'responseText',{{get:function(){{return {resp_text_escaped};}},configurable:true}});
                                    Object.defineProperty(x,'response',{{get:function(){{return {resp_text_escaped};}},configurable:true}});
                                    Object.defineProperty(x,'status',{{get:function(){{return {resp.status_code};}},configurable:true}});
                                    Object.defineProperty(x,'statusText',{{get:function(){{return 'OK';}},configurable:true}});
                                    Object.defineProperty(x,'readyState',{{get:function(){{return 4;}},configurable:true}});
                                    list[{req_idx}].state = 'done';
                                    if(x.onload) x.onload();
                                    if(x.onreadystatechange) x.onreadystatechange();
                                }}
                            }})();
                        """)
                        if 'set-cookie' in resp.headers:
                            for cpair in resp.headers['set-cookie'].split(','):
                                cpair = cpair.strip()
                                if '=' in cpair:
                                    ctx.eval(f"document.cookie = {json.dumps(cpair.split(';')[0])};")
                        total += 1
                    except Exception as e:
                        log(f'PX 上游请求失败: {type(e).__name__}: {str(e)[:100]}')
                        req['state'] = 'error'
                ctx.eval('__iv8__.eventLoop.drain()')
            else:
                if round_num > 12 and total >= 2:
                    log(f'iv8 no more pending ({total} done), 提前结束')
                    break

        ctx.eval('__iv8__.eventLoop.sleep(2000)')
        cookie_str = ctx.eval('document.cookie') or ''
        for c in cookie_str.split(';'):
            c = c.strip()
            if '=' in c:
                k, v = c.split('=', 1)
                if k in PX_COOKIE_KEYS:
                    px_cookies[k] = v
    finally:
        ctx.close()
    log(f'iv8 补环境完成,PX cookies keys: {list(px_cookies.keys())}')
    return px_cookies


def fetch_px_cookies(logger=None, max_rounds=30, proxies=None, timeout=120):
    """铸一组 PX cookies。默认 fork 干净子进程跑 iv8(避开 V8 子线程初始化失败 + 多线程隔离)。"""
    log = logger.info if logger else print
    cmd = [sys.executable, os.path.abspath(__file__), '--worker']
    if max_rounds != 30:
        cmd += ['--max-rounds', str(max_rounds)]
    if proxies:
        cmd += ['--proxies-json', json.dumps(proxies)]

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    log(f'fetch_px_cookies → 子进程: {" ".join(cmd[:2])} --worker ...')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                cwd=os.path.dirname(os.path.abspath(__file__)), env=env,
                                encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        log(f'fetch_px_cookies 子进程超时({timeout}s)')
        return {}

    stdout = result.stdout or ''
    cookies = {}
    for line in stdout.splitlines():
        if line.startswith('===PX_COOKIES_JSON==='):
            try:
                cookies = json.loads(line.split('===', 2)[2].strip())
            except Exception:
                pass
            break
    if not cookies:
        log(f'子进程未返回 cookies. rc={result.returncode}\n--- stdout tail ---\n{stdout[-1200:]}\n'
            f'--- stderr tail ---\n{(result.stderr or "")[-800:]}')
    else:
        log(f'fetch_px_cookies 子进程拿到: {list(cookies.keys())}')
    return cookies


# ─────────────────────────── 调搜索接口(用 PX cookies) ───────────────────────────

def is_blocked(resp):
    """PX/反爬拦截判定。返回拦截原因字符串,未拦截返回 None。"""
    if resp.status_code != 200:
        return f'status {resp.status_code}'
    t = resp.text
    for marker in ('Robot or human?', 'Access to this page has been denied',
                   'no robots allowed', 'Popular items in your club'):
        if marker in t:
            return marker
    return None


def search_products(cookies, keyword, club_id='4996', impersonate='chrome131', ua=DEFAULT_UA, proxies=None):
    """用 PX cookies 调 samsclub 搜索接口。返回 curl_cffi response。
    club_id: 俱乐部门店 id(clubId / assortmentStoreId);PX token 与 IP 解耦,proxies 可选。"""
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        'referer': f'https://www.samsclub.com/s/{keyword}',
        'user-agent': ua,
    }
    params = {
        'sourceType': '1', 'limit': '45', 'clubId': club_id, 'searchTerm': keyword,
        'br': 'true', 'secondaryResults': '2', 'wmsponsored': '1', 'wmsba': 'true',
        'banner': 'true', 'wmVideo': 'true',
    }
    req_cookies = {k: v for k, v in cookies.items() if k in PX_COOKIE_KEYS}
    if club_id:
        req_cookies['assortmentStoreId'] = club_id
    return cc_requests.get(SEARCH_API, headers=headers, params=params, cookies=req_cookies,
                           impersonate=impersonate, timeout=20, proxies=proxies)


def _count_products(resp):
    """从搜索 JSON 里粗略数出商品条数(结构可能随接口调整,尽力而为)。"""
    try:
        j = resp.json()
    except Exception:
        return None, None
    # samsclub search JSON 常见 records 路径;逐个探测
    for path in ('payload.records', 'searchResult', 'records', 'items', 'products'):
        node = j
        ok = True
        for seg in path.split('.'):
            if isinstance(node, dict) and seg in node:
                node = node[seg]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            return len(node), path
    return None, list(j.keys()) if isinstance(j, dict) else None


# ─────────────────────────── 入口 ───────────────────────────

def _worker_main():
    """子进程入口:跑 _fetch_px_cookies_inproc,结果通过 stdout 标记行返回。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--max-rounds', type=int, default=30)
    parser.add_argument('--proxies-json', type=str, default='')
    args, _ = parser.parse_known_args()
    proxies = json.loads(args.proxies_json) if args.proxies_json else None
    try:
        cookies = _fetch_px_cookies_inproc(logger=None, max_rounds=args.max_rounds, proxies=proxies)
    except Exception as e:
        print(f'WORKER_ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        cookies = {}
    print(f'===PX_COOKIES_JSON==={json.dumps(cookies)}')


def main():
    parser = argparse.ArgumentParser(description="Sam's Club PX 独立示例:铸 cookie → 调搜索接口")
    parser.add_argument('--keyword', default='zipper storage bags')
    parser.add_argument('--club', default='4996', help='clubId / assortmentStoreId')
    parser.add_argument('--proxy', default='', help='可选代理,如 http://user:pass@ip:port')
    args = parser.parse_args()
    proxies = {'http': args.proxy, 'https': args.proxy} if args.proxy else None

    print('=' * 60)
    print("[1/2] iv8 补环境铸 PX cookies ...")
    cookies = fetch_px_cookies(proxies=proxies)
    if not cookies.get('_px3'):
        print(f'  [失败] 未拿到 _px3:{cookies}')
        return
    print(f"  [成功] PX cookies: { {k: v[:40] + '...' for k, v in cookies.items()} }")

    print('=' * 60)
    print(f"[2/2] 用 cookies 调搜索接口:keyword={args.keyword!r} club={args.club}")
    resp = search_products(cookies, args.keyword, club_id=args.club, proxies=proxies)
    reason = is_blocked(resp)
    print(f'  HTTP {resp.status_code}  len={len(resp.text)}')
    if reason:
        print(f'  [拦截] {reason}  片段: {resp.text[:160]!r}')
        return
    n, where = _count_products(resp)
    if n is not None:
        print(f'  [成功] 出值:{n} 条商品 (path={where})')
    else:
        print(f'  [成功] 200 JSON,顶层键: {where}')
    print('=' * 60)


if __name__ == '__main__':
    if '--worker' in sys.argv:
        _worker_main()
    else:
        main()
