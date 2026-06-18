# iv8 补环境教程

## 一、项目简介

**iv8** 是基于 V8 引擎的高性能 Python 原生扩展，在 C++ 层实现浏览器 API，提供高可控、高保真的 BOM/DOM/CSSOM 模拟。核心特点：

- 纯 C++ 实现浏览器 API，无需启动浏览器
- 内置 Chrome/Windows 默认指纹（200+ 字段）
- 支持流式 HTML 解析、事件循环、可信输入事件
- 多线程并行（每个 Context 独占 V8 Isolate，释放 GIL）
- 内置 DevTools 远程调试与 API 调用链监控

**适用场景：** 浏览器环境模拟、JS 逆向补环境、自动化脚本执行、安全研究。

---

## 二、安装

```bash
pip install iv8
```

支持 Python 3.8 – 3.14，Windows (x64)、Linux (x64)。

---

## 三、核心 API 参考

### 3.1 JSContext — 主入口类

```python
import iv8

ctx = iv8.JSContext(
    mode="prod",           # "prod" 生产模式 / "debug" 调试模式
    environment=None,      # 浏览器指纹配置字典
    config=None,           # 框架行为配置（timezone 等）
    time_mode="logical",   # "logical" 逻辑时间 / "system" 系统时间
    js_api="__iv8__",      # JS 侧工具对象挂载名
    ignore_apis=None,      # 从监控日志排除的 API 列表
)
```

**推荐使用上下文管理器：**

```python
with iv8.JSContext() as ctx:
    ctx.eval("1 + 1")
# 自动释放资源
```

### 3.2 核心方法

| 方法 | 说明 |
|------|------|
| `ctx.eval(source, to_py=False)` | 执行 JS 代码，返回值自动转 Python 类型 |
| `ctx.close(gc="none")` | 释放上下文，gc 可选 `"low_memory"` / `"aggressive"` |
| `ctx.add_resource(url, body, status=200, headers=None)` | 注入离线 HTTP 响应 |
| `ctx.with_devtools(port=9229, watch_apis=None)` | 启用 DevTools 调试 |
| `ctx.expose(obj, name)` | 将 Python 对象暴露到 `__iv8__.data` 命名空间 |
| `iv8.JSContext.get_defaults()` | 获取所有可配置的 environment/config 路径及默认值 |

### 3.3 JS 侧工具对象 `window.__iv8__`

该对象设计为"不可检测"（`typeof window.__iv8__ === "undefined"`），不影响目标 JS 行为。

| 工具 | 说明 |
|------|------|
| `__iv8__.eventLoop.advance(total, step?)` | 分帧推进虚拟时间（默认步长 ~16.67ms） |
| `__iv8__.eventLoop.sleep(ms)` | 推进虚拟时间 ms 毫秒，排空任务队列 |
| `__iv8__.eventLoop.tick(ms?)` | 推进 ms 毫秒并执行一轮事件循环 |
| `__iv8__.eventLoop.drain(max?)` | 排空所有已到期任务，不推进时间 |
| `__iv8__.eventLoop.drainMicrotasks()` | 仅排空微任务队列 |
| `__iv8__.eventLoop.drainTimers()` | 仅处理已到期的定时器回调 |
| `__iv8__.page.load(snapshot)` | 流式加载 HTML 文档 |
| `__iv8__.input.dispatchMouseEvent(init)` | 派发可信鼠标事件（isTrusted=true） |
| `__iv8__.input.dispatchPointerEvent(init)` | 派发可信指针事件 |
| `__iv8__.netLog.entries` | 捕获的网络请求日志数组 |
| `__iv8__.wrapNative(fn, name)` | 将 JS 函数伪装为原生函数 |
| `__iv8__.help()` | 打印所有可用工具及说明 |

---

## 四、补环境操作指南

### 4.1 基础用法 — 最小可运行示例

```python
import iv8

with iv8.JSContext() as ctx:
    # 浏览器 API 开箱可用，无需手动补
    print(ctx.eval("navigator.userAgent"))    # Mozilla/5.0 ...
    print(ctx.eval("navigator.webdriver"))    # False
    print(ctx.eval("document.cookie"))        # ""
    print(ctx.eval("window.crypto.getRandomValues(new Uint8Array(4))"))
```

### 4.2 指纹配置 — environment 参数

通过 `environment` 字典覆盖浏览器指纹字段，未覆盖的保持默认值：

```python
environment = {
    "navigator": {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "platform": "Win32",
        "language": "zh-CN",
        "languages": ["zh-CN", "en-US"],
        "hardwareConcurrency": 8,
        "deviceMemory": 8,
    },
    "screen": {
        "width": 1920,
        "height": 1080,
        "colorDepth": 24,
    },
    "location": {
        "href": "https://example.com/page",
        "origin": "https://example.com",
        "protocol": "https:",
        "host": "example.com",
        "hostname": "example.com",
        "port": "",
        "pathname": "/page",
        "search": "",
        "hash": "",
    },
    "webgl": {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060)",
    },
}

with iv8.JSContext(environment=environment) as ctx:
    print(ctx.eval("navigator.userAgent"))
    print(ctx.eval("screen.width"))  # 1920
```

