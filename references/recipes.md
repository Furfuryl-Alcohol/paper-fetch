# 通道配方（可运行代码）

各通道的核心实现。`scripts/` 下的脚本是这些配方的完整版；本文件保留最小可读版本，
便于排障时单独验证某一条通道。

**通用约定**：落盘文件名统一用 DOI 规范化后的形式（`/` → `_`），便于后续回查。

---

## 1. Crossref TDM 链接（Springer / Nature / 等）

**零凭证、纯 HTTP、无反爬** —— 优先级最高，先跑这个。

```python
import requests

S = requests.Session()
S.headers.update({
    "User-Agent": "paper-fetch/1.0 (mailto:you@institution.edu)",   # 填真实邮箱进礼貌池
    "Accept": "application/json",
})

def crossref_tdm_links(doi: str) -> list[str]:
    """取 Crossref 声明的、给机器用的 PDF 链接。"""
    for attempt in range(4):
        r = S.get(f"https://api.crossref.org/works/{doi}", timeout=30)
        if r.status_code == 429:              # 限流，退避重试
            time.sleep(3 * (attempt + 1)); continue
        if r.status_code != 200:
            return []
        links = r.json()["message"].get("link", [])
        return [l["URL"] for l in links
                if "text-mining" in str(l.get("intended-application", "")).lower()]
    return []
```

**实测覆盖率**：某 39 篇的综述清单里，18 篇声明了 TDM 链接，其中 Springer / Nature
的目标**全部可用**；Elsevier 的 TDM 链接指向 `api.elsevier.com`（仍受权益限制）；
Wiley 的指向 `onlinelibrary.wiley.com/doi/pdf/...`（被 Cloudflare 挡，不如走官方 API）。

**下载时要带浏览器 UA**，否则部分站点会拒：

```python
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
r = requests.get(url, headers=UA, timeout=60, allow_redirects=True)
if r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 20000:
    ...  # 校验通过才落盘
```

> **务必校验** `%PDF-` magic + 最小体积。有些站点对无权内容返回 200 + 一个 HTML 错误页，
> 不校验就会存下一堆假 PDF。

---

## 2. MDPI CDN

```python
import re

_MDPI_SLUGS = {
    # DOI 前缀 → 期刊全名（**必须补全，漏了就 404**）
    "ma": "materials", "catal": "catalysts", "en": "energies",
    "molecules": "molecules", "su": "sustainability", "polym": "polymers",
    "ijms": "ijms", "nano": "nanomaterials", "chem": "chemistry",
    "app": "applsci", "w": "water", "f": "forests", "min": "minerals",
    "atmos": "atmosphere", "d": "diversity", "a": "algorithms", "dj": "dentistry",
}

def mdpi_variants(doi: str) -> list[str]:
    """构造 mdpi-res.com CDN URL。主站是 Akamai 墙，但 CDN 敞开。"""
    m = re.match(r"^10\.3390/([a-z]+)(\d{6,})$", doi.strip().lower())
    if not m:
        return []
    pref, digits = m.groups()
    slug = _MDPI_SLUGS.get(pref, pref)
    out = []
    for vol_take in (2, 1):                  # 老刊可能是一位数卷号，两种拆法都试
        if len(digits) <= vol_take + 2:
            continue
        vol = str(int(digits[:vol_take])).zfill(2)
        art = str(int(digits[vol_take + 2:])).zfill(5)   # 跳过两位期号
        base = f"{slug}-{vol}-{art}"
        for suffix in ("", "-v2", "-v3", "-v4"):
            out.append(f"https://mdpi-res.com/d_attachment/{slug}/{base}/"
                       f"article_deploy/{base}{suffix}.pdf")
    return out
```

**推导示例**：`10.3390/ma16010394` → 前缀 `ma`、数字 `16010394`
→ vol=`16`、art=`00394` → slug=`materials` → `materials-16-00394`

**注意**：`www.mdpi.com/.../pdf` 是 Akamai 墙，**不要用**。

---

## 3. Wiley TDM API

用**官方客户端**，不要自己拼 API。

```bash
pip install wiley-tdm
export WILEY_TDM_TOKEN="<uuid>"
```

