"""Sam's Club PerimeterX(PX)绕过 —— 独立示例(脱离 spiders_2 框架)

两段完整链路:
  1) iv8 补环境铸 PX cookies(_px3/_pxvid/pxcts/_pxde)
  2) 用 cookies 调 samsclub 搜索接口(/api/node/vivaldi/browse/v2/products/search)拿真实数据

依赖:iv8 · httpcloak(TLS 指纹,替代 curl_cffi)。px_init.js(PX sensor)运行时自动下载并缓存到同目录。
本机(py310)直接跑:
    python examples/samsclub_px_example.py
    python examples/samsclub_px_example.py --keyword "milk" --club 4996 --proxy http://user:pass@ip:port
    python examples/samsclub_px_example.py --worker      # (内部子进程用,勿手动)

说明:iv8 的 V8 isolate 在子线程里跑 PX SDK 会异常(SDK 顶层 try/catch 吞错,keys=[]),
故 fetch_px_cookies() 默认 fork 一个干净子进程跑 iv8,通过 stdout 回传 cookies JSON。

⚠️ token 质量取决于**铸造时的采集 IP 信誉**(PX 评分):干净/住宅 IP(如生产服务器)铸的 token
   → 搜索接口 200 出值;中国 dev IP / 数据中心段铸的 token → PX 评分低 → 搜索接口 412
   ("are-you-human")。这是 IP 信誉问题,非脚本逻辑问题。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import iv8
import httpcloak

SAMS_HOME_URL = 'https://www.samsclub.com/'
SEARCH_API = 'https://www.samsclub.com/api/node/vivaldi/browse/v2/products/search'
PX_JS_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), 'px_init.js'))
PX_APP_ID = 'PXsLC3j22K'  # sensor 路径 = /px/<PX_APP_ID>/init.js(首页提取不到时兜底)
PX_COOKIE_KEYS = ('_pxvid', '_px3', 'pxcts', '_pxde')
PX_JS_TTL_SECONDS = 3 * 24 * 3600  # 缓存超 3 天重下(PX 轮换 sensor 后旧 token 会 412)

# —— 简单映射:一套自洽的 Chrome 画像。httpcloak preset 决定 TLS 指纹,UA/environment 与之对齐 ——
PRESET = 'chrome-146-windows'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36')
ENVIRONMENT = {
    'location': {'href': SAMS_HOME_URL, 'origin': 'https://www.samsclub.com',
                 'host': 'www.samsclub.com', 'hostname': 'www.samsclub.com'},
    'navigator': {'userAgent': UA, 'platform': 'Win32', 'language': 'en-US',
                  'hardwareConcurrency': 8, 'deviceMemory': 8, 'maxTouchPoints': 0, 'vendor': 'Google Inc.'},
    'screen': {'width': 1920, 'height': 1080, 'availWidth': 1920, 'availHeight': 1040, 'colorDepth': 24},
    'webgl': {'vendor': 'Google Inc. (NVIDIA)',
              'renderer': 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)'},
}


def _session(proxy=None, timeout=30):
    return httpcloak.Session(preset=PRESET, proxy=proxy, timeout=timeout)


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


def _download_px_init_js(log, proxy=None):
    """去 sams 首页找 PX init.js 路径并下载,写缓存;失败抛异常。"""
    s = _session(proxy)
    r = s.get(SAMS_HOME_URL, headers={'user-agent': UA, 'accept': 'text/html'})
    html = r.text
    log(f'PX 首页 status={r.status_code} len={len(html)}')
    m = re.search(r'(/px/[A-Za-z0-9_\-]{6,}/init\.js)', html)
    if m:
        path = m.group(1)
    else:
        m2 = re.search(r'(PX[A-Za-z0-9]{8,})', html)
        path = f'/px/{m2.group(1) if m2 else PX_APP_ID}/init.js'
        log(f'首页未命中 sensor 路径,兜底 → {path}')
    js_url = SAMS_HOME_URL.rstrip('/') + path
    log(f'下载 PX init.js: {js_url}')
    rj = s.get(js_url, headers={'user-agent': UA, 'referer': SAMS_HOME_URL})
    if rj.status_code != 200 or len(rj.text) < 1000:
        raise RuntimeError(f'下载 PX init.js 失败: {rj.status_code} (len={len(rj.text)})')
    with open(PX_JS_LOCAL, 'w', encoding='utf-8') as f:
        f.write(rj.text)
    log(f'PX init.js 已缓存: {len(rj.text):,} bytes')
    return rj.text


def fetch_px_init_js(log=print, proxy=None):
    """优先用未过期缓存;过期重下;重下失败回退旧缓存。"""
    have = os.path.exists(PX_JS_LOCAL) and os.path.getsize(PX_JS_LOCAL) > 1000
    if have:
        age = time.time() - os.path.getmtime(PX_JS_LOCAL)
        if age < PX_JS_TTL_SECONDS:
            with open(PX_JS_LOCAL, encoding='utf-8') as f:
                log(f'PX init.js 命中缓存 (age={age / 3600:.1f}h)')
                return f.read()
        log(f'PX init.js 缓存过期 (age={age / 3600:.1f}h)，重下')
    else:
        log('PX init.js 无缓存,下载中')
    try:
        return _download_px_init_js(log, proxy=proxy)
    except Exception as e:
        if have:
            with open(PX_JS_LOCAL, encoding='utf-8') as f:
                log(f'重下失败({type(e).__name__}: {e})，回退旧缓存')
                return f.read()
        raise


def _fetch_px_cookies_inproc(logger=None, max_rounds=30, proxy=None):
    """进程内跑 iv8 补环境,返回 PX cookies dict。必须在主线程才稳定。"""
    log = logger.info if logger else print
    px_js = fetch_px_init_js(log=log, proxy=proxy)
    log(f'PX init.js loaded: {len(px_js):,} bytes  (preset={PRESET})')

    s = _session(proxy)  # PX 上游(px-cloud.net)请求用同一 TLS 指纹 + 出口
    base_hdr = {'user-agent': UA, 'accept': '*/*', 'accept-language': 'en-US,en;q=0.9',
                'origin': 'https://www.samsclub.com', 'referer': 'https://www.samsclub.com/'}

    ctx = iv8.JSContext(environment=ENVIRONMENT, time_mode='logical')
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
                    if not any(d in url for d in ('px-cloud.net', 'px-cdn.net')):
                        req['state'] = 'skip'
                        continue
                    method = req.get('method', 'GET')
                    hdr = {**base_hdr, **(req.get('headers') or {})}
                    body = req.get('body')
                    log(f'[iv8 r{round_num}] {method} {url[:120]}')
                    try:
                        if method == 'POST':
                            resp = s.post(url, data=body, headers=hdr, timeout=15)
                        else:
                            resp = s.get(url, headers=hdr, timeout=15)
                        # httpcloak 的 text/headers 需强制转纯 str/int/dict,否则 iv8 C++ 转换报错
                        rtext = resp.text if isinstance(resp.text, str) else bytes(resp.text).decode('utf-8', 'replace')
                        rheaders = {str(k): str(v) for k, v in dict(resp.headers).items()}
                        rstatus = int(resp.status_code)
                        log(f'  → {rstatus} ({len(rtext)}B)')
                        ctx.add_resource(url=str(url), body=rtext, status=rstatus, headers=rheaders)
                        idx = xhr_list.index(req)
                        esc = json.dumps(rtext)
                        ctx.eval(f"""
                            (function(){{
                                var l=window.__px_xhr_list__;
                                if(l[{idx}] && l[{idx}].xhr) {{
                                    var x=l[{idx}].xhr;
                                    Object.defineProperty(x,'responseText',{{get:function(){{return {esc};}},configurable:true}});
                                    Object.defineProperty(x,'response',{{get:function(){{return {esc};}},configurable:true}});
                                    Object.defineProperty(x,'status',{{get:function(){{return {rstatus};}},configurable:true}});
                                    Object.defineProperty(x,'readyState',{{get:function(){{return 4;}},configurable:true}});
                                    l[{idx}].state='done';
                                    if(x.onload)x.onload();
                                    if(x.onreadystatechange)x.onreadystatechange();
                                }}
                            }})();
                        """)
                        sc = rheaders.get('set-cookie') or rheaders.get('Set-Cookie') or ''
                        for cpair in sc.split(','):
                            cpair = cpair.strip()
                            if '=' in cpair:
                                ctx.eval(f"document.cookie = {json.dumps(cpair.split(';')[0])};")
                        total += 1
                    except Exception as e:
                        log(f'PX 上游请求失败: {type(e).__name__}: {str(e)[:100]}')
                        req['state'] = 'error'
                ctx.eval('__iv8__.eventLoop.drain()')
            elif round_num > 12 and total >= 2:
                log(f'iv8 no more pending ({total} done), 提前结束')
                break

        ctx.eval('__iv8__.eventLoop.sleep(2000)')
        for c in (ctx.eval('document.cookie') or '').split(';'):
            c = c.strip()
            if '=' in c:
                k, v = c.split('=', 1)
                if k in PX_COOKIE_KEYS:
                    px_cookies[k] = v
    finally:
        ctx.close()
    log(f'iv8 补环境完成,PX cookies keys: {list(px_cookies.keys())}')
    return px_cookies


def fetch_px_cookies(logger=None, max_rounds=30, proxy=None, timeout=120):
    """铸一组 PX cookies。默认 fork 干净子进程跑 iv8(避开 V8 子线程初始化失败 + 多线程隔离)。"""
    log = logger.info if logger else print
    cmd = [sys.executable, os.path.abspath(__file__), '--worker']
    if max_rounds != 30:
        cmd += ['--max-rounds', str(max_rounds)]
    if proxy:
        cmd += ['--proxy', proxy]
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    log('fetch_px_cookies → 子进程铸 cookie ...')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                cwd=os.path.dirname(os.path.abspath(__file__)), env=env,
                                encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        log(f'fetch_px_cookies 子进程超时({timeout}s)')
        return {}
    cookies = {}
    for line in (result.stdout or '').splitlines():
        if line.startswith('===PX_COOKIES_JSON==='):
            try:
                cookies = json.loads(line.split('===', 2)[2].strip())
            except Exception:
                pass
            break
    if not cookies:
        log(f'子进程未返回 cookies. rc={result.returncode}\n'
            f'--- stdout ---\n{(result.stdout or "")[-1200:]}\n--- stderr ---\n{(result.stderr or "")[-800:]}')
    else:
        log(f'fetch_px_cookies 拿到: {list(cookies.keys())}')
    return cookies


# ─────────────────────────── 调搜索接口(用 PX cookies) ───────────────────────────

def is_blocked(resp):
    """PX/反爬拦截判定。返回原因字符串,未拦截返回 None。"""
    if resp.status_code != 200:
        return f'status {resp.status_code}'
    for marker in ('Robot or human?', 'Access to this page has been denied',
                   'no robots allowed', 'Popular items in your club'):
        if marker in resp.text:
            return marker
    return None


def search_products(cookies, keyword, club_id='4996', proxy=None):
    """用 PX cookies 调 samsclub 搜索接口,返回 httpcloak response。"""
    headers = {'accept': 'application/json, text/plain, */*', 'accept-language': 'en-US,en;q=0.9',
               'referer': f'https://www.samsclub.com/s/{keyword}', 'user-agent': UA}
    params = {'sourceType': '1', 'limit': '45', 'clubId': club_id, 'searchTerm': keyword,
              'br': 'true', 'secondaryResults': '2', 'wmsponsored': '1', 'wmsba': 'true',
              'banner': 'true', 'wmVideo': 'true'}
    ck = {k: v for k, v in cookies.items() if k in PX_COOKIE_KEYS}
    if club_id:
        ck['assortmentStoreId'] = club_id
    return _session(proxy).get(SEARCH_API, params=params, headers=headers, cookies=ck)


def _count_products(resp):
    try:
        j = resp.json()
    except Exception:
        return None, None
    for path in ('payload.records', 'searchResult', 'records', 'items', 'products'):
        node, ok = j, True
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
    p = argparse.ArgumentParser()
    p.add_argument('--worker', action='store_true')
    p.add_argument('--max-rounds', type=int, default=30)
    p.add_argument('--proxy', default='')
    a, _ = p.parse_known_args()
    try:
        cookies = _fetch_px_cookies_inproc(logger=None, max_rounds=a.max_rounds, proxy=a.proxy or None)
    except Exception as e:
        print(f'WORKER_ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        cookies = {}
    print(f'===PX_COOKIES_JSON==={json.dumps(cookies)}')


def main():
    p = argparse.ArgumentParser(description="Sam's Club PX 独立示例:铸 cookie → 调搜索接口")
    p.add_argument('--keyword', default='zipper storage bags')
    p.add_argument('--club', default='4996', help='clubId / assortmentStoreId')
    p.add_argument('--proxy', default='', help='可选代理,如 http://user:pass@ip:port')
    a = p.parse_args()
    proxy = a.proxy or None

    print('=' * 60)
    print('[1/2] iv8 补环境铸 PX cookies ...')
    cookies = fetch_px_cookies(proxy=proxy)
    if not cookies.get('_px3'):
        print(f'  [失败] 未拿到 _px3:{cookies}')
        return
    print(f"  [成功] PX cookies: { {k: v[:40] + '...' for k, v in cookies.items()} }")

    print('=' * 60)
    print(f'[2/2] 用 cookies 调搜索接口:keyword={a.keyword!r} club={a.club}')
    resp = search_products(cookies, a.keyword, club_id=a.club, proxy=proxy)
    reason = is_blocked(resp)
    print(f'  HTTP {resp.status_code}  len={len(resp.text)}')
    if reason:
        print(f'  [拦截] {reason}  片段: {resp.text[:160]!r}')
        return
    n, where = _count_products(resp)
    print(f'  [成功] 出值:{n} 条商品 (path={where})' if n is not None
          else f'  [成功] 200 JSON,顶层键: {where}')
    print('=' * 60)


if __name__ == '__main__':
    _worker_main() if '--worker' in sys.argv else main()
