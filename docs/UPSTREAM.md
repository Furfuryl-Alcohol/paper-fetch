# 上游问题报告：scansci-pdf

开发过程中发现 [`scansci-pdf`](https://pypi.org/project/scansci-pdf/)（PyPI 1.17.0）的若干问题，
整理在此以便提给上游。

**本项目不依赖 scansci-pdf**，两者独立。以下仅为回馈社区的记录 ——
如果你在用这个包，可以据此自行打补丁或向上游反馈。

复现环境：Windows 11 / Python 3.12 / patchright 1.63.0 / cloakbrowser 0.5.11 / scansci-pdf 1.17.0。

---

## 1. `browser_engine.py` — 缺 `global` 声明，浏览器链路整体不可用

**严重度：高（崩溃）**

`_check_browser_backend()` 给模块级全局变量赋值，但没有 `global` 声明：

```python
_HAS_BROWSER_BACKEND: bool | None = None

def _check_browser_backend(config=None) -> bool:
    ...
    if _HAS_BROWSER_BACKEND is None:
        _HAS_BROWSER_BACKEND = is_available(BACKEND_PATCHRIGHT)   # ← UnboundLocalError
    return _HAS_BROWSER_BACKEND
```

**触发条件**：`patchright` 可导入时（即装好浏览器后端之后）**必然触发**：

```
UnboundLocalError: cannot access local variable '_HAS_BROWSER_BACKEND'
where it is not associated with a value
```

**影响**：所有走浏览器的通道（出版商直取、机构登录、Cloudflare 挑战）全部失效。

**修复**：函数开头加一行

```python
def _check_browser_backend(config=None) -> bool:
    global _HAS_BROWSER_BACKEND
    ...
```

（临时补丁，`pip install -U` 会被覆盖。）

---

## 2. `pipeline.py` — MDPI CDN 期刊名映射表不完整

**严重度：中（整本刊无法下载）**

`_MDPI_SLUGS` 把 DOI 前缀映射到期刊全名。CDN 的 URL 用的是**期刊全名**，
`www.mdpi.com` 主站则是 Akamai 墙：

```python
_MDPI_SLUGS = {
    "su": "sustainability", "atmos": "atmosphere", "w": "water", ...
}
```

**缺 `"ma": "materials"` 和 `"catal": "catalysts"`**，导致这两本刊构造出的 URL 是

```
https://mdpi-res.com/d_attachment/ma/ma-16-00394/article_deploy/ma-16-00394.pdf   → 404
```

而正确的（实测返回真 PDF）是：

```
https://mdpi-res.com/d_attachment/materials/materials-16-00394/article_deploy/materials-16-00394.pdf   → 200
```

**影响**：Materials、Catalysts 的全部文章下载失败，而 CDN 本身完全可用。
容易被误判成"站点封了"。

---

## 3. `elsevier_check.py` — "OA 对照"探针逻辑导致有效 key 被误判为"无效"

**严重度：中（误导性诊断）**

画像判定逻辑：

```python
oa_ok = verdict_oa == ENTITLED or code_oa == 200
...
elif oa_ok:   profile = "key 有效但无该刊订阅"
else:         profile = "无效 key"
```

但"OA 对照"探针是**不带 key** 发出的（`_head_probe(OA_CONTROL_DOI, "", ...)`），
而 Elsevier 的 API **不带 key 一律返回 406 NO_KEY**。实测如此。

**因此 `oa_ok` 恒为 `False`**，中间那个分支（"key 有效但无该刊订阅"）**永远不可达**。

**后果**：任何"key 有效但缺全文权益"的 key 都会被判为**"无效 key"**，
并且 `elsevier-setup --api-key` **拒绝保存这个本来有效的 key**。

实测：一个 key 在 `content/abstract/doi/...` 上返回 200（证明有效），
但工具报"无效 key"并丢弃它。

**建议**：OA 对照探针应带上 key；或把判定改为基于"全文请求的返回码语义"
（403 `AUTHENTICATION_ERROR` = 有效但无权益，而非无效）。

---

## 4. `_publisher_strategies_core.py` — `_detect_paywall()` 误报，导致放弃可访问的页面

**严重度：中（误导性诊断）**

```python
def _detect_paywall(html: str, status_code: int = 0) -> bool:
    paywall_signals = [
        ...
        "access through your institution", "get access",
        "institutional login", "shibboleth", "openathens",
    ]
    if any(sig in lower for sig in paywall_signals):
        return True
```

`"institutional login"` 和 `"access through your institution"` 几乎出现在
**所有 Wiley / ACS 页面的页眉**（无论你有没有权限）。

**后果**：明明有权限，工具报 `paywall detected` → 放弃下载。
实测一篇有机构权限的 Angew 文章因此被放弃，而改用浏览器 `pdfdirect` + `expect_download`
一次成功。

**建议**：不要把"机构登录入口的存在"当作付费墙信号；
应基于**正文是否真的存在**（Introduction / References / Supporting Information 等）判断。
另：`status_code == 403 and not _is_challenge_page(html)` 也不可靠 ——
Cloudflare 的 403 在 `domcontentloaded` 阶段拿到的 HTML 里可能还没有挑战页特征串。

---

## 附：关于 `browser_auto_upgrade` 的默认行为

`browser_backend.py` 的 `find_local_browser()` 会找**本地比内置内核更新的**
Chrome/Edge 来顶替自带内核（`browser_auto_upgrade` 默认 `True`）。

对 cloakbrowser 后端而言，这会让它的**反检测补丁全部失效**（补丁打在它自带的构建里），
且只在日志里留一行：

```
browser_backend: using local browser ...msedge.exe (kernel (154,0,4258,37)) instead of bundled Chromium
```

**不一定是 bug**（本地新内核也有价值），但**默认值值得商榷**：
用户以为在用反检测浏览器，实际在驱动原版 Edge。

实测结论：原版 Edge 也能过 Cloudflare 的落地页挑战，
所以内置内核的缺失**通常不是** Cloudflare 失败的主因 ——
主因往往是下游的下载代码路径（如用页面内 `fetch()` 取 PDF，那一定会 403）。