**查看所有可配置项：**

```python
for path, value in sorted(iv8.JSContext.get_defaults().items()):
    print(f"{path} = {value!r}")
```

### 4.3 页面加载 — page.load

`page.load` 对齐浏览器导航流程：HTML 解析 → `<script>` 暂停执行 → 样式表处理 → DOMContentLoaded / load 事件派发。

```python
with iv8.JSContext(environment=environment) as ctx:
    ctx.eval("""
        window.__iv8__.page.load({
            baseURL: 'https://example.com',
            html: '<html><head><script src="/app.js"></script></head><body></body></html>',
            resources: {
                'https://example.com/app.js': { body: 'window.APP_LOADED = true;' }
            },
            headers: [['set-cookie', 'sid=abc123; path=/']]
        });
    """)
    print(ctx.eval("window.APP_LOADED"))  # True
```

**page.load 参数说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `baseURL` | string | 是 | 页面 URL，同步到 `document.URL`、`location.href` |
| `html` | string | 是 | HTML 源码 |
| `resources` | Object | 否 | 外联资源映射（URL → 内容），`<script src>` / `<link href>` / XHR / fetch 均从中匹配 |
| `headers` | Object/Array | 否 | 主文档响应头（CSP、Set-Cookie 等） |

**resources 格式：**

```javascript
resources: {
    // 简写：value 直接为内容字符串
    'https://example.com/lib.js': 'var LIB = true;',

    // 完整格式：可指定 HTTP 状态码、响应头、body
    'https://example.com/app.js': {
        body: 'var APP = true;',
        status: 200,
        headers: [['content-type', 'application/javascript']],
    }
}
```

### 4.4 轻量 DOM 构建 — innerHTML

如果目标 JS 不依赖 DOMContentLoaded / load 事件，使用 innerHTML 性能更好：

```python
import json

with iv8.JSContext(environment=environment) as ctx:
    html_content = '<html><body><div id="app">Hello</div></body></html>'
    ctx.eval(f"document.documentElement.innerHTML = {json.dumps(html_content)}")
    print(ctx.eval("document.getElementById('app').textContent"))  # "Hello"
```

### 4.5 事件循环控制

iv8 使用逻辑时间模式，`sleep(5000)` 瞬间完成，不会真正等待：

```python
with iv8.JSContext(time_mode="logical") as ctx:
    ctx.eval("""
        var result = [];
        setTimeout(() => result.push('timer-100'), 100);
        setTimeout(() => result.push('timer-500'), 500);
        Promise.resolve().then(() => result.push('micro'));
    """)

    # 推进虚拟时间 600ms，排空所有任务
    ctx.eval("window.__iv8__.eventLoop.sleep(600)")
    print(ctx.eval("result"))
    # ['micro', 'timer-100', 'timer-500']
```

**时间模式选择：**

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `logical`（默认） | 纯逻辑推进，瞬间完成 | 自动化、快速执行 |
| `system` | 系统时间锚定，Date.now() 反映真实耗时 | POW、时间差校验 |

### 4.6 网络请求拦截与注入

iv8 社区版不直接发起 HTTP 请求，网络层完全由用户控制：

```python
import requests as req

with iv8.JSContext(environment=environment) as ctx:
    ctx.eval("""
        window.__iv8__.page.load({
            baseURL: 'https://example.com',
            html: '<html><body></body></html>'
        });
    """)

    # JS 侧发起异步 XHR
    ctx.eval("""
        var xhr = new XMLHttpRequest();
        xhr.open('GET', 'https://api.example.com/data');
        xhr.onload = function() { window._result = xhr.responseText; };
        xhr.send();
    """)

    # Python 侧发真实请求，注入响应
    resp = req.get("https://api.example.com/data")
    ctx.add_resource(
        url="https://api.example.com/data",
        body=resp.text,
        status=resp.status_code,
        headers=dict(resp.headers),
    )

    # 推进事件循环，XHR 回调命中注入的资源
    ctx.eval("window.__iv8__.eventLoop.drain()")
    print(ctx.eval("window._result"))
```

**查看 JS 发起的网络请求：**

```python
entries = ctx.eval("window.__iv8__.netLog.entries", to_py=True)
for entry in entries:
    print(f"{entry['method']} {entry['url']}")
```

### 4.7 函数伪装 — wrapNative

将自定义 JS 函数伪装为浏览器原生函数，`toString()` 返回 `[native code]`：

