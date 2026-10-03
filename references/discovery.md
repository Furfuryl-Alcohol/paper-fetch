# 探路方法论：遇到没见过的出版商怎么办

`access-matrix.md` 给的是**已知答案**。这份文件给的是**得出答案的方法** ——
遇到一家表里没有的出版商时，按这里的顺序走。

**核心思路：先问"它有没有给机器开的门"，再问"能不能走人走的门"，最后才考虑要不要自己撬。**

---

## 第 0 步：先拿元数据（别急着试 URL）

已知 DOI，先查 Crossref 拿基础事实：

```python
import requests
S = requests.Session()
S.headers.update({"User-Agent": "probe/1.0 (mailto:you@institution.edu)"})

m = S.get(f"https://api.crossref.org/works/{doi}", timeout=30).json()["message"]
journal  = (m.get("container-title") or [""])[0]
publisher = m.get("publisher", "")
issn     = (m.get("ISSN") or [""])[0]
links    = m.get("link", [])          # ← 关键字段，见第 1 步
```

同时查 OA 状态（决定要不要绕开付费墙问题）：

```python
oa = S.get(f"https://api.openalex.org/works/doi:{doi}", timeout=30).json()
status = oa.get("open_access", {}).get("oa_status")     # gold/hybrid/bronze/green/closed
best   = (oa.get("best_oa_location") or {}).get("pdf_url")
```

**为什么要先做这步**：`journal` 和 `publisher` 决定了后面所有分支；
如果 `status` 是 gold/ diamond，往往有免费的官方 PDF 端点，根本不用碰付费墙。

---

## 第 1 步：查有没有"官方机器通道"（按优先级）

### 1a. Crossref 是否声明了 TDM 链接 ⭐ 最高优先

```python
tdm = [l["URL"] for l in links
       if "text-mining" in str(l.get("intended-application", "")).lower()]
```

**这是出版商主动声明的"给机器用"的入口** —— 用它不算绕过。
实测 Springer / Nature / Wiley / Elsevier 都声明了；前两家的链接可以直接纯 HTTP 下载。

> 有些出版商声明的 TDM 链接指向自己的 API（如 Elsevier 指向 `api.elsevier.com`），
> 那就需要凭证，转第 1b 步。

### 1b. 出版商有没有 TDM / API 计划

搜：

```
<出版商名> text and data mining api
<出版商名> TDM policy
<出版商名> developer portal
```

判断标准（**看它给的是什么，别看它说了什么**）：

| 发现 | 含义 |
|---|---|
| 有官方 Python/命令行客户端 | 最好的信号，直接用它 |
| 有 API key 自助申请 | 好，申请后能用 |
| 文档里说 "contact us" / "arranged on individual request" | 需要人工联系，见第 3 步 |
| 出现在"定价 / 销售"页面上 | **是付费商品，个人拿不到** |
| 明确写 "blocks systematic downloading" | **禁止自动化，走人工** |

### 1c. 是否完全 OA

查 DOAJ（`https://doaj.org/api/search/journals/issn:<ISSN>`）或看 OpenAlex 的 `oa_status`。
完全 OA 的刊通常有直接 PDF 端点，值得试。

---

## 第 2 步：实测候选端点（**纯 HTTP 优先**）

**先用 `requests`，不要一上来就开浏览器。** 浏览器慢得多，而且很多站点对浏览器自动化
反而更警惕。

按下面顺序试，命中即停：

```
1. Crossref 声明的 TDM 链接
2. OA 定位服务给的最佳 PDF（OpenAlex best_oa_location.pdf_url）
3. 出版商的常规 PDF 端点（见 recipes.md 的变体表）
4. 该出版商是否有独立的内容 CDN（见下方"找替代主机"）
```

**每次都要校验**（别信 HTTP 200）：

```python
def is_pdf(r):
    return r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 20000
```

> 有些站点对无权内容返回 200 + HTML 错误页。不校验就会存一堆假 PDF。

---

## 第 2.5 步：找替代主机（CDN）—— 很容易被忽略

**同一个出版商的主站和内容分发主机，防护往往完全不同。**
主站被墙死、CDN 完全敞开，是常见格局。

**MDPI 就是典型案例**：

```
www.mdpi.com/.../pdf          → Akamai 墙（Access Denied，连真浏览器都拒）
mdpi-res.com/d_attachment/... → 完全敞开，纯 HTTP 200
```

**怎么发现这类主机**：

- 用真实浏览器打开一篇论文，看 PDF 实际是从哪个域名加载的
  （开发者工具 → Network → 筛 `pdf`，看请求的 Host）