```python
import os
from wiley_tdm import TDMClient

tdm = TDMClient(download_dir="papers/")
tdm.api_rate_limit = 10.0        # 官方建议：长期跑 10 秒/篇
results = tdm.download_pdfs(["10.1002/xxx", "10.1002/yyy"])   # 每篇之间自动 sleep

for r in results:
    print(r.status, r.doi, r.path)
```

要点：

- `download_pdfs` 会**逐篇 sleep**；`download_pdf`（单篇）不 sleep
- 默认 `skip_existing_files=True`，文件已存在就跳过（省配额）
- `only_record_errors=True` 可只留失败记录
- `save_results("results.csv")` 导出结果
- **不做 `?download=true` 之类的 URL 花样** —— 这是 API，不是网页

---

## 4. 需要真浏览器时的正确姿势

仅用于**未被禁止自动化**、且没有 API 的站点。三家明文禁止的（Elsevier/RSC/IOP）
请走人工清单，不要用本节。

### 关键：用 `expect_download` 接住下载

很多出版商的 PDF 端点在直接导航时会抛 `Page.goto: Download is starting` ——
**这是正常的**，必须包住：

```python
with page.expect_download(timeout=120000) as dl:
    try:
        page.goto(pdf_url, timeout=120000)
    except Exception:
        pass                      # "Download is starting" 会走到这里，属预期
d = dl.value
print(d.suggested_filename)       # 出版商的原始文件名
d.save_as(out_path)
```

### 关键：先落地页、再取 PDF

Cloudflare 的放行状态是**在访问落地页时建立**的。直接请求 PDF 端点通常 403：

```python
page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=90000)
# 此时放行 cookie 已建立，再取 PDF
```

### 常见 PDF 端点变体（按序试）

| 出版商 | 端点 |
|---|---|
| Wiley | `/doi/pdfdirect/<doi>?download=true` ← 真正触发下载的是这个 |
| Wiley | `/doi/pdf/<doi>` ← 通常只返回 HTML 阅读器页 |
| ACS | `/doi/pdf/<doi>` |
| 通用 | 落地页 DOM 里找 `a[href*="/pdf"]`、`articlepdf`、`pdfdirect` |

### 不要用页面内的 `fetch()`

在页面里执行 `fetch(pdf_url)` 拿 PDF **一定失败**（403）—— 它是页面发起的子资源请求，
Cloudflare 照样拦，**与你有没有权限无关**。要用**导航 + expect_download**。

### 无头 vs 可见

- 无头更容易被识别（UA 里露 `HeadlessChrome`，或返回 CAPTCHA / 空页面）
- 遇到拦截面**先切可见模式**
- **注意配置项污染**：某些工具里形如 `scihub_browser_headless` 的"仅某通道"开关
  会**覆盖全局**无头设置，导致其他通道也变无头

---

## 5. Elsevier Article Retrieval API

```python
import requests

r = requests.get(
    f"https://api.elsevier.com/content/article/doi/{doi}",
    headers={"X-ELS-APIKey": KEY,
             "Accept": "application/json"},     # 或 text/xml
    timeout=45,
)
# 200 → 拿到全文
# 403 AUTHENTICATION_ERROR → key 无全文权益（见 credentials.md）
# 200 但只有摘要 → 未订阅该刊
```

**没有全文权益时**：

- `content/abstract/doi/...` 仍可用来做元数据（默认开通）
- 全文请让用户手动下，**不要抓网站**（违反 TDM 协议 2.2）

**诊断技巧**：拿一篇 **gold OA** 的文章测。OA 内容本该任何有效 key 都能取；
若连它也 403，说明是 **key 的能力范围**问题，不是订阅问题。这一条能帮你
在给支持方写信时把问题钉死。

---

## 6. 落盘与命名

**统一用 DOI 规范化文件名**，后续才能回查：

```python
import re
def doi_tag(doi: str) -> str:
    return re.sub(r"[^a-z0-9.]", "_", doi.lower())
# 10.1002/anie.202512175 → 10.1002_anie.202512175
```

最后用 `rename_by_meta.py` 按 DOI 回查表格，改成「期刊名 - 标题.pdf」。

**校验每一步**（别信 HTTP 200）：

```python
def valid_pdf(path) -> bool:
    try:
        p = open(path, "rb")
        return p.read(5) == b"%PDF-" and os.path.getsize(path) > 20000
    except Exception:
        return False
```