```python
with iv8.JSContext() as ctx:
    ctx.eval("""
        // 补一个 MessageChannel（某些 JS 会检测）
        window.MessageChannel = __iv8__.wrapNative(function() {
            const port1 = { onmessage: null };
            const port2 = { onmessage: null };
            port1.postMessage = function(data) {
                if (port2.onmessage) setTimeout(() => port2.onmessage({data}), 0);
            };
            port2.postMessage = function(data) {
                if (port1.onmessage) setTimeout(() => port1.onmessage({data}), 0);
            };
            return { port1, port2 };
        }, 'MessageChannel');
    """)
    print(ctx.eval("MessageChannel.toString()"))
    # "function MessageChannel() { [native code] }"
```

### 4.8 Python ↔ JS 互调 — expose

将 Python 对象暴露到 JS 的 `__iv8__.data` 命名空间：

```python
import requests

with iv8.JSContext() as ctx:
    # 命名暴露
    ctx.expose(requests.get, "httpGet")
    # JS 中调用: __iv8__.data.httpGet("https://...")

    # 暴露字典数据
    ctx.expose({"token": "abc123", "debug": True}, "config")
    result = ctx.eval("__iv8__.data.config.token")  # "abc123"

    # 暴露 page.load 的 snapshot 对象
    snapshot = {
        "baseURL": "https://example.com",
        "html": "<html><body></body></html>",
        "resources": {}
    }
    ctx.expose(snapshot, "snapshot")
    ctx.eval("__iv8__.page.load(__iv8__.data.snapshot)")
```

### 4.9 DevTools 调试与 API 监控

```python
# 启用调试模式 + DevTools
with iv8.JSContext(mode='debug').with_devtools(
    port=9229,
    watch_apis=["navigator.userAgent", "document.cookie", "canvas.toDataURL"],
    enable_console=False,
) as ctx:
    ctx.eval("let ua = navigator.userAgent;")  # 触发 API 访问断点
    ctx.eval("vconsole.log('调试信息', ua);")  # 仅 DevTools 可见
    ctx.eval("vdebugger;")  # 在 DevTools 中暂停（替代被禁用的 debugger;）
```

**注意事项：**
- `debugger;` 被禁用（防止目标 JS 反调试），使用 `vdebugger;` 替代
- `console` 可能被检测，设置 `enable_console=False` 后使用 `vconsole` 替代

---

## 五、实战案例模板

### 5.1 案例一：抖音 a_bogus 签名（bdms）

典型的"加载 JS SDK → 初始化 → 调用签名方法"流程：

```python
import iv8
import requests
from urllib.parse import urlencode

# 1. 读取目标 JS 文件
with open('./js/bdms_1.0.1.19.js', 'r', encoding='utf-8') as f:
    js_code = f.read()

# 2. 配置环境指纹
environment = {
    "location": {
        "href": "https://www.douyin.com/video/xxxx",
        "origin": "https://www.douyin.com",
        "protocol": "https:",
        "host": "www.douyin.com",
        "hostname": "www.douyin.com",
        "port": "",
        "pathname": "/video/xxxx",
        "search": "",
        "hash": ""
    },
    "navigator": {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "language": "en-US",
        "languages": ["en-US", "en"],
    },
}

# 3. 创建上下文并执行
with iv8.JSContext(environment=environment) as ctx:
    # 补 MessageChannel（bdms 依赖）
    ctx.eval("""
        window.MessageChannel = __iv8__.wrapNative(function() {
            const port1 = { onmessage: null };
            const port2 = { onmessage: null };
            port1.postMessage = function(data) {
                if (port2.onmessage) setTimeout(() => port2.onmessage({data}), 0);
            };
            port2.postMessage = function(data) {
                if (port1.onmessage) setTimeout(() => port1.onmessage({data}), 0);
            };
            return { port1, port2 };
        }, 'MessageChannel');
    """)

    # 加载并执行 JS
    ctx.eval(js_code)

    # 初始化 bdms SDK
    ctx.eval("""
        window.bdms.init({
            "aid": 6383,
            "dfp": true,
        });
    """)
    ctx.eval("window.__iv8__.eventLoop.sleep(100)")

    # 调用签名方法
    query_str = urlencode(params)
    a_bogus = ctx.eval(f"""
        window.bdms.sign({{url: "https://www-hj.douyin.com/aweme/v1/web/aweme/detail/?{query_str}"}})
    """)
    print(f"a_bogus: {a_bogus}")
```

### 5.2 案例二：京东 h5st 签名

典型的"加载 HTML + 外联 JS → 实例化签名类 → 调用签名"流程：

