# 出版商通道矩阵

按下表的 DOI 前缀识别出版商，走对应通道。**排序即优先级**：先试官方 API / 开放 CDN，
再考虑需要交互的通道，最后才是人工。

---

## 速查矩阵

| DOI 前缀 | 出版商 | 首选通道 | 凭证 | 反爬 | 自动化 |
|---|---|---|---|---|---|
| `10.1002` | **Wiley** | 官方 TDM API | TDM token | 走 API，无 | ✅ 完全 |
| `10.1007` `10.1186` | **Springer** | Crossref TDM → `content/pdf` | 无 | 无 | ✅ 完全 |
| `10.1038` | **Nature** | Crossref TDM → `.pdf` | 无 | 无 | ✅ 完全 |
| `10.3390` | **MDPI** | `mdpi-res.com` CDN | 无 | 主站 Akamai，CDN 开放 | ✅ 完全 |
| `10.1016` | **Elsevier** | Article Retrieval API | API key + **全文权益** | 走 API，无 | ⚠️ 需权益 |
| `10.1039` | **RSC** | 无自助通道 | — | Cloudflare | ❌ 人工 |
| `10.1149` | **IOP** | 无自助通道 | — | Cloudflare | ❌ 人工（可邮件走 SFTP） |
| `10.1021` | **ACS** | 无免费通道 | — | Cloudflare | ❌ 人工 |
| `10.1080` | Taylor & Francis | 无自助通道 | — | — | ❌ 人工 |
| `10.1126` | Science/AAAS | 机构 TDM 直下（见其许可协议） | — | — | ⚠️ 看机构协议 |
| `10.1093` | Oxford | 无自助通道 | — | — | ❌ 人工 |

**一句话策略**：`10.1002` / `10.1007` / `10.1186` / `10.1038` / `10.3390` 这五类
（通常占文献综述的一半以上）**完全可以自动化且合规**；剩下的基本要人工。

---

## 逐家说明

### Wiley `10.1002` ✅ 推荐

**Wiley 有官方 TDM API 和官方 Python 客户端**（`wiley-tdm`，MIT 许可）。

- 官方客户端：`pip install wiley-tdm`
- 限速规定：**3 篇/秒**、**60 请求/10 分钟**（长期跑用 **10 秒/篇**）
- 认证：TDM token + **IP 鉴权**
- 内置：限速、跳过已存在文件、断点续传、结果 CSV

**注意**：官方文档明确说明**只支持 IP 鉴权**。SSO-only 的机构账号、或在登记
IP 段外运行（云主机等）都不支持。

### Springer / Nature ✅ 推荐（零凭证）

这两家通过 **Crossref 公开声明了给机器用的 PDF 链接**，**不需要任何凭证**。

- Crossref API 里 `link` 字段中 `intended-application` 含 `text-mining` 的条目
- Springer：`https://link.springer.com/content/pdf/<doi>.pdf`
- Nature：`https://www.nature.com/articles/<doi-suffix>.pdf`

**这是性价比最高的通道**——零凭证、纯 HTTP、无反爬。

### MDPI `10.3390` ✅ 推荐（零凭证）

主站 `www.mdpi.com` 是 **Akamai** 墙（`Access Denied` / `errors.edgesuite.net`），
**连浏览器都拒**。但它的 CDN 完全敞开：

```
https://mdpi-res.com/d_attachment/{slug}/{slug}-{vol}-{art}/article_deploy/{slug}-{vol}-{art}{suffix}.pdf
```

- `slug` = **期刊全名小写**（`materials`、`catalysts`、`molecules`、`energies`…），
  **不是 DOI 前缀**
- `vol` 两位零填充，`art` 五位零填充，**URL 里没有期号**
- `suffix` 依次试 `""`、`-v2`、`-v3`、`-v4`

**常见 bug**：期刊名前缀映射表如果漏了条目就会 404，而 CDN 其实是通的。
已知必补的映射：`ma`→`materials`、`catal`→`catalysts`。

### Elsevier `10.1016` ⚠️ 有条件

官方正路是 **Article Retrieval API**，但需要**全文权益**（受限 API，默认不开通，
需申请，见 `credentials.md`）。

- **TDM 协议 2.2 明文禁止**用 robots/spiders/自动化程序访问其网站 ——
  所以**不要抓 ScienceDirect 网站**
- 网站上自动化访问会撞 CAPTCHA（"Are you a robot?"）
- 摘要 API 是默认开通的，可用来做元数据

**若拿不到全文权益**：让用户手动下（正常个人使用）。

### RSC `10.1039` ❌ 人工

- **没有自助 API**。开发者门户（`developer.rsc.org`）只管 ChemSpider 化学数据，不含期刊全文
- 政策是**个案申请**：*"Arranged on individual request"*
- **须提前至少两周**联系，他们要确认机器访问不影响其他用户
- **供的是 XML，不是 PDF** —— 适合文本挖掘，不适合"我要读这几篇"
- 明文保留 TDM 权利

**因为供 XML 不是 PDF，对"下载 PDF 阅读"这个目的，它其实不合用。**
6 篇以内的量，直接人工下更快。

### IOP `10.1149` ❌ 人工

IOP 政策原文（2026年7月版）：

> *"our IOPscience platform **blocks systematic downloading of content through a variety of
> methods**. Researchers seeking to obtain large amounts of data for AI and/or T&DM are asked
> to contact us (contentsupport@ioppublishing.org). Subject to our review... we may provide the
> requested content via **SFTP** or another agreed method."*
>
> *"IOP Publishing reserves the right to **charge a nominal fee** for supplying data such as
> full-text XML and PDF files"* （XML 元数据免费）

### ACS `10.1021` ❌ 人工

TDM 是**付费商业产品**：*"The cost may vary based on type and breadth of data, duration of
access, frequency, and delivery mechanism."* 需联系销售。

无免费自助通道。

---

## 合规边界（重要）

**这三家的自动化是明确被禁止的，本 skill 不为它们写自动化：**

| 出版商 | 禁止依据 |
|---|---|
| Elsevier | TDM 协议 2.2：禁止 robots/spiders/自动化程序访问其网站 |
| IOP | 明文封锁 systematic downloading，批量走 SFTP |
| RSC | 要求事先联系并获认可 |

**手动下载不在禁止之列**——那是正常的个人使用。
所以正确做法是：生成可点击清单（`make_checklist.py`）交给用户，而不是驱动浏览器批量抓。

**另需注意**：Elsevier 的 TDM 许可在**机构订阅中止时自动终止**，
且要求 TDM 输出带署名声明。学术非商业用途是允许的，商业用途不允许。

---

## 判断"该不该自动化"的决策树

```
这家出版商有没有官方 API / 公开的机器通道？
├─ 有 ──→ 走通道（Wiley TDM / Crossref TDM / MDPI CDN）
│         └─ 需要凭证吗？→ 需要就走 credentials.md 申请（一次性）
└─ 没有
    ├─ 明文禁止自动化？ ──→ 生成人工清单，不写自动化
    └─ 未明文禁止但被反爬拦？──→ 单篇量小：人工清单
                                  批量需求：联系出版商问官方通道
```
