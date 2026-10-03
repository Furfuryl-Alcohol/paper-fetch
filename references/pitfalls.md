# 陷阱全表

以下每条都是**实测踩过的**，不是理论推测。按"会浪费多少时间"降序排列。

---

## 一、把"没权限"误判成"被反爬"

**代价：几小时。** 这是最容易犯、最贵的错误。

某工具自带的付费墙检测函数把这些词当付费墙信号：

```python
paywall_signals = [..., "access through your institution", "institutional login", ...]
```

而这两句几乎出现在**所有** Wiley/ACS 页面的页眉。结果是：**明明有权限，却报"paywall"
然后放弃**。实测一篇有权限的 Angew 文章就是这样被误判掉的。

**正确做法**：判断权限要看**正文是否真的存在**（有没有 Introduction、References、
Supporting Information），不要看关键词。

```python
# 好
access_markers = ["supporting information", "full text", "references", "introduction"]
# 坏（会误伤）
bad_markers = ["institutional login", "access through your institution", "sign in"]
```

---

## 二、混淆 Cloudflare 与 Akamai

**代价：1–2 小时。**

两者失败长得像，根因完全不同，处理方式也不同：

| 特征串 | 厂商 | 处理 |
|---|---|---|
| `Just a moment...` / `Checking your browser` / `cf-ray` / `__cf_bm` | Cloudflare | 可用真实浏览器过；或走 API |
| `Access Denied` + `errors.edgesuite.net` + `Reference #18.xxx` | **Akamai** | 该主站大概率封死，**去找它的 CDN** |

实测：`www.mdpi.com` 是 **Akamai**（不是 Cloudflare），连浏览器都拒。
但 `mdpi-res.com` CDN 完全敞开。**把 MDPI 当成 Cloudflare 问题去解决，
会一直找不到方向。**

---

## 三、Cloudflare 的 cookie 绑 TLS 指纹

**代价：30 分钟。**

从浏览器导出 `cf_clearance` 再用 `requests` 带上 —— **照样 403**。
放行 cookie 绑定 TLS 指纹 + UA + IP，Python 的 TLS 指纹对不上。

**要么全程用浏览器，要么走 API，别混用。**

---

## 四、在页面里用 `fetch()` 取 PDF

**代价：反复失败但难查。**

```python
# 一定失败
page.evaluate(f"fetch('{pdf_url}').then(r => r.blob())")
```

这是**页面发起的子资源请求**，Cloudflare 照样拦 —— **与你有没有权限完全无关**。
实测：同一个浏览器会话里，`fetch()` 全 403，而 `page.goto(pdf_url)` + `expect_download`
一次成功。

**正确做法**：

```python
with page.expect_download() as dl:
    try:
        page.goto(pdf_url)      # 抛 "Download is starting" 是正常的
    except Exception:
        pass
dl.value.save_as(path)
```

---

## 五、PDF 端点变体没试全

**代价：以为"下不了"，其实只是 URL 不对。**

- Wiley：`/doi/pdf/<doi>` 只返回 **HTML 阅读器页**；
  `/doi/pdfdirect/<doi>?download=true` 才真正触发下载
- 必须**先访问落地页**建立 Cloudflare 放行状态，再请求 PDF 端点
- 落地页 DOM 里 `a[href*="/pdf"]` 找到的端点可能带 `version` 等 query，**别丢**

---

## 六、无头浏览器被识别

**代价：以为站点封了，其实是自己露了馅。**

症状：UA 里出现 `HeadlessChrome`、返回 CAPTCHA、或页面 `innerText` 极短（几百字节）。

**注意配置项污染**：某些工具里形如 `scihub_browser_headless`、`browser_headless`
的开关会**互相覆盖**，一个通道设了无头，别的通道也被带着变无头。
实测被这个坑过一次：为提速开了某通道的无头，结果所有出版商通道都拿到错误页，
而当时误判成"权限没了"。

**排查**：把渲染后的 `document.body.innerText` 打出来看。
内容只有几百字节且含 `There was a problem` / `Are you a robot?` → 是被识别了，不是没权限。

---

## 七、期刊名前缀映射表不全

**代价：误判"这家下不了"。**

MDPI 的 CDN slug 是**期刊全名**，不是 DOI 前缀。映射表漏条就 404，
而 CDN 本身是通的。已知必补：

```python
"ma": "materials", "catal": "catalysts"
```

**教训**：遇到"整类资源全 404"时，先怀疑**自己构造 URL 的映射表**，
而不是站点封了。

---

## 八、新论文交给灰色源

**代价：白等半小时。**

Sci-Hub 约 **2021 年后停止收录**新文章。对 2023+ 的文献，灰色源命中率接近 0。

实测：39 篇（多为 2023–2026）跑灰色源竞速，5 分钟只出 5 篇，且全是 OA 的。

