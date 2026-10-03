#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 mdpi-res.com CDN 下载 MDPI 论文 —— 零凭证、纯 HTTP。

为什么不用主站: www.mdpi.com 是 **Akamai** 墙（Access Denied / errors.edgesuite.net），
连真浏览器都拒。但它的 CDN 完全敞开。

用法:
    python fetch_mdpi_cdn.py --xlsx 表.xlsx --dest ./papers
    python fetch_mdpi_cdn.py --dois 10.3390/ma16010394 --dest ./papers
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import doi_tag, ensure_dir, norm_doi, read_doi_list, valid_pdf  # noqa: E402

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests")
    sys.exit(1)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}

# DOI 前缀 → 期刊全名。**这张表漏条就会 404，而 CDN 其实是通的。**
# 遇到"整本刊全 404"时，先来这里补条目，别怀疑站点封了。
MDPI_SLUGS = {
    "ma": "materials",
    "catal": "catalysts",
    "en": "energies",
    "molecules": "molecules",
    "ijms": "ijms",
    "nano": "nanomaterials",
    "chem": "chemistry",
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
    "membranes": "membranes",
    "foods": "foods",
    "sensors": "sensors",
    "pharmaceutics": "pharmaceutics",
    "antibiotics": "antibiotics",
}


def mdpi_variants(doi: str) -> list[str]:
    """构造 mdpi-res.com CDN URL。

    规则: {slug}/{slug}-{vol:02d}-{art:05d}/article_deploy/{base}{suffix}.pdf
      - slug 是**期刊全名**小写，不是 DOI 前缀
      - URL 里没有期号；art 取数字段第 vol+2 位之后
      - 老刊可能一位数卷号，两种拆法都试
    """
    m = re.match(r"^10\.3390/([a-z]+)(\d{6,})$", norm_doi(doi).lower())
    if not m:
        return []
    pref, digits = m.groups()
    slug = MDPI_SLUGS.get(pref, pref)
    out, seen = [], set()
    for vol_take in (2, 1):
        if len(digits) <= vol_take + 2:
            continue
        vol = str(int(digits[:vol_take])).zfill(2)
        art = str(int(digits[vol_take + 2:])).zfill(5)
        base = f"{slug}-{vol}-{art}"
        if base in seen:
            continue
        seen.add(base)
        for suffix in ("", "-v2", "-v3", "-v4"):
            out.append(f"https://mdpi-res.com/d_attachment/{slug}/{base}/"
                       f"article_deploy/{base}{suffix}.pdf")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="MDPI CDN 通道下载")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xlsx", help="含 DOI 列的表格")
    src.add_argument("--dois", help="逗号分隔的 DOI")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = [d for d in dois if d.lower().startswith("10.3390/")]
    dest = ensure_dir(args.dest)

    print(f"MDPI CDN 通道 · {len(dois)} 篇 → {dest}\n")
    ok = skip = fail = 0
    for i, doi in enumerate(dois, 1):
        out = dest / f"{doi_tag(doi)}.pdf"
        if valid_pdf(out):
            print(f"{i:3d}. skip   {doi}")
            skip += 1
            continue

        variants = mdpi_variants(doi)
        if not variants:
            print(f"{i:3d}. FAIL   {doi}  DOI 格式不匹配 10.3390/<letters><digits>")
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
            slug = variants[0].split("/d_attachment/")[1].split("/")[0]
            print(f"{i:3d}. FAIL   {doi}   所有变体 404（slug={slug}）")
            print(f"          若整本刊都失败，去 MDPI_SLUGS 补 "
                  f"'{norm_doi(doi).split('/')[0].replace('10.3390/','')}': '<期刊全名>'")
            fail += 1
        time.sleep(args.sleep)

    print(f"\n成功 {ok} · 跳过 {skip} · 失败 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
