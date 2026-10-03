#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为「无官方自助通道」的出版商生成人工下载清单（HTML + TXT）。

为什么需要这个而不是自动化:
    RSC / IOP / ACS 明文禁止或未开放自动化批量下载。手动下载是正常个人使用，
    不在禁止之列 —— 所以正确做法是生成好点的清单让用户点，而不是写爬虫。
    详见 references/access-matrix.md 的「合规边界」。

用法:
    python make_checklist.py --xlsx 表.xlsx --dest ./papers
    python make_checklist.py --xlsx 表.xlsx --dest ./papers --all   # 含所有未完成项
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    norm_doi, publisher_of, read_doi_list, safe_filename, valid_pdf,
)

MANUAL_ONLY = {"RSC", "IOP", "ACS", "TaylorFrancis", "Oxford", "Science", "?"}
ORDER = ["Elsevier", "Wiley", "RSC", "ACS", "IOP", "Springer", "Nature", "MDPI",
         "TaylorFrancis", "Oxford", "Science", "?"]

# 每家的说明
HINTS = {
    "RSC": "RSC 无自助 API；TDM 需提前两周申请且供 XML 不是 PDF。6 篇以内直接手动下更快。",
    "IOP": "IOP 明文封锁 systematic downloading，批量走 SFTP（contentsupport@ioppublishing.org）。",
    "ACS": "ACS 的 TDM 是付费商品，无免费自助通道。",
    "Elsevier": "需要全文权益（受限 API）。若 API 不可用，手动下载是最快的。",
    "Wiley": "有官方 TDM API；若单篇 Access Denied，多半是该刊不在机构订阅内。",
}


def load_meta(xlsx: Path) -> dict[str, tuple[str, str]]:
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
        if d:
            out[d] = (str(r[src_col]).strip() if src_col else "",
                      str(r[title_col]).strip() if title_col else "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成人工下载清单")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--dest", required=True, help="已下载目录（用来判断哪些已完成）")
    ap.add_argument("--all", action="store_true",
                    help="包含所有未完成项（默认只列无自助通道的那几家）")
    args = ap.parse_args()

    xlsx, dest = Path(args.xlsx), Path(args.dest)
    meta = load_meta(xlsx)
    dest.mkdir(parents=True, exist_ok=True)

    files = [p for p in dest.glob("*.pdf") if valid_pdf(p)]
    names_lower = {p.name.lower() for p in files}
    tags = {p.stem.lower() for p in files}

    todo = []
    for doi, (journal, title) in meta.items():
        hit = doi.lower().replace("/", "_") in tags
        if not hit and title:
            hit = any(safe_filename(title)[:60].lower() in n for n in names_lower)
        if hit:
            continue
        pub = publisher_of(doi)
        if args.all or pub in MANUAL_ONLY:
            todo.append((doi, journal, title, pub))

    if not todo:
        print("没有需要人工处理的条目。")
        return 0

    todo.sort(key=lambda x: (ORDER.index(x[3]) if x[3] in ORDER else 99, x[1]))

    # ---------- TXT ----------
    L = [f"待手动下载清单 — 共 {len(todo)} 篇",
         f"目标目录: {dest}",
         "做法: 点 DOI 链接 → 页面上点 Download / PDF → 存进上面那个目录",
         "文件名不用改，下完跑 rename_by_meta.py 批量重命名。", ""]
    cur = None
    for i, (doi, j, t, p) in enumerate(todo, 1):
        if p != cur:
            L += ["", f"─── {p} " + "─" * max(0, 50 - len(p))]
            if p in HINTS:
                L.append("   " + HINTS[p])
            cur = p
        L += [f"{i:3d}. {t or '(无标题)'}",
              f"     期刊  : {j}",
              f"     链接  : https://doi.org/{doi}",
              f"     将命名: {j} - {t}.pdf", ""]
    txt = dest.parent / "待下载清单.txt"
    txt.write_text("\n".join(L), encoding="utf-8")

    # ---------- HTML ----------
    rows, cur = [], None
    for i, (doi, j, t, p) in enumerate(todo, 1):
        if p != cur:
            hint = HINTS.get(p, "")
            rows.append('<tr class="sep"><td colspan="3"><b>' + p + '</b>'
                        + ('<div class="h">' + hint + '</div>' if hint else '')
                        + '</td></tr>')
            cur = p
        rows.append(
            '<tr><td class="n">' + str(i) + '</td>'
            '<td><a href="https://doi.org/' + doi + '" target="_blank">'
            + (t or '(无标题)') + '</a><div class="j">' + j + '</div></td>'
            '<td class="f">' + j + ' - ' + (t or '') + '.pdf</td></tr>')

    css = ("body{font-family:'Segoe UI',Arial,sans-serif;padding:26px 30px;color:#202124}"
           "h1{font-size:18px;margin:0 0 4px}"
           ".hint{color:#5f6368;font-size:12.5px;margin-bottom:16px;line-height:1.6}"
           "table{border-collapse:collapse;width:100%;font-size:13px}"
           "td{border-bottom:1px solid #eee;padding:7px 9px;vertical-align:top}"
           ".sep td{background:#f1f3f4;font-weight:700;font-size:12px;letter-spacing:.4px}"
           ".sep .h{font-weight:400;color:#5f6368;font-size:11.5px;margin-top:3px;letter-spacing:0}"
           ".n{color:#5f6368;width:30px}.j{color:#5f6368;font-size:11.5px;margin-top:2px}"
           ".f{color:#5f6368;font-size:11px;font-family:Consolas,monospace;width:36%}"
           "a{color:#1a73e8;text-decoration:none}a:hover{text-decoration:underline}")

    html = ('<!doctype html><meta charset="utf-8"><title>待下载清单</title><style>'
            + css + '</style><h1>待手动下载 &mdash; ' + str(len(todo)) + ' 篇</h1>'
            + '<div class="hint">点标题打开文章页 → 点 Download / PDF → 存进 <code>'
            + str(dest) + '</code><br>文件名不用手动改，下完跑 '
            + '<code>rename_by_meta.py</code> 批量归位。</div>'
            + '<table>' + ''.join(rows) + '</table>')
    htmlp = dest.parent / "待下载清单.html"
    htmlp.write_text(html, encoding="utf-8")

    print(f"共 {len(todo)} 篇")
    print("按出版商:", dict(Counter(x[3] for x in todo)))
    print()
    print(f"  {txt}")
    print(f"  {htmlp}   ← 点标题直接跳转，推荐用这个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
