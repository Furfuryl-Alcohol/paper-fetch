---
name: paper-fetch
description: >
  自动化获取学术论文 PDF —— 按出版商走各自「官方许可」的通道（TDM API / Crossref TDM 链接 /
  开放 CDN），而不是对抗反爬。当用户要批量下载论文、给了 DOI 列表或含 DOI 的表格（xlsx/csv/
  WoS 导出）、要做文献综述的资料收集、要从 Zotero/EndNote/文献列表批量取全文、要配置
  Wiley TDM token 或 Elsevier API key、遇到下载被 Cloudflare/Akamai 拦、或说
  「下载论文」「批量下载文献」「获取全文」「文献综述资料」「抓 PDF」「DOI 下载」时，使用本 skill。
  即使用户只说「帮我把这些文献下下来」而没提任何工具名，也应使用本 skill。
  SKIP：用户只是讨论论文内容、翻译论文、或做文献综述的写作（不涉及获取原文文件）。
version: 1.0.0
---

# paper-fetch — 学术论文自动化获取

## 核心原则（先读这段，它决定后面所有选择）

**不要对抗反爬，去走出版商自己开的通道。**

Cloudflare / Akamai 的检测是持续演进的。任何"绕过"技巧都会在对方改规则的那天整体失效，
且失败得毫无征兆。而**出版商为批量场景提供的官方通道（TDM API、Crossref TDM 链接、开放 CDN）
前面根本没有反爬**——它们是设计给机器用的。

所以本 skill 的默认路径永远是：**先查这家出版商有没有官方机器通道，有就走，没有就如实报告并交给用户手动。**

### 第二原则：分清"反爬"和"权限"

这两种失败长得像，根因完全不同，混淆会浪费大量时间：

| 现象 | 真实原因 | 处理 |
|---|---|---|
| `403 Just a moment` / `Checking your browser` | 反爬（Cloudflare Turnstile） | 换官方通道；或真实浏览器过一次挑战 |
| `403 Access Denied` + `errors.edgesuite.net` | **Akamai**（不是 Cloudflare） | 该站主站被封，查它的 CDN 是否开放 |
| `You do not have access` / `Get access` | 权限（机构未订阅该刊） | 无解，跳过 |
| `AUTHENTICATION_ERROR` / `NOT_ENTITLED` | 凭证权益不足 | 查 API 权益配置，不是反爬问题 |

**动手前先判断是哪一类。** 判错的代价是：把"没订阅"当成"被反爬拦"，
然后花几个小时对抗一个根本不存在的对手。

### 第三原则：合规边界

有些出版商**明文禁止**自动化下载。对它们，本 skill 只提供人工清单，不写自动化：

- **Elsevier** — TDM 协议 2.2 禁止用 robots/spiders/自动化程序访问其网站；正路是 API
- **IOP** — 明文封锁 systematic downloading，批量需求走 `contentsupport@ioppublishing.org` → SFTP
- **RSC** — 要求事先联系，供的是 XML 不是 PDF；明文保留 TDM 权利
- **ACS** — TDM 是付费商品，无免费自助通道

**手动下载是正常个人使用，不在禁止之列。** 所以对这些出版商，正确做法是
生成「点击清单」交给用户，而不是驱动浏览器批量抓。

---

## 工作流

### 第 0 步：体检（每次都先做）

```bash
python scripts/doctor.py
```

它会报告：本机有哪些凭证可用、哪些通道因此打开、以及缺的凭证去哪里申请。
**先跑这个再决定策略**，否则会按不存在的通道规划。

### 第 1 步：确认清单来源

用户可能给：DOI 列表 / xlsx（WoS 导出）/ BibTeX / 一个文件夹里的半成品。

```bash
python scripts/gap_report.py --xlsx <表.xlsx> --dest <目标目录>
```

输出：已完成 N 篇、还缺哪些、**按出版商分组**。这一步决定后面走哪几条通道。

### 第 2 步：按出版商分发到对应通道

见 `references/access-matrix.md`（完整矩阵）。速查：

