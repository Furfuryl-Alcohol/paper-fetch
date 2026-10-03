# 上游问题报告：scansci-pdf

开发过程中发现 [`scansci-pdf`](https://pypi.org/project/scansci-pdf/) 的若干问题，
整理在此以便提给上游。

- **上游仓库**：<https://github.com/Rimagination/scansci-pdf>
- **提交 issue**：<https://github.com/Rimagination/scansci-pdf/issues>
- **核验日期**：2026-10-03
- **核验版本**：1.17.0（本地安装）vs **1.18.0**（PyPI wheel，逐文件比对）

**本项目不依赖 scansci-pdf**，两者独立。以下仅为回馈社区的记录。

复现环境：Windows 11 / Python 3.12 / patchright 1.63.0 / cloakbrowser 0.5.11。

---

## 状态总览

| # | 问题 | 1.17.0 | 1.18.0 | 状态 |
|---|---|---|---|---|
| 1 | `_check_browser_backend()` 缺 `global` 声明 | ❌ | ✅ | **已修复，无需上报** |
| 2 | `_MDPI_SLUGS` 缺 `ma` / `catal` 映射 | ❌ | ❌ | **待上报** |
| 3 | 「OA 对照」探针恒失败 → 有效 key 被判「无效」 | ❌ | ✅ | **已修复，无需上报** |
| 4 | `_detect_paywall()` 把机构登录入口当付费墙信号 | ❌ | ❌ | **待上报** |
| 5 | 附带配置不完整的 key 会使公开文章从 200 变 403 | — | — | **新发现，可选上报** |

---

## 已修复（仅作记录，不必再报）

### #1 `_check_browser_backend()` 缺 `global` 声明 — 1.18.0 已修

**1.17.0 症状**：`patchright` 可导入时必然抛错，浏览器通道全部失效。

```
UnboundLocalError: cannot access local variable '_HAS_BROWSER_BACKEND'
where it is not associated with a value
```

**1.18.0 状态**：`browser_engine.py:75` 已有 `global _HAS_BROWSER_BACKEND`，问题消失。

### #3 「OA 对照」探针恒失败 — 1.18.0 已修

**1.17.0 症状**：判定画像时「OA 对照」探针**不带 key** 发出，却期望返回 200；
而当时使用的对照 DOI 不带 key 会返回 406 NO_KEY，导致

```python
oa_ok = verdict_oa == ENTITLED or code_oa == 200   # 恒为 False
```

中间分支 `"key 有效但无该刊订阅"` **永远不可达**，任何「有效但无全文权益」的 key
都被判为 **「无效 key」**，且 `elsevier-setup --api-key` **拒绝保存**这个本来有效的 key。

**1.18.0 状态**：对照 DOI 换为 `10.1016/j.jenvman.2023.118901`，
注释标为「无 key 可得的公开对照（实测 200）」。

**实测复核（2026-10-03）**：

```
GET api.elsevier.com/content/article/doi/10.1016/j.jenvman.2023.118901
  不带 key         → HTTP 200（返回全文）  ✅ 对照探针现在能通过
```

该问题对应上游 **#56**（代码注释中已引用），已闭环。

---

## 待上报

### #2 `_MDPI_SLUGS` 缺 `ma` / `catal` 映射

**版本**：1.18.0 仍存在

**问题**：`pipeline.py` 的 `_MDPI_SLUGS` 把 DOI 前缀映射到 MDPI 期刊全名，
CDN 的 URL 用的是**期刊全名**。缺这两个映射导致构造出的 URL 必然 404，
而 `mdpi-res.com` CDN 本身完全开放。

**复现**：

| DOI | 构造出的 URL（404） | 正确的 URL（200，实测返回真 PDF） |
|---|---|---|
| `10.3390/ma16010394` | `.../ma/ma-16-00394/...` | `.../materials/materials-16-00394/...` |
| `10.3390/catal13101336` | `.../catal/catal-13-01336/...` | `.../catalysts/catalysts-13-01336/...` |

```
https://mdpi-res.com/d_attachment/ma/ma-16-00394/article_deploy/ma-16-00394.pdf
  → HTTP 404

https://mdpi-res.com/d_attachment/materials/materials-16-00394/article_deploy/materials-16-00394.pdf
  → HTTP 200, 2,005,594 B, magic b'%PDF-'
```

**修复**：

```python
_MDPI_SLUGS = {
    # ... 现有条目 ...
    "ma": "materials",
    "catal": "catalysts",
}
```

**影响**：Materials 与 Catalysts 两本刊的全部文章无法通过 CDN 车道下载，
且因为主站 `www.mdpi.com` 是 Akamai 墙，用户容易误判为「站点封了」。

---

### #4 `_detect_paywall()` 把机构登录入口当作付费墙信号

**版本**：1.18.0 仍存在

**问题**：信号表包含以下词：

```python
paywall_signals = [
    ...
    "access through your institution", "get access",
    "institutional login", "shibboleth", "openathens",
]
```

其中 `"access through your institution"`、`"institutional login"`、`"shibboleth"`、
`"openathens"` 是**机构登录入口的标识**，出现在几乎每一个 Wiley / ACS 页面的页眉里 ——
**与用户有没有权限无关**。

**后果**：明明有机构订阅权限，工具报 `paywall detected` 并放弃下载。

**实测案例**：一篇有机构权限的 Wiley 文章（Angew，闭源非 OA），
工具报 paywall 后放弃；而同一页面改用浏览器导航到 `pdfdirect` 端点 + `expect_download`
**一次成功**，拿到 3.37 MB 真 PDF。

**建议**：

1. 不要用「机构登录入口是否存在」判断权限。应基于**正文是否真的存在**
   （Introduction / References / Supporting Information 等）判断。
2. 另一个判据 `status_code == 403 and not _is_challenge_page(html)` 也不可靠 ——
   Cloudflare 的 403 在 `domcontentloaded` 阶段拿到的 HTML 里可能还没有挑战页特征串，
   会被误判成付费墙。建议改为轮询等待挑战解除后再判定。

---

### #5 附带配置不完整的 key 会使公开文章从 200 变 403（可选上报）

**问题**：同一个 URL，带 key 反而失败。

**实测**：

```
GET https://api.elsevier.com/content/article/doi/10.1016/j.jenvman.2023.118901

  不带 X-ELS-APIKey  → HTTP 200（返回全文）
  带   X-ELS-APIKey  → HTTP 403 AUTHENTICATION_ERROR
                       "Requestor configuration settings insufficient for access to this resource."
```

**含义**：该 key 被 Elsevier 判定为「非订阅者权限」。一旦附带，Elsevier 就按这个
受限身份处理请求，连本来公开的文章也拒绝。

**对工具的影响**：如果 Elsevier 车道对**所有**请求（含 OA 内容）都附带 key，
可能反而取不到本可获取的公开内容。

**建议**：对公开内容先尝试不带 key 的请求，或用回归方式判断。

---

## 附：`browser_auto_upgrade` 的默认值值得商榷

`browser_backend.py` 的 `find_local_browser()` 会找**本地比内置内核更新的**
Chrome/Edge 来顶替自带内核（`browser_auto_upgrade` 默认 `True`）。

对 cloakbrowser 后端而言，这会让它的**反检测补丁全部失效**（补丁打在自带构建里），
且只在日志里留一行：

```
browser_backend: using local browser ...msedge.exe (kernel (154,0,4258,37)) instead of bundled Chromium
```

**不一定是 bug**（本地新内核也有价值），但默认值值得商榷：
用户以为在用反检测浏览器，实际在驱动原版 Edge。

**补充实测结论**：原版 Edge **也能通过** Cloudflare 的落地页挑战，
所以内置内核的缺失**通常不是** Cloudflare 失败的主因 ——
主因往往是下游的下载代码路径（例如用页面内 `fetch()` 取 PDF，那一定会 403，
因为它是页面发起的子资源请求，Cloudflare 照样拦截，与用户权限无关）。
