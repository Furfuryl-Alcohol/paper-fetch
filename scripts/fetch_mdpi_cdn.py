#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 mdpi-res.com CDN 下载 MDPI 论文 —— 零凭证、纯 HTTP。

为什么不用主站: www.mdpi.com 是 **Akamai** 墙（Access Denied / errors.edgesuite.net），
连真浏览器都拒。但它的 CDN 完全敞开。

关于期刊名 slug
---------------
CDN 路径用的是**期刊全名**（materials、processes、marinedrugs…），而不是 DOI 前缀
（ma、pr、md）。但**并非所有刊都遵循这个规律** —— 例如 `ijms` 的 slug 就是它自己，
不是 `internationaljournalofmolecularsciences`。

早期版本靠一张手工映射表，结果是**每发现一本新刊就要改一次代码**
（`ma`/`catal` → `pr` → `s`/`md`/`ph` 都是事后补的）。现在改为两级解析：

  1. 静态表 `MDPI_SLUGS` —— 快速路径，覆盖常用刊，不发网络请求
  2. **Crossref 回退** —— 表里没有的前缀，查 Crossref 拿期刊全名再拼 slug
  3. 兜底 —— DOI 前缀本身（许多刊前缀即 slug）

新增的静态条目**必须实测验证过**（CDN 返回真 `%PDF-`）才能加入。
加错了比不加更糟：它会挡住后面两条回退路径。

用法:
    python fetch_mdpi_cdn.py --xlsx 表.xlsx --dest ./papers
    python fetch_mdpi_cdn.py --dois 10.3390/pr13010249 --dest ./papers --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import doi_tag, ensure_dir, get, norm_doi, read_doi_list, valid_pdf  # noqa: E402

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests")
    sys.exit(1)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}

# ---------------------------------------------------------------------------
# 静态映射：DOI 前缀 -> CDN slug
#
# 只放 **前缀 ≠ slug** 的刊。前缀即 slug 的（molecules、toxins、cancers…）
# 靠兜底路径即可，不必列出。
#
# 每条都经过实测（curl 该刊一篇真实论文的 CDN URL，确认返回 %PDF-）。
# 加错条目会挡住 Crossref 回退，比不加更糟。
# ---------------------------------------------------------------------------
MDPI_SLUGS = {
    # —— 实测验证 ——
    "ma": "materials",              # 实测 materials-16-00394
    "catal": "catalysts",           # 实测 catalysts-13-01336
    "pr": "processes",              # 实测 processes-13-00249
    "s": "sensors",                 # 实测 sensors-24-00001
    "md": "marinedrugs",            # 实测 marinedrugs-22-00001
    "ph": "pharmaceuticals",        # 实测 pharmaceuticals-17-00001
    "nano": "nanomaterials",        # 实测 nanomaterials-14-00001
    "e": "entropy",                 # 实测 entropy
    "nu": "nutrients",              # 实测 nutrients
    "sym": "symmetry",              # 实测 symmetry
    "v": "viruses",                 # 实测 viruses
    "fi": "futureinternet",         # 实测 futureinternet
    "rs": "remotesensing",          # 实测 remotesensing

    # —— 沿用早期条目（前缀 ≠ slug，逻辑一致但未逐条重测）——
    "en": "energies",
    "su": "sustainability",
    "polym": "polymers",
    "app": "applsci",
    "w": "water",
    "f": "forests",
    "min": "minerals",
    "atmos": "atmosphere",
    "d": "diversity",
    "a": "algorithms",
    "dj": "dentistry",
    "educsci": "education",
    "applbiosci": "appliedbiosciences",
    "tourhosp": "tourismhosp",

    # —— 恒等映射：纯为可读性保留，可删 ——
    # 注意 ijms 是**特例**：slug 就是缩写，不是全名（实测 ijms-25-00001）
    "ijms": "ijms",
}

_crossref_cache: dict[str, str | None] = {}


def slugify(name: str) -> str:
    """期刊名 -> CDN slug（小写、& -> and、去除非字母数字）。"""
    s = str(name).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", s)


def crossref_slug(doi: str, verbose: bool = False) -> str | None:
    """表里没有前缀时，去 Crossref 查期刊全名并转成 slug。"""
    if doi in _crossref_cache:
        return _crossref_cache[doi]
    mailto = get("crossref_mailto")
    ua = f"paper-fetch/1.0 (mailto:{mailto})" if mailto else "paper-fetch/1.0"
    slug = None
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}",
                         headers={"User-Agent": ua, "Accept": "application/json"},
                         timeout=30)
        if r.status_code == 200:
            names = r.json().get("message", {}).get("container-title") or []
            if names:
                slug = slugify(names[0])
                if verbose:
                    print(f"      [crossref] {names[0]!r} -> slug={slug!r}")
        elif verbose:
            print(f"      [crossref] HTTP {r.status_code}")
    except Exception as e:
        if verbose:
            print(f"      [crossref] 失败: {str(e)[:60]}")
    _crossref_cache[doi] = slug
    return slug