```python
import hashlib
import json
import iv8

with open('./js/js_security_v3_main.js', 'r', encoding='utf-8') as f:
    js_code = f.read()
with open('./js/jd_index.html', 'r', encoding='utf-8') as f:
    index_html = f.read()

ctx = iv8.JSContext(environment={
    "location": {
        "href": "https://m.jd.com/",
        "origin": "https://m.jd.com",
        "protocol": "https:",
        "host": "m.jd.com",
        "hostname": "m.jd.com",
        "port": "",
        "pathname": "/",
        "search": "",
        "hash": ""
    }
}, config={"timezone": "Asia/Shanghai"})

# 补 MessageChannel
ctx.eval("""
    window.MessageChannel = __iv8__.wrapNative(function() {
        const port1 = { onmessage: null };
        const port2 = { onmessage: null };
        port1.postMessage = function(data) {
            if (port2.onmessage) setTimeout(() => port2.onmessage({data}), 0);
        };
        port2.postMessage = function(data) {
            if (port1.onmessage) setTimeout(() => port1.onmessage({data}), 0);
        };
        return { port1, port2 };
    }, 'MessageChannel');
""")

# 用 innerHTML 加载 HTML（不需要事件派发）
ctx.eval(f"document.documentElement.innerHTML = {json.dumps(index_html)}")

# 执行签名 JS
ctx.eval(js_code, name="https://storage.360buyimg.com/webcontainer/main/js_security_v3_main.js")

# 生成 h5st 签名
body = '{"func":"item_rec"}'
body_hash = hashlib.sha256(body.encode()).hexdigest()
h5st = ctx.eval(f"""
    _ParamsSign = new window.ParamsSignMain({{appId: "2088b"}})
    _ParamsSign._$sdnmd({{
        "appid": "jd-cphdeveloper-m",
        "functionId": "recommend_like_m",
        "body": "{body_hash}"
    }}).h5st
""")
print(f"h5st: {h5st}")
ctx.close()
```

### 5.3 案例三：瑞数/cookie 反爬（药监局/海关模式）

典型的"首次请求被拦截 → 加载反爬 JS → 生成 cookie → 携带 cookie 重试"流程：

```python
import re
import iv8
import requests

environment = {
    "location": {
        "href": "https://www.target.com/page.html",
        "origin": "https://www.target.com",
        "protocol": "https:",
        "host": "www.target.com",
        "hostname": "www.target.com",
        "port": "",
        "pathname": "/page.html",
        "search": "",
        "hash": ""
    },
    "navigator": {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    }
}

headers = {"User-Agent": environment['navigator']['userAgent']}

# 1. 首次请求，获取反爬页面
resp1 = requests.get("https://www.target.com/page.html", headers=headers)

# 2. 提取外联 JS URL
js_match = re.search(r'src="([^"]+\.js)"[^>]*r=\'m\'', resp1.text)
js_url = "https://www.target.com" + js_match.group(1)
js_code = requests.get(js_url, headers=headers, cookies=resp1.cookies.get_dict()).text

# 3. iv8 执行反爬 JS，生成 cookie
with iv8.JSContext(environment=environment, config={"timezone": "Asia/Shanghai"}) as ctx:
    snapshot = {
        "baseURL": environment['location']['href'],
        "html": resp1.text,
        "headers": [[k, v] for k, v in resp1.headers.items()],
        "resources": {js_url: js_code},
    }
    ctx.expose(snapshot, "snapshot")
    ctx.eval("__iv8__.page.load(__iv8__.data.snapshot)")
    ctx.eval("__iv8__.eventLoop.sleep(100)")

    # 从 netLog 获取生成的 cookie
    cookies_str = ctx.eval(
        "__iv8__.netLog.entries[__iv8__.netLog.entries.length - 1].cookieHeader"
    )
    print(f"生成的 cookie: {cookies_str}")

# 4. 携带 cookie 重新请求
final_resp = requests.get(
    "https://www.target.com/api/data",
    headers={**headers, "Cookie": cookies_str}
)
print(final_resp.json())
```

### 5.4 案例四：BOSS 直聘 __zp_stoken__

典型的"获取 seed/name/ts → 下载动态 JS → iv8 执行生成 token"流程：

```python
import json
from urllib.parse import quote
import requests
import iv8

session = requests.Session()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# 1. 首次请求触发 code=37，获取 seed/name/ts
resp = session.post(API_URL, headers=HEADERS, data=DATA)
zp = resp.json()["zpData"]
seed, name, ts = zp["seed"], zp["name"], zp["ts"]

# 2. 下载动态 JS
js_url = f"https://www.zhipin.com/web/common/security-js/{name}.js"
js_code = session.get(js_url, headers={"user-agent": UA}).text

# 3. iv8 执行生成 token
security_url = f"https://www.zhipin.com/web/common/security-check.html?seed={quote(seed)}&name={name}&ts={ts}"

environment = {
    "location": {
        "href": security_url,
        "origin": "https://www.zhipin.com",
        "protocol": "https:",
        "host": "www.zhipin.com",
        "hostname": "www.zhipin.com",
        "port": "",
        "pathname": "/web/common/security-check.html",
        "search": "?" + security_url.split("?", 1)[1],
        "hash": ""
    },
}

with iv8.JSContext(environment=environment) as ctx:
    ctx.eval(js_code)
    ctx.eval("__iv8__.eventLoop.sleep(500)")
    token = ctx.eval("document.cookie")  # 提取 __zp_stoken__
    print(f"__zp_stoken__: {token}")
```