- 搜 `<出版商> CDN` 或看论文页的 `<a href>` 指向哪
- 试 `<出版商>res.com` / `cdn.<域名>` / `<域名>-assets...` 这类命名

**注意**：CDN 路径的构造规则往往不直观（MDPI 用的是**期刊全名**而不是 DOI 前缀，
且 `ijms` 这类缩写刊又是例外）。**必须逐刊实测**，别假设规律。

---

## 第 3 步：查政策 —— 这一步决定"能不能自动化"

**在动手写批量化代码之前**，确认这家出版商是否允许。

搜 `<出版商> text and data mining policy`，找这些关键句：

| 关键句 | 判定 |
|---|---|
| "blocks systematic downloading" | ❌ 禁止批量，改人工 |
| "please contact us beforehand" | ⚠️ 需事先联系，别直接跑 |
| "arranged on individual request" | ⚠️ 同上 |
| "robots, spiders or other automated downloading programs"（禁止语境） | ❌ 禁止自动化访问其网站 |
| "we encourage you to..." / 提供 API | ✅ 允许，走它给的通道 |

**另外要分清"网站"和"API"**：有的出版商允许通过 API 批量，但明令禁止抓网站。
这两件事的合规含义完全不同。

---

## 第 4 步：决策

```
有官方 API / 公开机器入口？
├─ 有 ──→ 用（需凭证就申请，一次性成本）
│         └─ 申请不下来？→ 人工清单
└─ 没有
    ├─ 明文禁止自动化？────→ 人工清单（不要写爬虫）
    ├─ 需事先联系？────────→ 人工清单 + 提示用户可联系
    └─ 未表态但被反爬拦？
        ├─ 量小（< 10 篇）→ 人工清单更划算
        └─ 量大 ──────────→ 联系出版商问官方通道
```

---

## 附 A：失败诊断树

**拿到非 200 时，先判断是哪一类** —— 判错的代价是几小时。

```
拿到响应
├─ 200 但不是 %PDF-        → 多半是 HTML 错误页/阅读器页，看内容判断
├─ 401 / 403
│   ├─ HTML 含 "Just a moment" / "Checking your browser" / cf-ray
│   │                       → Cloudflare。走 API，或真实浏览器过一次
│   ├─ HTML 含 "Access Denied" + "errors.edgesuite.net" + "Reference #18..."
│   │                       → Akamai。**主站大概率封死，去找 CDN**
│   ├─ HTML 含 "Are you a robot?" / captcha
│   │                       → 站点自有机器人防护。自动化难，可考虑人工
│   ├─ JSON 含 AUTHENTICATION_ERROR / NOT_ENTITLED
│   │                       → 凭证/权益问题，不是反爬（见 credentials.md）
│   └─ HTML 含 "Get access" / "Purchase" / "Subscribe"
│                           → 付费墙 = 真没权限，放弃
└─ 404
    ├─ 整本刊都 404         → **先怀疑自己 URL 构造错了**（映射表、卷期号拆法）
    └─ 单篇 404             → 该文可能没有 PDF（early access / 撤稿）
```

**最容易犯的错**：把"付费墙/权益"当成"反爬"，或把"映射表写错"当成"站点封了"。

---

## 附 B：如何用浏览器确认主机的真实地址

需要真浏览器时（**仅用于未被禁止自动化的站点**）：

1. 打开论文落地页
2. F12 → Network → 筛选 `pdf`
3. 点页面上的下载按钮
4. 看那条请求的 **Host** 和完整 URL

拿到真实 URL 后，回第 2 步用 `requests` 重试 —— **很多时候浏览器能看到、requests
也能拿到，只是你之前没找对地址**。

---

## 附 C：判断"slug 规则"的通用做法

CDN 路径里的路径段常常来自期刊名而非 DOI，而且**规则不统一**。
遇到需要构造路径的场景：

1. **别假设规律**。先拿 3–5 篇该刊的论文，手工试几个候选路径
2. 候选顺序：DOI 前缀 → 期刊全名（小写去符号）→ 出版商给的缩写
3. 确认一条能通的之后，**把它降级为"快速路径"，同时保留动态解析兜底**

```python
def candidate_slugs(doi, journal_name):
    pref = doi_prefix(doi)
    out = []
    if pref in STATIC_MAP:            # 快速路径：已验证
        out.append(STATIC_MAP[pref])
    else:
        out.append(slugify(journal_name))   # 动态：查元数据拿到的刊名
        out.append(pref)                    # 兜底：很多刊前缀即 slug
    return dedupe(out)
```

**关键教训**：静态映射表一定会过时（新刊、改名、特例）。
**要么保留动态兜底，要么接受它周期性失效。** 纯静态表是错的架构。
