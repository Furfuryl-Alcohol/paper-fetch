# paper-fetch

帮**已经有机构订阅**的研究人员，自动化获取他们**本就有权访问**的文献。

适用于文献综述的资料收集：给一份 DOI 清单（或含 DOI 的 xlsx），把能自动化的部分自动下完，
把不能自动化的部分整理成可点击清单交给你手动处理，最后统一按「期刊名 - 标题」重命名归位。

---

## 设计立场：不对抗反爬

**本工具不去破解 Cloudflare / Akamai。** 它走的是出版商**为批量场景主动开放**的通道：

- 官方 TDM API（Wiley）
- Crossref 公开声明的 text-mining 链接（Springer、Nature 等）
- 开放的内容 CDN（MDPI）

这些通道前面**本来就没有反爬**——它们是设计给机器用的，用它不构成"绕过"。

反爬对抗是猫鼠游戏：今天能过，对方改一次规则就整体失效，而且失败得毫无征兆。
**走官方通道才是可持续的。**

## 不做什么

- ❌ 不绕过付费墙，不内置任何灰色来源（Sci-Hub / LibGen / Sci-Net 等）
- ❌ 不抓取**明文禁止**自动化下载的站点（Elsevier / IOP / RSC / ACS，见下表）
- ❌ 不内置任何凭证 —— 你需要自己申请，见 [`references/credentials.md`](references/credentials.md)

对上面这几家，本工具只生成**可点击的人工下载清单**，不提供自动化。
手动下载是正常个人使用，不在禁止之列。

## 使用前请确认

1. 你所在机构**已订阅**目标内容（没有订阅的话，任何工具都拿不到）
2. 你遵守所在机构与出版商的使用条款
3. **不要把下载的文献再分发**

---

## 各出版商通道一览

| DOI 前缀 | 出版商 | 通道 | 凭证 | 自动化 |
|---|---|---|---|---|
| `10.1002` | Wiley | 官方 TDM API | TDM token | ✅ |
| `10.1007` `10.1186` | Springer | Crossref TDM 链接 | 无 | ✅ |
| `10.1038` | Nature | Crossref TDM 链接 | 无 | ✅ |
| `10.3390` | MDPI | `mdpi-res.com` CDN | 无 | ✅ |
| `10.1016` | Elsevier | Article Retrieval API | key + **全文权益** | ⚠️ 需申请 |
| `10.1039` | RSC | — | — | ❌ 人工 |
| `10.1149` | IOP | — | — | ❌ 人工 |
| `10.1021` | ACS | — | — | ❌ 人工 |

**中间四行（通常占综述清单的一半以上）零凭证即可自动化。**
完整矩阵与各家的禁止依据见 [`references/access-matrix.md`](references/access-matrix.md)。

---

## 快速开始

```bash
git clone <your-repo> && cd paper-fetch
pip install requests                # 唯一必需依赖

# 1. 体检：本机有哪些凭证、哪些通道可用、缺的怎么申请
python scripts/doctor.py
python scripts/doctor.py --guide    # 逐项申请指引（含入口 URL、耗时）

# 2. 配置凭证（见下方「凭证」）
export WILEY_TDM_TOKEN="..."
export CROSSREF_MAILTO="you@institution.edu"

# 3. 盘点清单里还缺哪些，按出版商分组
python scripts/gap_report.py --xlsx papers.xlsx --dest ./papers

# 4. 按出版商跑对应通道
python scripts/fetch_crossref_tdm.py --xlsx papers.xlsx --dest ./papers   # Springer/Nature
python scripts/fetch_mdpi_cdn.py     --xlsx papers.xlsx --dest ./papers   # MDPI
python scripts/fetch_wiley_tdm.py    --xlsx papers.xlsx --dest ./papers   # Wiley

# 5. 无自助通道的生成人工清单
python scripts/make_checklist.py --xlsx papers.xlsx --dest ./papers

# 6. 全部按「期刊名 - 标题」重命名归位（手动下载的也能认出来）
python scripts/rename_by_meta.py --xlsx papers.xlsx --dest ./papers
```

