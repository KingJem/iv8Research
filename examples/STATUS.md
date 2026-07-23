# iv8 自实现站点脚本 — 通过状态

这些是在 iv8（HanZzzzz000/iv8）社区版基础上**自己实现**的站点反爬脚本，从原 `KingJem/iv8` 仓库迁移至此。
中国站点 / 通用签名类 examples 未收录 —— 它们是 iv8 上游原生示例，见文末链接。

## 测试环境说明

- 引擎：**iv8 0.1.4**（py310：`C:/Users/YanchuangJin/miniforge3/envs/py310/python.exe`，含 `iv8` + `curl_cffi` + `httpcloak`）
- 运行：`PYTHONIOENCODING=utf-8 <py310> examples/<script>.py`
- **出口 IP：本机中国直连（无干净/属地代理）。** 西方电商反爬（Akamai/Kasada/Queue-it）对数据中心/异地 IP 普遍硬封，下表 ❌ 多为 **IP/环境所致，非脚本逻辑错误**。干净/属地 IP 下结果可能不同。

## 状态（每个脚本跑一遍，2026-07-23）

| 脚本 | 站点 | 防护 | 状态 | 说明 |
|---|---|---|---|---|
| `cvs.py` / `cvs_2.py` / `cvs_home.py` | cvs.com | Akamai | ✅ 通过 | httpcloak `chrome-146` 指纹直连即出真实页（3.9MB/14MB）+ 全套 Akamai cookie；无需 iv8 sensor |
| `argos.py` | argos.co.uk | Akamai | ✅ 通过 | httpcloak 直连 → 200 / 513KB 真实页 + `_abck` |
| `chewy.py` | chewy.com | Kasada | ⚠️ 部分 | iv8 0.1.4 成功执行 ips.js 产出 `/tl` 负载 + `KP_UIDz-ssn`（核心通过）；但重试仍 429（Kasada 多轮/IP）。含 `DataTransfer.files` shim 修复 iv8 0.1.4 teardown 崩溃 |
| `very.py` | very.co.uk | Akamai v3 | ⚠️ 受 IP 阻 | iv8 0.1.4 能生成 sensor_data POST（接受 200），但所有数据中心 IP（含 172.121 全段）被 `403 Access Denied` 硬封，`_abck` 停 `~-1~`；干净 IP 直连即出真实页。详见根目录 `retry_very_iv8_chrome.py` |
| `bjs.py` | bjs.com | Akamai v3 | ❌ 不通过 | iv8 生成的 v3 sensor 无效，`_abck` 始终 `~-1~`，页面仍挑战 |
| `lowes_product.py` / `lowes_search.py` | lowes.com | Akamai | ❌ 不通过 | iv8 跑完仍返回 ~2.5KB 挑战页 / teardown 崩溃（CN IP） |
| `ebay.py` | ebay.com | Akamai | ❌ 不通过 | 初始 403（CN IP） |
| `bol_product.py` | bol.com | Akamai sbsd | ❌ 不通过 | 初始 403；`sbsd` 为一次性 PoW，curl_cffi 回放不可行 |
| `fnac.py` | fnac.com | Queue-it | ❌ 不通过 | 初始 403 + 流程报错 |
| `lary.py` | zhipin.com | `__zp_stoken__` | ⏭ 未测 | 中国站点变体，参见上游 `zp_stoken.py` |
| `yaojianju.py` | nmpa.gov.cn | 参数签名 | ⏭ 未测 | 中国站点变体（`browserforge` 依赖报错），参见上游 `药监局.py` |

图例：✅ 通过 · ⚠️ 部分/受环境阻 · ❌ 不通过 · ⏭ 未测

## iv8 0.1.4 通用补丁（本轮踩坑）

- **`document.readyState` 钉死为 `"complete"`**：页面 `<head>` 脚本在 body 未解析时按 readyState 分支会崩（`null.classList`）。修法：注入 `Object.defineProperty(document,'readyState',{get:()=>document.body?'complete':'loading'})`。
- **`DataTransfer.files` / FileList 未实现**：访问会抛 C++ 异常并在 JSContext 销毁时使进程崩溃（exit 127）。修法：`Object.defineProperty(DataTransfer.prototype,'files',{get:()=>[]})`。

## 上游原生 examples（未迁移，指向 iv8 原仓库）

以下为 iv8 社区版自带示例，见 **<https://github.com/HanZzzzz000/iv8/tree/main/examples>**：

- [`abogus.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/abogus.py) — 抖音 `a_bogus`
- [`h5st.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/h5st.py) — 京东 `h5st`
- [`tdc.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/tdc.py) — 腾讯验证码 POW
- [`zp_stoken.py`](https://github.com/HanZzzzz000/iv8/blob/main/examples/zp_stoken.py) — BOSS直聘 `__zp_stoken__`
- 欧冶 / 海关 / 税务 / 药监局 — 中国政企数据 API（iv8 算签名/参数）