**判据**：文献年份 > 2022 → 别指望灰色源，直接走官方通道。

---

## 九、默认开着的高代价后台任务

**代价：整个时间预算。**

某些工具默认开启需要下载大体积资源的功能（如内嵌 Tor），而这些资源在受限网络里
**连接超时可达 300 秒且反复重试**。实测一次批量里因此烧掉大量时间。

**动手前检查并关闭**：

- 需要下载二进制的默认功能（Tor、隐形浏览器内核等）
- 竞速的"宽限期"（实测有实现在浏览器源在场时要多等 **180 秒**，CARSI 在场时 **300 秒**）
- 恒定失败的源（如未配邮箱的 Unpaywall）—— 它每次都占一个车道

**大批量前先用单篇试跑并计时**，别直接上 39 篇。

---

## 十、"隐形浏览器"的真相

**代价：2 小时下载 + 无收益。**

很多工具的"反检测浏览器"能力依赖一个**另行下载的内核**（可能数百 MB）。
如果网络慢，下载本身就要很久。

更关键的是：**某些默认配置会静默替换掉它**。实测某实现里
`browser_auto_upgrade=True`（默认）会找本地比自带内核更新的 Chrome/Edge 来顶替 ——
于是反检测补丁**一个都不生效**，而你从日志里才能看出来。

而且实测结论是：**普通浏览器也能过 Cloudflare**（落地页正常加载）。
**真正卡住的是下载代码路径，不是内核。** 所以那几百 MB 通常不必下。

**排查**：看启动日志里报告的实际内核路径。若不是工具自带的那个，说明被替换了。

---

## 十一、凭诊断结论下判断前先直连验证

**代价：拿到错误的结论并据此行动。**

实测两次被工具的"诊断"误导：

1. 报 **"无效 key"** —— 实际 key 完全有效（直连 API 返回 200），
   是工具自己的自检探针逻辑有 bug（它期望 OA 对照探针在**不带 key** 时返回 200，
   但 API 不带 key 一律 406，所以那个分支永远走不到）
2. 报 **"paywall detected"** —— 实际有权限（见第一条）

**做法**：拿到诊断结论后，**用 `curl` 直连原始接口验证一遍**再采信。

```bash
curl -s -D - -H "X-ELS-APIKey: $KEY" -H "Accept: application/json" \
  "https://api.elsevier.com/content/article/doi/<doi>" | head -20
```

**并且**：把"数据"和"解读"分开。给第三方（如出版商支持）提交证据时，
只给原始响应（可复现的 JSON / curl 输出），不要给自己渲染的图片或总结 ——
**自己能画的东西不构成证据；能被对方复现的才构成证据。**

---

## 十二、权限问题的错误归因（IPv4 / IPv6 双栈）

**代价：可能白折腾。**

很多机构同时有教育网和商业 ISP 出口，且 **IPv4 与 IPv6 走不同出口**。
有些 API **只支持 IPv4**（无 AAAA 记录），于是即使你有教育网 IPv6 地址也用不上。

```bash
curl -4 https://api.ipify.org   # 看 IPv4 出口
curl -6 https://api.ipify.org   # 看 IPv6 出口
nslookup -type=AAAA api.example.com   # 看该 API 是否支持 IPv6
```

**重要**：出口 IP 看起来像商业 ISP 段，**不代表机构权限不生效**。
实测某出口是商业 ISP 段，但机构订阅照常生效。
**判断权限要实测（能不能下载），不要靠 IP 归属推测。**

---

## 十三、自己造"证据"

**代价：破坏可信度。**

需要向第三方（出版商、图书馆）证明某个技术问题时：

- ❌ 自己渲染的图片、自己总结的文字 —— **对方无法验证，等于没给**
- ✅ 原始响应体（JSON）、`curl -D -` 的输出、浏览器 Network 导出的 HAR ——
  **对方照着重跑一遍就能复现**

**能被复现，才叫证据。**

---

## 十四、杂项

- **Crossref 限流**：无 `mailto` 时容易 429。加 `mailto` 进礼貌池，并对 429 做退避重试。
- **别信 HTTP 200**：有些站点对无权内容返回 200 + HTML 错误页。
  校验 `%PDF-` magic + 最小体积（如 20 KB）。
- **控制台编码**：中文 Windows 控制台是 GBK，打印含替换字符的输出会
  `UnicodeEncodeError`。脚本里把 stdout 包成 UTF-8：
  ```python
  sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
  ```
- **长路径**：Windows 下超过约 260 字符的路径，`open()` 会 `FileNotFoundError`
  而 `os.listdir`/`glob` 却能看到 —— 加 `\\?\` 前缀，或把工作文件放浅目录。
- **CSV/文本给人看**：用 `utf-8-sig`，否则 Excel 打开中文乱码。
