# iv8 站点脚本示例

在 iv8 基础上自实现的站点反爬脚本(cookie 生成 / 接口请求)。通用签名类示例见 iv8 上游仓库(文末链接)。

## 通过状态

| 脚本 | 站点 | 防护 | 状态 | 说明 |
|---|---|---|---|---|
| `cvs.py` / `cvs_2.py` / `cvs_home.py` | cvs.com | Akamai | ✅ 通过 | httpcloak `chrome-146` 指纹直接 GET 即出真实页 + Akamai cookie，无需 iv8/sensor |
| `argos.py` | argos.co.uk | Akamai | ✅ 通过 | httpcloak 直连 → 真实页 + `_abck` |
| `samsclub_px_example.py` | samsclub.com | PerimeterX | ✅ 通过 | 独立示例：iv8 铸 `_px3`/`_pxvid`/`pxcts`/`_pxde` + 调 `products/search`；请求库 httpcloak(`chrome-146-windows`)。`px_init.js`(PX sensor)运行时自动下载 |
| `chewy.py` | chewy.com | Kasada | ⚠️ 部分 | httpcloak(`chrome-146-windows`，与 iv8 环境 UA / sec-ch-ua 版本对齐)。iv8 产出 `/tl` + `KP_UIDz-ssn` + `x-kpsdk-ct`；重试仍 429(Kasada 多轮再挑战）。含 `DataTransfer.files` shim 修 iv8 0.1.4 teardown 崩溃 |
| `very.py` | very.co.uk | Akamai v3 | ⚠️ 受 IP 阻 | iv8 生成 sensor_data POST（接受 200）但 `_abck` 停 `~-1~`；需干净 IP |
| `bjs.py` | bjs.com | Akamai v3 | ❌ 不通过 | iv8 生成的 v3 sensor 无效，`_abck` 始终 `~-1~` |
| `lowes_product.py` / `lowes_search.py` | lowes.com | Akamai | ❌ 不通过 | iv8 跑完仍返回挑战页 / teardown 崩溃 |
| `ebay.py` | ebay.com | Akamai | ❌ 不通过 | 初始 403 |
| `bol_product.py` | bol.com | Akamai sbsd | ❌ 不通过 | 初始 403；`sbsd` 为一次性 PoW，回放不可行 |
| `fnac.py` | fnac.com | Queue-it | ❌ 不通过 | 初始 403 + 流程报错 |

图例：✅ 通过 · ⚠️ 部分/受环境阻 · ❌ 不通过

## CVS 特性（最省）

CVS 是唯一「指纹对 = 访问即得」的站点：

- **不需要 iv8、不需要代理、不挑地区** —— httpcloak `chrome-146` 指纹直接 GET 即返回真实页 + Akamai cookie。
- `_abck` 停在 `~-1~` 也正常，判断成功看页面是否真实内容（几 MB、含 CVS/商品），不看状态位。
- cookie 寿命瓶颈 `bm_ss≈1h` / `bm_sz≈4h`（`_abck` 名义 1 年是假象）。
- 唯一前提：客户端能伪造 Chrome TLS 指纹（httpcloak / curl_cffi impersonate）。

## 请求库与指纹一致性

反爬脚本用 iv8 + httpcloak 时，**httpcloak preset 的 Chrome 版本必须与 iv8 环境的 UA / sec-ch-ua 版本一致**（如全部 chrome-146），否则 TLS 指纹与 JS 环境版本不一致会被判异常。经验：PerimeterX 吃 httpcloak 更真的 TLS（samsclub 出值）；Kasada / Akamai-IP 封需多轮 solve 或住宅 IP。

## iv8 0.1.4 通用补丁

- **`document.readyState` 钉死为 `"complete"`**：`<head>` 脚本在 body 未解析时按 readyState 分支会崩（`null.classList`）。修法：注入 `Object.defineProperty(document,'readyState',{get:()=>document.body?'complete':'loading'})`。
- **`DataTransfer.files` / FileList 未实现**：访问会抛 C++ 异常并在 JSContext 销毁时使进程崩溃（exit 127）。修法：`Object.defineProperty(DataTransfer.prototype,'files',{get:()=>[]})`。

## 上游原生 examples

以下为 iv8 社区版自带示例，见 <https://github.com/HanZzzzz000/iv8/tree/main/examples>：

- [`abogus.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/abogus.py) — 抖音 `a_bogus`
- [`h5st.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/h5st.py) — 京东 `h5st`
- [`tdc.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/tdc.py) — 腾讯验证码 POW
