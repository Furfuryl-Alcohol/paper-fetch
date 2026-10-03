#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 Crossref 的 TDM 链接下载 —— 零凭证、纯 HTTP、无反爬。

适用: Springer (10.1007/10.1186)、Nature (10.1038) 等公开声明了机器入口的出版商。
不适用: Wiley (走官方 TDM API)、Elsevier (走 Article Retrieval API)。

用法:
    python fetch_crossref_tdm.py --xlsx 表.xlsx --dest ./papers
    python fetch_crossref_tdm.py --dois 10.1038/s41929-024-01131-6 --dest ./papers
    python fetch_crossref_tdm.py --xlsx 表.xlsx --dest ./papers --only 10.1038,10.1007
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    doi_tag, ensure_dir, get, norm_doi, publisher_of, read_doi_list, valid_pdf,
)

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests")
    sys.exit(1)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}


def crossref_tdm_links(doi: str, session: requests.Session) -> list[str]:
    """取 Crossref 声明为 text-mining 的链接，带 429 退避。"""
    for attempt in range(4):
        try:
            r = session.get(f"https://api.crossref.org/works/{doi}", timeout=30)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            links = r.json().get("message", {}).get("link", [])
            return [l["URL"] for l in links
                    if "text-mining" in str(l.get("intended-application", "")).lower()]
        except Exception:
            time.sleep(2)
    return []


def try_download(urls: list[str], dest: Path) -> bool:
    for u in urls[:3]:
        try:
            r = requests.get(u, headers=UA, timeout=90, allow_redirects=True)
            if r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 20000:
                dest.write_bytes(r.content)
                return valid_pdf(dest)
        except Exception:
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Crossref TDM 通道下载")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xlsx", help="含 DOI 列的表格（xlsx/csv/txt）")
    src.add_argument("--dois", help="逗号分隔的 DOI")
    ap.add_argument("--dest", required=True, help="输出目录")
    ap.add_argument("--only", default="", help="只处理这些 DOI 前缀，逗号分隔，如 10.1038,10.1007")
    ap.add_argument("--sleep", type=float, default=1.0, help="每篇间隔秒数（默认 1.0）")
    args = ap.parse_args()

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    if args.only:
        prefs = tuple(p.strip() for p in args.only.split(",") if p.strip())
        dois = [d for d in dois if d.startswith(prefs)]

    dest = ensure_dir(args.dest)
    S = requests.Session()
    mailto = get("crossref_mailto")
    S.headers.update({"Accept": "application/json"})
    if mailto:
        S.headers["User-Agent"] = f"paper-fetch/1.0 (mailto:{mailto})"
    else:
        S.headers["User-Agent"] = "paper-fetch/1.0"
        print("[hint] 未配置 crossref_mailto，易被限流。export CROSSREF_MAILTO=you@example.edu")

    print(f"Crossref TDM 通道 · {len(dois)} 篇 → {dest}\n")
    ok = skip = fail = 0
    for i, doi in enumerate(dois, 1):
        out = dest / f"{doi_tag(doi)}.pdf"
        if valid_pdf(out):
            print(f"{i:3d}. skip   {doi}")
            skip += 1
            continue

        links = crossref_tdm_links(doi, S)
        if not links:
            print(f"{i:3d}. --     {doi}   [{publisher_of(doi)}] 无 TDM 链接")
            fail += 1
        elif try_download(links, out):
            print(f"{i:3d}. OK     {doi}   {out.stat().st_size:,} B")
            ok += 1
        else:
            host = links[0].split("/")[2] if links else "?"
            print(f"{i:3d}. FAIL   {doi}   [{publisher_of(doi)}] 链接不可用 ({host})")
            fail += 1
        time.sleep(args.sleep)

    print(f"\n成功 {ok} · 跳过 {skip} · 失败 {fail}")
    print("下一步：python rename_by_meta.py --xlsx <表.xlsx> --dest " + str(dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