### 5.5 案例五：腾讯滑块验证码（tdc）

典型的"加载验证码 JS → 模拟滑动事件 → 生成 collect 参数"流程：

```python
import iv8

environment = {
    "location": {
        "href": "https://login-user.example.com/login/",
        "origin": "https://login-user.example.com",
        "protocol": "https:",
        "host": "login-user.example.com",
        "hostname": "login-user.example.com",
        "port": "",
        "pathname": "/login/",
        "search": "",
        "hash": ""
    }
}

with iv8.JSContext(environment=environment) as ctx:
    # 加载 tdc JS
    ctx.eval(tdc_js_code)
    ctx.eval("__iv8__.eventLoop.sleep(100)")

    # 模拟可信鼠标事件（isTrusted=true）
    ctx.eval("""
        var btn = document.getElementById('slide-btn');
        __iv8__.input.dispatchMouseEvent({
            type: 'mousedown',
            target: btn,
            clientX: 30, clientY: 200,
            button: 0, buttons: 1
        });
    """)

    # 模拟滑动轨迹
    for x in range(30, 280, 5):
        ctx.eval(f"""
            __iv8__.input.dispatchMouseEvent({{
                type: 'mousemove',
                target: document.body,
                clientX: {x}, clientY: 200,
                button: 0, buttons: 1
            }});
        """)

    ctx.eval("""
        __iv8__.input.dispatchMouseEvent({
            type: 'mouseup',
            target: document.body,
            clientX: 280, clientY: 200,
            button: 0, buttons: 0
        });
    """)

    # 获取 collect 参数
    collect = ctx.eval("TDC.getData()")
    print(f"collect: {collect}")
```

---

## 六、多线程并行

每个 `JSContext` 独占一个 V8 Isolate，执行期释放 GIL，可直接多线程并行：

```python
import threading
import iv8

def run_js(thread_id, environment):
    with iv8.JSContext(environment=environment) as ctx:
        ctx.eval(js_code)
        result = ctx.eval("generateSign()")
        print(f"Thread {thread_id}: {result}")

threads = []
for i in range(8):
    env = {"navigator": {"userAgent": f"Bot/{i}"}}
    t = threading.Thread(target=run_js, args=(i, env))
    threads.append(t)
    t.start()
for t in threads:
    t.join()
```

实测 8 线程可获得 ~4.7x 加速比。

---

## 七、最佳实践总结

| 场景 | 推荐做法 |
|------|---------|
| 需要执行页面脚本、触发生命周期事件 | 使用 `page.load(snapshot)` |
| 只需 DOM 结构（解析 HTML、提取数据） | 使用 `innerHTML` 赋值 |
| 目标 JS 检测 `MessageChannel` | 用 `wrapNative` 补一个桩实现 |
| 目标 JS 检测 `Function.toString()` | 用 `wrapNative` 伪装为 `[native code]` |
| 需要真实 HTTP 请求 | Python 侧发请求 → `add_resource()` 注入响应 |
| 需要分析目标 JS 访问了哪些 API | 使用 `mode='debug'` + `watch_apis` |
| 需要断点调试 | `with_devtools(port=9229)` + Chrome 打开 `chrome://inspect` |
| 时间敏感（POW、时间差校验） | 使用 `time_mode="system"` |
| 并发执行多个站点脚本 | 多线程，每线程一个 JSContext |
| Context 复用 vs 新建 | 推荐每次新建（~3ms），避免状态污染 |

---

## 八、浏览器 API 覆盖范围

iv8 在 C++ 层实现了以下 Web 标准 API（部分为接口级桩实现）：

