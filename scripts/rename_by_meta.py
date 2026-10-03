#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 DOI 回查表格，把 PDF 重命名为「期刊名 - 标题.pdf」。

匹配顺序（从可靠到宽松）:
  1. 文件名里的 DOI（/ 被换成 _ 或 -）
  2. PDF 元数据 / 首页文本里的 DOI     ← 处理用户手动下载的乱七八糟文件名
  3. 标题模糊匹配

**认不出的文件保持原样并单独列出，绝不删除、绝不覆盖非同名文件。**

用法:
    python rename_by_meta.py --xlsx 表.xlsx --dest ./papers
    python rename_by_meta.py --xlsx 表.xlsx --dest ./papers --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import norm_doi, safe_filename  # noqa: E402


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

    meta = {}
    for _, r in df.iterrows():
        d = norm_doi(str(r[doi_col]))
        if d:
            meta[d] = (str(r[src_col]).strip() if src_col else "",
                       str(r[title_col]).strip() if title_col else "")
    return meta


def pdf_text_head(path: Path, limit: int = 4000) -> str:
    """取 PDF 前几页文本，用于找 DOI。"""
    try:
        import pymupdf
        doc = pymupdf.open(path)
        try:
            txt = ""
            for i in range(min(3, doc.page_count)):
                txt += doc[i].get_text()
                if len(txt) > limit:
                    break
            meta_doi = (doc.metadata or {}).get("doi", "") or ""
            return (meta_doi + "\n" + txt)[:limit]
        finally:
            doc.close()
    except Exception:
        return ""


def doi_from_text(text: str, known: dict) -> str | None:
    """在文本里找已知的 DOI。"""
    if not text:
        return None
    candidates = re.findall(r"10\.\d{4,9}/[^\s,;\"'<>\\)\]]+", text)
    for c in candidates:
        c = norm_doi(c).rstrip(".")
        if c in known:
            return c
        low = c.lower()
        for k in known:
            if k.lower() == low:
                return k
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="按 DOI 回查表格重命名")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--dry-run", action="store_true", help="只预览，不改动")
    args = ap.parse_args()

    xlsx, dest = Path(args.xlsx), Path(args.dest)
    meta = load_meta(xlsx)
    # 规范化 DOI → 用于宽松匹配
    norm_lookup = {re.sub(r"[^a-z0-9.]", "", k.lower()): k for k in meta}

    pdfs = sorted(p for p in dest.glob("*.pdf"))
    if not pdfs:
        print(f"{dest} 里没有 PDF")
        return 0

    print(f"表格 {len(meta)} 条 · 目录 {len(pdfs)} 个 PDF\n")
    renamed = skipped = 0
    unmatched: list[str] = []

    for p in pdfs:
        doi = None
        stem_key = re.sub(r"[^a-z0-9.]", "", p.stem.lower())

        # 1) 文件名
        if stem_key in norm_lookup:
            doi = norm_lookup[stem_key]
        else:
            for k, orig in norm_lookup.items():
                if len(k) > 12 and (stem_key.startswith(k) or k in stem_key):
                    doi = orig
                    break

        # 2) PDF 内容
        if doi is None:
            doi = doi_from_text(pdf_text_head(p), meta)

        # 3) 标题模糊
        if doi is None:
            hay = p.stem.lower()
            for k, (j, t) in meta.items():
                if t and safe_filename(t)[:60].lower() in hay:
                    doi = k
                    break

        if doi is None:
            unmatched.append(p.name)
            continue

        journal, title = meta[doi]
        if not journal and not title:
            unmatched.append(p.name)
            continue

        newname = safe_filename(f"{journal} - {title}" if journal else title) + ".pdf"
        target = p.with_name(newname)

        if target == p:
            skipped += 1
            continue
        if target.exists():
            # 同名目标已存在：内容相同则删掉重复的源，否则保留两者
            try:
                same = target.stat().st_size == p.stat().st_size and \
                       target.read_bytes()[:2000] == p.read_bytes()[:2000]
            except Exception:
                same = False
            if same:
                if not args.dry_run:
                    p.unlink()
                print(f"  去重  {p.name}")
                renamed += 1
                continue
            print(f"  冲突  {newname} 已存在且不同，跳过 {p.name}")
            unmatched.append(p.name)
            continue

        if args.dry_run:
            print(f"  预览  {p.name}\n     -> {newname}")
        else:
            p.rename(target)
            print(f"  OK    {p.name}\n     -> {newname}")
        renamed += 1

    print(f"\n{'将' if args.dry_run else '已'}重命名 {renamed} · 无需改动 {skipped} · "
          f"未匹配 {len(unmatched)}")
    if unmatched:
        print("\n未匹配（保持原样，未删除）:")
        for n in unmatched:
            print("   ", n)
        print("\n未匹配的常见原因：表格里没有这篇的 DOI，或它是补充材料/无关文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