`--xlsx` 也可以是纯文本 DOI 列表。所有脚本 `--help` 有详细说明。

---

## 凭证

**本仓库不含任何密钥。** 所有脚本从外部读取，优先级：

1. 环境变量（推荐）
2. `~/.paper-fetch/credentials.json`

| 键 | 环境变量 | 用途 |
|---|---|---|
| `wiley_tdm_token` | `WILEY_TDM_TOKEN` | Wiley TDM API |
| `elsevier_api_key` | `ELSEVIER_API_KEY` | Elsevier API |
| `crossref_mailto` | `CROSSREF_MAILTO` | Crossref 礼貌池 |

复制 `credentials.example.json` 到 `~/.paper-fetch/credentials.json` 并填写，
或直接用环境变量。**不要提交到仓库。**

### 申请入口速查

| 凭证 | 入口 | 耗时 |
|---|---|---|
| Wiley TDM token | [WOL TDM 页面](https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining)，用 WOL 账号自助领取 | 即时 |
| Crossref mailto | 无需申请，填自己邮箱 | — |
| Elsevier API key | [dev.elsevier.com](https://dev.elsevier.com/) 自助注册 | 即时 |
| **Elsevier 全文权益** | [API Support 表单](https://www.elsevier.support/dataasaservice/contact) | 48–72h，可能被拒 |
| instToken | **找本校图书馆**（AdminTool 生成） | 看图书馆 |

> ⚠️ **Elsevier 的 key 和"全文权益"是两件事。**
> key 是自助的，但全文权益是受限 API、默认不开通，需单独申请。
> 只拿到 key 会看到摘要 200、全文 `403 AUTHENTICATION_ERROR` —— 这不是配置错误。
> 详见 [`references/credentials.md`](references/credentials.md)。

---

## 排障

跑之前先看 [`references/pitfalls.md`](references/pitfalls.md)。最容易踩的几条：

- **别信通用的付费墙检测。** 很多实现把 `institutional login` 当付费墙信号，
  而这词几乎出现在所有 Wiley/ACS 页眉 → "有权限却报 paywall"。
  判断权限要看**正文是否真的存在**。
- **分清 Cloudflare 和 Akamai。** `Just a moment` 是前者，`errors.edgesuite.net` 是后者，
  处理方式完全不同。
- **需要浏览器下载时用 `expect_download`。** 直接导航 PDF 端点会抛
  `Page.goto: Download is starting` —— 这是**正常的**，必须包住。
- **2023 年后的文献别指望灰色源**（本工具也不提供）。

各通道的可运行代码配方见 [`references/recipes.md`](references/recipes.md)。

---

## 作为 Agent Skill 使用

本仓库同时是一个 Agent Skill：`SKILL.md` 带 YAML frontmatter，
可直接放进支持 Agent Skills 的客户端（Claude Code / Cherry Studio 等）的技能目录。

---

## 已知的上游问题

本项目在开发过程中发现 [`scansci-pdf`](https://pypi.org/project/scansci-pdf/) 的若干 bug，
已整理成可供上游修复的报告，见 [`docs/UPSTREAM.md`](docs/UPSTREAM.md)。
**本项目不依赖它**，两者是独立的。

---

## 许可

本项目源代码与文档以 **MIT** 许可发布，见 [LICENSE](LICENSE)。

**范围说明**：上述许可仅覆盖本项目原创的代码与文档。

文档中引用的出版商政策条款、API 文档摘录等，版权归各出版商所有，
此处仅作事实性说明与引用，不因本项目许可而改变其权利归属。

## 免责声明

本工具仅自动化**你已经有权访问**的内容的获取过程。
使用者需自行确保其使用方式符合所在机构与各出版商的使用条款及适用法律。
作者不对因使用本工具产生的任何后果负责。