| 分类 | 覆盖范围 |
|------|---------|
| DOM & HTML | Document、Element、Node 继承链、70+ HTML 元素、ShadowRoot、MutationObserver、Custom Elements |
| SVG | SVGElement 继承链、50+ SVG 元素接口 |
| CSS & CSSOM | CSSStyleSheet、25+ CSSRule 子类、CSS Typed OM、Highlight API |
| 事件系统 | EventTarget / Event 继承链，80+ 事件类型 |
| Window & Navigator | Window、Location、History、Navigator、Screen、Performance API |
| 网络 | XMLHttpRequest、Fetch API、WebSocket（离线 bundle 模式） |
| 编码 & 文件 | TextEncoder / Decoder、Blob、File、URL / URLSearchParams |
| 存储 | localStorage、sessionStorage、CookieStore、IndexedDB |
| 加密 | crypto.getRandomValues、SubtleCrypto（AES/RSA/ECDH/ECDSA/HMAC 等） |
| Canvas & 图形 | Canvas 2D、WebGL / WebGL2（30+ 扩展）、WebGPU |
| 定时器 | setTimeout / setInterval / requestAnimationFrame / requestIdleCallback |
| Geometry | DOMPoint、DOMRect、DOMQuad、DOMMatrix |
| Performance | PerformanceTiming、PerformanceResourceTiming、PerformanceObserver |

---

## 九、环境探测与 Proxy 代理拦截

iv8 已内置 200+ 浏览器 API，但实战中仍需定位目标 JS 具体检测了哪些环境点。以下是从"发现缺失"到"精准补齐"的完整工作流。

### 9.1 方法一：debug 模式自动监控（推荐）

iv8 的 `mode='debug'` 会自动记录所有浏览器 API 的属性读/写、方法调用，以及 JS 内置反射路径（Object.keys、getOwnPropertyDescriptor、Reflect.ownKeys、Function.prototype.toString 等）：

```python
import iv8

with iv8.JSContext(mode='debug').with_devtools(
    port=9229,
    watch_apis=["navigator.userAgent", "document.cookie", "canvas.toDataURL"],
) as ctx:
    ctx.eval(js_code)
    ctx.eval("__iv8__.eventLoop.sleep(500)")
    # 打开 Chrome，访问 chrome://inspect
    # watch_apis 中的 API 被访问时会自动触发断点
    # Console 面板可查看完整 API 访问链路
```

**适用场景：** 快速定位目标 JS 的环境探测逻辑，无需修改目标代码。

### 9.2 方法二：Proxy 代理器拦截属性访问

和传统 Node.js 补环境中"Proxy 吐环境"思路一致。iv8 运行真实 V8，可以直接使用 JS Proxy：

#### 9.2.1 通用代理工厂 — 记录所有属性访问

```python
import iv8

with iv8.JSContext() as ctx:
    ctx.eval("""
        var __access_log__ = [];

        // 通用代理工厂：递归拦截对象的所有属性读取
        function createProxy(target, name) {
            return new Proxy(target, {
                get(obj, prop) {
                    if (typeof prop === 'string') {
                        __access_log__.push('GET ' + name + '.' + prop);
                    }
                    let value = Reflect.get(obj, prop);
                    // 值是对象则递归代理，实现深层拦截
                    if (value && typeof value === 'object' && !Array.isArray(value)) {
                        return createProxy(value, name + '.' + prop);
                    }
                    return value;
                },
                set(obj, prop, value) {
                    if (typeof prop === 'string') {
                        __access_log__.push('SET ' + name + '.' + prop + ' = ' + JSON.stringify(value));
                    }
                    return Reflect.set(obj, prop, value);
                },
                has(obj, prop) {
                    if (typeof prop === 'string') {
                        __access_log__.push('HAS ' + name + '.' + prop);
                    }
                    return Reflect.has(obj, prop);
                },
                getOwnPropertyDescriptor(obj, prop) {
                    __access_log__.push('DESC ' + name + '.' + prop);
                    return Reflect.getOwnPropertyDescriptor(obj, prop);
                }
            });
        }

        // 对 navigator 做代理
        window.navigator = createProxy(window.navigator, 'navigator');
    """)

    # 执行目标 JS
    ctx.eval(js_code)
    ctx.eval("__iv8__.eventLoop.sleep(500)")

    # 查看访问日志
    logs = ctx.eval("__access_log__", to_py=True)
    for log in logs:
        print(log)
    # GET navigator.userAgent
    # GET navigator.platform
    # GET navigator.languages
    # HAS navigator.webdriver
    # DESC navigator.webdriver
    # ...
```

#### 9.2.2 拦截 window 全局 — 发现缺失的 API

```python
with iv8.JSContext() as ctx:
    ctx.eval("""
        var __missing__ = [];
        var __accessed__ = [];

        var _origWindow = window;
        window = new Proxy(window, {
            get(obj, prop) {
                let value = Reflect.get(obj, prop);
                if (typeof prop === 'string') {
                    if (value === undefined) {
                        __missing__.push('MISSING window.' + prop);
                    } else {
                        __accessed__.push('ACCESS window.' + prop + ' -> ' + typeof value);
                    }
                }
                return value;
            },
            has(obj, prop) {
                if (typeof prop === 'string') {
                    __accessed__.push('HAS window.' + prop + ' -> ' + Reflect.has(obj, prop));
                }
                return Reflect.has(obj, prop);
            }
        });
    """)

    ctx.eval(js_code)
    ctx.eval("__iv8__.eventLoop.sleep(500)")

    # 查看缺失的 API — 这些就是需要补的
    missing = ctx.eval("__missing__", to_py=True)
    print("=== 缺失的 API ===")
    for m in missing:
        print(f"  {m}")

    # 查看已访问的 API（确认 iv8 已覆盖）
    accessed = ctx.eval("__accessed__", to_py=True)
    print(f"\n=== 已覆盖的 API（共 {len(accessed)} 个）===")
    for a in accessed[:20]:
        print(f"  {a}")
```

