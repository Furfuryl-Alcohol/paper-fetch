# 凭证申请指南

本文件是**迁移到新设备后的操作手册**。每项凭证给出：入口、前置条件、逐步操作、耗时、常见失败原因。

> **安全铁律**：申请到的令牌只存 `~/.paper-fetch/credentials.json`（权限 600）或环境变量。
> 不要写进脚本、不要提交到仓库、不要截图、不要在对话里完整打印。

---

## 一、Wiley TDM Token

Wiley 有**官方 TDM API**，前面没有 Cloudflare。这是 Wiley 最省事的正路。

### 前置条件

- 一个 **Wiley Online Library (WOL) 账号**（用机构邮箱注册即可，免费）
- 所在机构**已开通 IP 鉴权**（多数订阅机构默认有）
- **请求必须从机构登记的 IP 段内发出**——这是硬性要求

### 申请步骤

1. 注册 / 登录 WOL 账号：<https://onlinelibrary.wiley.com/>
2. 打开 TDM 资源页：
   ```
   https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining
   ```
3. 用 WOL 账号登录后，页面上有获取 **TDM API Token** 的入口，复制那个 **UUID**
   （形如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）
4. 存起来：
   ```bash
   export WILEY_TDM_TOKEN="<uuid>"
   ```

### 耗时

即时。这是自助的，不需要审批。

### 官方客户端的限速规定

- 最多 **3 篇/秒**
- 最多 **60 请求/10 分钟**（即长期跑建议 **10 秒/篇**）
- 客户端默认 5 秒间隔，官方建议长期批量调到 10 秒

### 常见失败

| 报错 | 原因 | 处理 |
|---|---|---|
| `Access Denied`（单篇） | 该刊不在机构订阅内 | 跳过，正常现象 |
| `Access Denied`（全部） | IP 不在机构登记段内 | 见下方「IP 鉴权排查」 |
| token 无效 | 复制时带了空格 / 不是 UUID | 重新复制 |

### IP 鉴权排查

官方文档明确：**只支持 IP 鉴权**。以下情况不支持：

- WOL 机构账号**没有**配置 IP 访问（例如只有 SSO）
- 有配置，但**请求不在登记 IP 段内**（例如在云主机上跑、或走了非机构出口）

排查方法：客户端启动时会打印它检测到的公网 IP，和你浏览器打开
<https://api.ipify.org/?format=json> 看到的对比。两者不同就要找网络管理员。

**机构管理员可以确认访问模型**——如果自助领取的 token 始终 Access Denied，
找图书馆确认机构账号是否配了 IP 访问。

---

## 二、Elsevier API Key

### 前置条件

- 一个 Elsevier 账号（<https://account.elsevier.com/auth>），**务必用机构邮箱注册**
- **在机构网络内完成注册**（权益按 IP 判定）

### 申请步骤

1. 注册 / 登录 Elsevier 账号（用机构邮箱）
2. 打开开发者门户：<https://dev.elsevier.com/>
3. 点 **"I want an API Key"**（或顶部菜单 **"My API Key"**）
4. 登录后点 **"Create API key"**
5. 填 **Label**（标签名，**不要带空格**，如 `lit-review-fetch`）
6. **Website URL** 可空或填占位符
7. 阅读并勾选 **API Service Agreement**，再勾选 **TDM Provisions**
8. 点 **Submit** → 跳到 "My API Key" 页面，**那里就是你的 key**
9. 存起来：
   ```bash
   export ELSEVIER_API_KEY="<key>"
   ```

### 耗时

即时（这一步是自助的）。

### ⚠️ 关键：key ≠ 全文权限

**这是最容易踩的坑。** 拿到 key 之后你会发现：

- `content/abstract/doi/...` → **HTTP 200**（能取摘要和元数据）
- `content/article/doi/...` → **HTTP 403 `AUTHENTICATION_ERROR`**

**这不是配置错误。** 全文检索能力（**ScienceDirect Full-Text Entitlement**）被 Elsevier
列为**受限 API，默认不开通**。

官方原话：

> *access to specialized APIs is **not enabled by default**, as use cases for specialized APIs
> require review from Elsevier's API Support team. **API Support cannot guarantee permission**
> to use access-controlled APIs.*

### 申请全文权益

走 API Support 联系表单（**是网页表单，不是邮件**）：

```
https://www.elsevier.support/dataasaservice/contact
```

表单字段（实测渲染结果）：

| 字段 | 填什么 |
|---|---|
| **Product** | 选 **`ScienceDirect APIs`**（别选成 `ScienceDirect Journals Data`，那是买数据集） |
| **Subject** | 一句话，如 `API key returns 403 on all Article Retrieval requests` |
| **Your question** | 见下方模板 |
| Attachment | 可选 |
| Email | **必须用机构邮箱**（表单明确要求 institutional email） |

**"Your question" 模板**（把三件事写清楚，能省一个来回）：