def candidate_slugs(doi: str, verbose: bool = False) -> list[str]:
    """候选 slug，按优先级：静态表 -> Crossref -> DOI 前缀本身。"""
    m = re.match(r"^10\.3390/([a-z]+)\d{6,}$", norm_doi(doi).lower())
    if not m:
        return []
    pref = m.group(1)
    out: list[str] = []
    if pref in MDPI_SLUGS:
        out.append(MDPI_SLUGS[pref])
    else:
        cs = crossref_slug(doi, verbose)
        if cs:
            out.append(cs)
        out.append(pref)          # 兜底：大量刊前缀即 slug
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def mdpi_variants(doi: str, verbose: bool = False) -> list[str]:
    """构造 mdpi-res.com CDN 候选 URL。

    规则: {slug}/{slug}-{vol:02d}-{art:05d}/article_deploy/{base}{suffix}.pdf
      - URL 里没有期号；art 取数字段第 vol+2 位之后（跳过两位期号）
      - 老刊可能一位数卷号，两种拆法都试
      - 后缀依次试 ""、-v2、-v3、-v4
    """
    m = re.match(r"^10\.3390/([a-z]+)(\d{6,})$", norm_doi(doi).lower())
    if not m:
        return []
    digits = m.group(2)
    out: list[str] = []
    for slug in candidate_slugs(doi, verbose):
        for vol_take in (2, 1):
            if len(digits) <= vol_take + 2:
                continue
            vol = str(int(digits[:vol_take])).zfill(2)
            art = str(int(digits[vol_take + 2:])).zfill(5)
            base = f"{slug}-{vol}-{art}"
            for suffix in ("", "-v2", "-v3", "-v4"):
                u = (f"https://mdpi-res.com/d_attachment/{slug}/{base}/"
                     f"article_deploy/{base}{suffix}.pdf")
                if u not in out:
                    out.append(u)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="MDPI CDN 通道下载")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xlsx", help="含 DOI 列的表格")
    src.add_argument("--dois", help="逗号分隔的 DOI")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--verbose", action="store_true", help="打印 slug 解析过程")
    args = ap.parse_args()

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = [d for d in dois if d.lower().startswith("10.3390/")]
    dest = ensure_dir(args.dest)

    print(f"MDPI CDN 通道 · {len(dois)} 篇 → {dest}\n")
    ok = skip = fail = 0
    failed: list[str] = []

    for i, doi in enumerate(dois, 1):
        out = dest / f"{doi_tag(doi)}.pdf"
        if valid_pdf(out):
            print(f"{i:3d}. skip   {doi}")
            skip += 1
            continue

        if args.verbose:
            pref = re.match(r"^10\.3390/([a-z]+)", norm_doi(doi).lower())
            pref = pref.group(1) if pref else "?"
            src_kind = "静态表" if pref in MDPI_SLUGS else "crossref/兜底"
            print(f"{i:3d}. 解析 {doi}   前缀={pref}  来源={src_kind}")

        variants = mdpi_variants(doi, args.verbose)
        if not variants:
            print(f"{i:3d}. FAIL   {doi}   DOI 格式不匹配 10.3390/<letters><digits>")
            failed.append(doi)
            fail += 1
            continue

        got = False
        for u in variants:
            try:
                r = requests.get(u, headers=UA, timeout=60)
                if r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 20000:
                    out.write_bytes(r.content)
                    print(f"{i:3d}. OK     {doi}   {len(r.content):,} B")
                    ok += 1
                    got = True
                    break
                time.sleep(0.15)   # 连续 404 可能招致临时封禁
            except Exception:
                continue
        if not got:
            tried = sorted({u.split("/d_attachment/")[1].split("/")[0] for u in variants})
            print(f"{i:3d}. FAIL   {doi}   候选 slug 均 404: {tried}")
            failed.append(doi)
            fail += 1
        time.sleep(args.sleep)

    print(f"\n成功 {ok} · 跳过 {skip} · 失败 {fail}")

    if failed:
        print("\n失败的 DOI：")
        for d in failed:
            print("   ", d)
        print("""
排查建议：
  1. 用 --verbose 看候选 slug 是什么
  2. 该刊的 slug 可能既不等于前缀也不等于 Crossref 全名。
     取一篇该刊的论文，手工试几个候选 URL，确认后**加进 MDPI_SLUGS**
     （必须实测返回真 %PDF- 才加 —— 加错会挡住回退路径）。""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