| 出版商 | 通道 | 凭证 | 脚本 |
|---|---|---|---|
| Wiley `10.1002` | 官方 TDM API | TDM token | `fetch_wiley_tdm.py` |
| Springer `10.1007` `10.1186` | Crossref TDM → content/pdf | 无 | `fetch_crossref_tdm.py` |
| Nature `10.1038` | Crossref TDM → .pdf | 无 | `fetch_crossref_tdm.py` |
| MDPI `10.3390` | mdpi-res.com CDN | 无 | `fetch_mdpi_cdn.py` |
| Elsevier `10.1016` | Article Retrieval API | API key + 权益 | `fetch_elsevier_api.py` |
| RSC `10.1039` / IOP `10.1149` / ACS `10.1021` | **无官方自助通道** | — | 人工清单 |

**并行建议**：无凭证的通道（Springer/Nature/MDPI）可以立即跑；
需要凭证的（Wiley/Elsevier）先跑 `doctor.py` 确认凭证在不在。

> **表里没有的出版商怎么办？** 别猜，也别直接开浏览器硬试 ——
> 按 `references/discovery.md` 的方法论走：
> 先用 Crossref 拿元数据（期刊名 / 出版商 / OA 状态 / 有无 TDM 链接），
> 再按"官方 API → 公开机器入口 → 开放 CDN → 人工"的顺序探。
> 那份文件还给了失败诊断树（分清 Cloudflare / Akamai / 付费墙 / 权益）。

### 第 3 步：下载

各脚本用法见 `references/recipes.md`。共同约定：

- **落盘文件名统一用 DOI**（`10.1002_anie.202512175.pdf`），便于回查
- **按出版商分组跑**，不要把不同出版商的混在一批
- **慢速**：Wiley 官方上限是 60 请求/10 分钟（约 10 秒/篇）。**慢是特性不是缺陷**——
  慢速恰恰是长期不被封的关键
- 失败的**记录并继续**，绝不中断整批

### 第 4 步：重命名归位

```bash
python scripts/rename_by_meta.py --xlsx <表.xlsx> --dest <目标目录>
```

按 DOI 回查表格，重命名为「期刊名 - 标题.pdf」。**认不出的单独列出，绝不误删。**

### 第 5 步：剩余部分交给用户

对无官方通道的出版商，生成可点击清单：

```bash
python scripts/make_checklist.py --xlsx <表.xlsx> --dest <目标目录>
```

产出 `待下载清单.html`（点标题直接跳文章页）+ `.txt`。用户手动下完丢回同一目录，
再跑一次第 4 步即可归位。

---

## 凭证管理（迁移到新设备时看这里）

### 铁律

1. **绝不把令牌写进 skill 文件、脚本、或任何会被打包分发的地方。**
   本 skill 的所有脚本都从外部读取凭证，仓库里只有 `credentials.example.json` 占位模板。
2. **绝不把令牌打印到输出、日志、或截图里。** 传给支持方时只给前 4 位 + 后 4 位。
3. **不要在每个项目里重复填。** 凭证放一处，所有脚本共用。

### 存放位置（按优先级）

```
1. 环境变量                        ← 推荐，最安全
2. ~/.paper-fetch/credentials.json ← 次选，权限设 600
```

支持的键：

| 键 | 环境变量 | 用途 |
|---|---|---|
| `wiley_tdm_token` | `WILEY_TDM_TOKEN` | Wiley TDM API（UUID） |
| `elsevier_api_key` | `ELSEVIER_API_KEY` | Elsevier Article Retrieval API |
| `crossref_mailto` | `CROSSREF_MAILTO` | Crossref 礼貌池（填真实邮箱，非密钥） |

### 各项凭证怎么申请

**完整步骤见 `references/credentials.md`**（含每个申请的入口 URL、要填什么、审批时长、常见被拒原因）。

速查：

| 凭证 | 入口 | 时长 | 难度 |
|---|---|---|---|
| Wiley TDM token | WOL 的 TDM 页面，用 WOL 账号自助领取 | 即时 | 易 |
| Elsevier API key | dev.elsevier.com 自助注册 | 即时 | 易 |
| Elsevier 全文**权益** | API Support 表单申请 | 48–72h | 中，可能被拒 |
| instToken | **找本校图书馆**（AdminTool 生成） | 看图书馆 | 中 |
| Crossref mailto | 无申请，填自己邮箱即可 | — | 极易 |

