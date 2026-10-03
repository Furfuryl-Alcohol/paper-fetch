#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺口盘点：清单里还有哪些没下到，按出版商分组。

匹配方式（两种都认）:
  1. DOI 规范化文件名: 10.1002_anie.202512175.pdf
  2. 已重命名文件:     <期刊名> - <标题>.pdf   （按标题前 60 字符匹配）

用法:
    python gap_report.py --xlsx 表.xlsx --dest ./papers
    python gap_report.py --xlsx 表.xlsx --dest ./papers --list     # 列出缺失明细
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import doi_tag, norm_doi, publisher_of, read_doi_list, safe_filename, valid_pdf  # noqa: E402


def load_titles(xlsx: Path) -> dict[str, tuple[str, str]]:
    """DOI → (期刊名, 标题)。"""
    import pandas as pd
    df = pd.read_excel(xlsx, header=0)
    cols = {str(c).strip().lower(): c for c in df.columns}

    doi_col = cols.get("doi")
    if doi_col is None:
        raise ValueError(f"表格里找不到 DOI 列。实际列：{list(df.columns)[:12]}")

    title_col = next((cols[k] for k in ("article title", "title", "标题") if k in cols), None)
    src_col = next((cols[k] for k in ("source title", "journal", "期刊", "来源出版物")
                    if k in cols), None)

    out = {}
    for _, r in df.iterrows():
        d = norm_doi(str(r[doi_col]))
        if not d:
            continue
        out[d] = (str(r[src_col]).strip() if src_col else "",
                  str(r[title_col]).strip() if title_col else "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="缺口盘点")
    ap.add_argument("--xlsx", required=True, help="含 DOI 列（及标题列）的表格")
    ap.add_argument("--dest", required=True, help="已下载目录")
    ap.add_argument("--list", action="store_true", help="列出缺失明细")
    args = ap.parse_args()

    xlsx, dest = Path(args.xlsx), Path(args.dest)
    if not xlsx.exists():
        print(f"表格不存在: {xlsx}")
        return 2
    if not dest.exists():
        print(f"目录不存在: {dest}（还没有任何下载？）")
        return 2

    meta = load_titles(xlsx)
    files = [p for p in dest.glob("*.pdf") if valid_pdf(p)]
    names_lower = {p.name.lower() for p in files}
    tags = {p.stem.lower() for p in files}

    done, todo = [], []
    for doi, (journal, title) in meta.items():
        hit = doi_tag(doi) in tags
        if not hit and title:
            key = safe_filename(title)[:60].lower()
            hit = any(key in n for n in names_lower)
        (done if hit else todo).append((doi, journal, title))

    print("=" * 68)
    print(f"完成 {len(done)} / {len(meta)}     目录内有效 PDF {len(files)} 个")
    print("=" * 68)

    if not todo:
        print("\n全部到齐。")
        return 0

    by_pub = Counter(publisher_of(d) for d, _, _ in todo)
    print("\n缺口按出版商:")
    advice = {
        "Springer": "✅ 可自动: fetch_crossref_tdm.py",
        "Nature":   "✅ 可自动: fetch_crossref_tdm.py",
        "MDPI":     "✅ 可自动: fetch_mdpi_cdn.py",
        "Wiley":    "✅ 可自动: fetch_wiley_tdm.py（需 TDM token）",
        "Elsevier": "⚠️ 需全文权益: fetch_elsevier_api.py --diagnose",
        "RSC":      "❌ 无自助通道 → 人工清单",
        "IOP":      "❌ 无自助通道 → 人工清单",
        "ACS":      "❌ 无免费通道 → 人工清单",
    }
    for pub, n in by_pub.most_common():
        print(f"  {pub:12s} {n:3d} 篇   {advice.get(pub, '')}")

    if args.list:
        print("\n缺失明细:")
        for doi, journal, title in sorted(todo, key=lambda x: publisher_of(x[0])):
            print(f"  [{publisher_of(doi):9s}] {doi:34s} {journal[:24]:26s} {title[:50]}")

    manual = sum(n for p, n in by_pub.items() if p in ("RSC", "IOP", "ACS"))
    if manual:
        print(f"\n其中 {manual} 篇无自助通道 → python make_checklist.py --xlsx {xlsx} --dest {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