#### 9.2.3 针对 document 的深度代理

```python
with iv8.JSContext() as ctx:
    ctx.eval("""
        var __doc_log__ = [];

        // 代理 document，记录所有 DOM 操作
        var _origDoc = document;
        document = new Proxy(document, {
            get(obj, prop) {
                if (typeof prop === 'string') {
                    __doc_log__.push('GET document.' + prop);
                }
                let value = Reflect.get(obj, prop);
                // 方法需要绑定原始 this
                if (typeof value === 'function') {
                    return value.bind(obj);
                }
                return value;
            }
        });
    """)

    ctx.eval(js_code)

    doc_logs = ctx.eval("__doc_log__", to_py=True)
    print("document 访问链路:")
    for log in doc_logs:
        print(f"  {log}")
```

#### 9.2.4 拦截特定检测点 — canvas 指纹

```python
with iv8.JSContext() as ctx:
    ctx.eval("""
        var __canvas_log__ = [];

        // 拦截 canvas 相关调用
        var _origGetContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, ...args) {
            __canvas_log__.push('getContext(' + type + ')');
            var ctx = _origGetContext.apply(this, [type, ...args]);
            if (type === '2d' && ctx) {
                return new Proxy(ctx, {
                    get(obj, prop) {
                        let value = Reflect.get(obj, prop);
                        if (typeof value === 'function') {
                            return function(...fnArgs) {
                                __canvas_log__.push('ctx2d.' + prop + '(' + fnArgs.map(a => JSON.stringify(a)).join(',') + ')');
                                return value.apply(obj, fnArgs);
                            };
                        }
                        __canvas_log__.push('GET ctx2d.' + prop);
                        return value;
                    }
                });
            }
            return ctx;
        };

        var _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(...args) {
            __canvas_log__.push('toDataURL(' + args.join(',') + ')');
            return _origToDataURL.apply(this, args);
        };
    """)

    ctx.eval(js_code)
    ctx.eval("__iv8__.eventLoop.sleep(500)")

    canvas_logs = ctx.eval("__canvas_log__", to_py=True)
    print("Canvas 指纹采集链路:")
    for log in canvas_logs:
        print(f"  {log}")
```

### 9.3 方法三：结合 Proxy + wrapNative 动态补环境

发现缺失后，用 Proxy 返回预设值 + wrapNative 伪装：

```python
with iv8.JSContext() as ctx:
    ctx.eval("""
        // 定义需要补的环境映射
        var __patches__ = {
            'SharedArrayBuffer': function SharedArrayBuffer(len) { return new ArrayBuffer(len); },
            'BroadcastChannel': function BroadcastChannel(name) {
                this.name = name;
                this.postMessage = function() {};
                this.close = function() {};
                this.onmessage = null;
            },
            'ReportingObserver': function ReportingObserver(cb, opts) {
                this.observe = function() {};
                this.disconnect = function() {};
                this.takeRecords = function() { return []; };
            },
        };

        // 批量补环境，全部伪装为原生函数
        for (var name in __patches__) {
            window[name] = __iv8__.wrapNative(__patches__[name], name);
        }
    """)

    # 对于属性型的补环境，直接赋值
    ctx.eval("""
        // 补 navigator 下的特殊属性
        Object.defineProperty(navigator, 'connection', {
            get: function() {
                return {
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                };
            },
            configurable: true
        });

        // 补 Notification.permission
        if (window.Notification) {
            Object.defineProperty(Notification, 'permission', {
                get: function() { return 'default'; },
                configurable: true
            });
        }
    """)

    # 现在执行目标 JS
    ctx.eval(js_code)
```

### 9.4 完整实战流程：探测 → 分析 → 补齐