**重要**：Elsevier 的 API key 和"全文权益"是两件事。key 是自助的，
但**全文权益是受限 API，默认不开通**，需要单独申请。只拿到 key 会看到
摘要能取、全文 `403 AUTHENTICATION_ERROR`——**这不是配置错误，是权益没开。**

### 新设备上手指引

```bash
python scripts/doctor.py --guide      # 打印逐项申请指引
```

---

## 常见陷阱

**完整清单见 `references/pitfalls.md`。** 最容易踩的几个：

1. **别信通用的付费墙检测函数。** 很多实现把 `institutional login`、
   `access through your institution` 当付费墙信号，而这两个词几乎出现在所有
   Wiley/ACS 页面的页眉 —— 结果是"明明有权限却报付费墙"，然后放弃。
   要判断权限，看**正文是否真的存在**，不要看关键词。

2. **Cloudflare 的放行 cookie 绑 TLS 指纹。** 用 `requests` 带着浏览器导出的
   `cf_clearance` 请求照样 403。**要么全程用浏览器，要么走 API，别混用。**

3. **需要浏览器下载时，用 `expect_download` 接。**
   很多出版商的 PDF 端点在直接导航时会抛 `Page.goto: Download is starting` ——
   **这是正常的**，必须用 `page.expect_download()` 包住 `goto` 才能拿到文件。
   另外常见的是：普通 `/pdf/...` 只返回 HTML 阅读器页，要加 `?download=true` /
   用 `pdfdirect` 变体才真正触发下载。

4. **无头浏览器更容易被识别。** 遇到 CAPTCHA / 空页面 / `HeadlessChrome` in UA，
   先切可见模式。另外注意有些工具里 `scihub_browser_headless` 这类"仅某通道"的开关
   会**覆盖全局**的无头设置。

5. **MDPI 不是 Cloudflare，是 Akamai。** 主站 `www.mdpi.com` 被墙死，
   但 `mdpi-res.com` CDN 敞开。见 `recipes.md` 的 URL 构造规则
   （注意 slug 是**期刊全名**，不是 DOI 前缀——`ma`→`materials`、`catal`→`catalysts`
   这类映射漏了就会 404，而 CDN 其实是通的）。

6. **新论文灰色源基本没用。** Sci-Hub 约 2021 年后停止收录。
   对 2023+ 的文献，别在灰色源上浪费时间。

---

## 参考文件

| 文件 | 内容 |
|---|---|
| `references/access-matrix.md` | 各出版商通道矩阵、限制、合规边界（**已知答案**） |
| `references/discovery.md` | **探路方法论**：遇到没见过的出版商，按什么顺序查（**得出答案的方法**） |
| `references/credentials.md` | 每项凭证的完整申请流程 |
| `references/recipes.md` | 各通道的可运行代码配方 |
| `references/pitfalls.md` | 陷阱全表（含本 skill 形成过程中的实测记录） |

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/doctor.py` | 体检：本机凭证与可用通道 |
| `scripts/gap_report.py` | 缺口盘点：还缺哪些、按出版商分组 |
| `scripts/fetch_wiley_tdm.py` | Wiley 官方 TDM API |
| `scripts/fetch_crossref_tdm.py` | Crossref TDM 链接（Springer/Nature 等） |
| `scripts/fetch_mdpi_cdn.py` | MDPI CDN |
| `scripts/fetch_elsevier_api.py` | Elsevier Article Retrieval API |
| `scripts/rename_by_meta.py` | 按 DOI 回查表格批量重命名 |
| `scripts/make_checklist.py` | 生成人工下载清单（HTML + TXT） |
| `scripts/_common.py` | 共用：凭证读取、路径、DOI 规范化 |

所有脚本均为纯 Python 3.10+，无第三方依赖（除 `requests`），Windows / macOS / Linux 通用。