```
API Key: <你的key>

Institution: <机构全名>

Problem: My API key returns HTTP 403 AUTHENTICATION_ERROR
"Requestor configuration settings insufficient for access to this resource"
on ALL Article Retrieval requests - including a GOLD OPEN ACCESS article
(DOI), which should be retrievable by any valid key.

What I have tested:
- Abstract Retrieval  -> HTTP 200 OK   (key is valid)
- Article Retrieval   -> HTTP 403      (gold OA article)
- Article Retrieval   -> HTTP 403      (regular article)

Raw response body:
{"service-error":{"status":{"statusCode":"AUTHENTICATION_ERROR","statusText":"Requestor configuration settings insufficient for access to this resource."}}}

Response header: X-ELS-Status: AUTHENTICATION_ERROR - ...

Important: the SAME machine / IP address has normal full-text access to these
same articles via the ScienceDirect website, so this does not appear to be a
subscription problem on our side.

Request: Please review the configuration of this API key. It appears to be
scoped to "non-subscriber" access. I would like Article Retrieval enabled for
our institution's subscribed content. Use case: non-commercial academic
research (a systematic literature review).
```

**三个要点必须写进去**，它们把问题从"权益不足"钉死成"key 配置问题"：

1. 连 **gold OA** 都 403 → 排除"没订阅"
2. 同一 IP 在**网站上能看全文** → 排除权益问题
3. 摘要能返 200 → 证明 key 本身有效

### 耗时

**48–72 小时**（对方承诺的响应时间）。且**可能被拒**。

### 备用路线：instToken

如果 API 权益申请不下来，或你的出口 IP 不在机构登记段内，可以要 **instToken**。

**注意：instToken 必须由机构出面申请，个人拿不到。** 官方原文：

> *Insttokens are **only available to customers or partners working on behalf of a customer**. ...
> it represents **full access to a customer account***

两条途径：

1. **机构管理员用 AdminTool 自己生成**（最快）：
   <https://www.elsevier.com/solutions/sciencedirect/support/admin-tool>
2. 若机构没有 AdminTool，向 helpdesk 申请：
   <https://service.elsevier.com/app/contact/supporthub/sciencedirect/>
   需要提供：① 要为哪个服务生成 instToken ② 机构的 **CustomerID**（图书馆/管理员知道）

**给图书馆的说法**：

> 我是本校 XX 学院研究生，做文献综述需要用 Elsevier 的 Research Product APIs 批量获取全文。
> 我的出口 IP 不在学校登记的 IP 段内，所以 API 只能拿到摘要。
> 能否为我的账号生成一个 instToken？（通过 AdminTool，或联系 Elsevier helpdesk 并提供 CustomerID）

**instToken 使用限制**（官方规定）：

- 只能走 **https**
- 只能**服务端保存**，不能出现在浏览器代码或地址栏
- 它代表机构账号的**完整访问权**，Elsevier 可随时撤销
- 必须保管好，别外传

---

## 三、Crossref mailto（最省事）

Crossref 的"礼貌池"（polite pool）要求你声明一个联系邮箱，用于在服务端压力大时优先照顾你。

**不需要申请**，填你自己的邮箱即可：

```bash
export CROSSREF_MAILTO="you@institution.edu"
```

用机构邮箱更规范。这项不是密钥，但填了能显著降低被限流（HTTP 429）的概率。

Crossref TDM 链接是**免费且无私钥**的——很多 publisher（Springer、Nature 等）
通过 Crossref 公开声明了给机器用的 PDF 入口。**这是本 skill 里性价比最高的通道**：
零凭证，纯 HTTP，没有反爬。

---

## 四、机构网络类凭证（CARSI / WebVPN）

校外访问全文用的，**不是 API 凭证**，但是很多机构的唯一合法通道。

### CARSI（教育网联邦认证）

1. 查本校在 CARSI 资源列表里有哪些库：<https://ds.carsi.edu.cn/resourcelist.html>
2. 一般流程：选机构登录 → 选本校 → 输统一身份认证账号密码 → 跳转登录
3. 首次使用要交互式登录一次，之后 cookie 复用

**配置注意**：有些工具要求填**学校英文名**做 IdP 匹配。如果工具内置的中→英映射表
没有你学校，填中文会匹配失败——**要去查该校在 WAYF 页面上的实际显示名**。

### WebVPN

各校入口不同（常见形如 `https://webvpn.<学校域名>`）。
若工具未收录你学校，需要手配 base URL。

**机构网络体检**：很多机构同时有教育网（CERNET）和商业 ISP 双出口，且
**IPv4 和 IPv6 可能走不同出口**。有些出版商的 API 只支持 IPv4——
这时即使你有教育网 IPv6 地址也用不上。排查：

```bash
curl -4 https://api.ipify.org        # IPv4 出口
curl -6 https://api.ipify.org        # IPv6 出口
```

两者归属不同运营商 / 网段时，说明是双栈异构出口，某些通道可能只在其中一条上生效。