```python
import iv8
import json

def analyze_js(js_code, environment):
    """第一步：探测目标 JS 访问了哪些环境"""
    with iv8.JSContext(environment=environment) as ctx:
        ctx.eval("""
            var __env_report__ = { accessed: [], missing: [], errors: [] };

            window = new Proxy(window, {
                get(obj, prop) {
                    if (typeof prop !== 'string') return Reflect.get(obj, prop);
                    let value;
                    try {
                        value = Reflect.get(obj, prop);
                    } catch(e) {
                        __env_report__.errors.push({prop: prop, error: e.message});
                        return undefined;
                    }
                    if (value === undefined && prop !== 'undefined') {
                        __env_report__.missing.push(prop);
                    } else {
                        __env_report__.accessed.push(prop);
                    }
                    return value;
                }
            });
        """)

        try:
            ctx.eval(js_code)
            ctx.eval("__iv8__.eventLoop.sleep(500)")
        except Exception as e:
            print(f"执行报错: {e}")

        report = ctx.eval("__env_report__", to_py=True)
        return report


def patch_and_run(js_code, environment, patches_js):
    """第二步：补齐环境后正式执行"""
    with iv8.JSContext(environment=environment) as ctx:
        # 注入补丁
        ctx.eval(patches_js)
        # 执行目标 JS
        ctx.eval(js_code)
        ctx.eval("__iv8__.eventLoop.sleep(500)")
        # 获取结果
        return ctx.eval("window._result")


# 使用示例
environment = {
    "location": {"href": "https://target.com/page", ...},
    "navigator": {"userAgent": "..."},
}

# 第一步：分析
report = analyze_js(js_code, environment)
print("缺失的 API:", list(set(report['missing'])))
print("报错:", report['errors'])

# 第二步：根据分析结果编写补丁
patches_js = """
    window.SharedArrayBuffer = __iv8__.wrapNative(
        function SharedArrayBuffer(len) { return new ArrayBuffer(len); },
        'SharedArrayBuffer'
    );
    // ... 其他补丁
"""

# 第三步：正式执行
result = patch_and_run(js_code, environment, patches_js)
print(f"签名结果: {result}")
```

### 9.5 常见需要额外补的环境点

iv8 已内置绝大多数 API，以下是实战中偶尔需要手动补的：

| 检测点 | 补法 |
|--------|------|
| `MessageChannel` | `wrapNative` 补桩实现（见 5.1 案例） |
| `SharedArrayBuffer` | `wrapNative` 包装 ArrayBuffer |
| `navigator.connection` | `Object.defineProperty` 返回预设对象 |
| `PerformanceObserver.supportedEntryTypes` | 直接赋值数组 |
| 特定 `document.createElement` 行为 | Proxy 拦截特定标签名 |
| `window.chrome` / `window.chrome.runtime` | 赋值空对象结构 |
| `Intl.DateTimeFormat().resolvedOptions().timeZone` | `config: {"timezone": "Asia/Shanghai"}` |
| 自定义全局变量（如 `__NEXT_DATA__`） | 直接赋值或通过 `page.load` 的 HTML 注入 |

---

## 十、与传统补环境方案对比

| 维度 | iv8 | Node.js + jsdom | Puppeteer/Playwright |
|------|-----|-----------------|---------------------|
| 启动开销 | ~3ms/Context | ~50ms | ~500ms+ |
| 内存占用 | ~15MB 首次 | ~50MB+ | ~200MB+ |
| 浏览器 API 覆盖 | 200+ 字段 C++ 原生 | 部分，需手动补 | 完整但重 |
| 指纹可控性 | environment 字典一键配置 | 需逐个 mock | 需 CDP 注入 |
| 多线程 | 原生支持，释放 GIL | 不支持 | 多进程 |
| 网络控制 | 完全由用户决定 | 需拦截 | 需 CDP 拦截 |
| 反检测 | `__iv8__` 不可检测 | 容易被检测 | 需 stealth 插件 |
| 可信事件 | isTrusted=true | 不支持 | 支持 |

---

## 十一、常见问题

**Q: iv8 和 Node.js 补环境有什么区别？**

iv8 在 C++ 层原生实现了浏览器 API，不需要手动一个个补 `navigator`、`document` 等对象。传统 Node.js 补环境需要用 JS 模拟这些 API，容易被检测到差异。

**Q: environment 不知道该填什么值？**

调用 `iv8.JSContext.get_defaults()` 查看所有支持的路径和默认值。通常只需覆盖 `location`（目标页面 URL）和 `navigator.userAgent`。

**Q: 目标 JS 报错找不到某个 API？**

1. 使用 `mode='debug'` 查看 API 访问链路
2. 用 `wrapNative` 补一个桩实现
3. 检查是否需要 `page.load` 而非 `innerHTML`

**Q: 如何处理目标 JS 发起的网络请求？**

iv8 社区版不发真实请求。工作流：JS 发起请求 → 查看 `netLog.entries` → Python 侧用 requests/httpx 发真实请求 → `add_resource()` 注入响应 → `eventLoop.drain()` 继续执行。

**Q: 如何处理时间相关的检测？**

使用 `time_mode="system"` 让 `Date.now()` / `performance.now()` 反映真实时间。或在 `logical` 模式下用 `eventLoop.advance()` 精确控制时间推进。

