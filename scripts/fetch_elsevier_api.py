#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elsevier Article Retrieval API —— 下载 + 权益诊断。

⚠️ 重要：Elsevier 的 API key 与"全文权益"是两件事。
   - key 是自助注册的
   - **全文权益 (ScienceDirect Full-Text Entitlement) 是受限 API，默认不开通**，
     需单独申请，可能被拒
   只拿到 key 会看到：摘要 200、全文 403 AUTHENTICATION_ERROR。
   **这不是配置错误。** 详见 credentials.md

⚠️ 不要抓 ScienceDirect 网站 —— TDM 协议 2.2 明文禁止自动化程序访问其网站。
   拿不到权益时，正确做法是让用户手动下载。

用法:
    python fetch_elsevier_api.py --dois 10.1016/j.jcou.2025.103019 --dest ./papers
    python fetch_elsevier_api.py --xlsx 表.xlsx --dest ./papers
    python fetch_elsevier_api.py --diagnose          # 只诊断权益状态
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import doi_tag, ensure_dir, get, norm_doi, read_doi_list, redact, valid_pdf  # noqa: E402

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests")
    sys.exit(1)

API = "https://api.elsevier.com/content"
# gold OA 对照：OA 内容本该任何有效 key 都能取
OA_CONTROL = "10.1016/j.jcou.2025.103019"


def call(key: str, path: str, accept: str = "application/json"):
    return requests.get(f"{API}/{path}",
                        headers={"X-ELS-APIKey": key, "Accept": accept},
                        timeout=60)


def diagnose(key: str) -> bool:
    """返回全文权益是否可用。"""
    print("=" * 68)
    print("Elsevier 权益诊断")
    print("=" * 68)
    print(f"  key: {redact(key)}\n")

    r = call(key, f"abstract/doi/{OA_CONTROL}")
    abstract_ok = r.status_code == 200
    print(f"  [{'OK' if abstract_ok else '!!'}] 摘要接口              HTTP {r.status_code}")
    if not abstract_ok:
        print(f"       {r.text[:120]}")

    r2 = call(key, f"article/doi/{OA_CONTROL}?view=FULL", accept="text/xml")
    full_ok = r2.status_code == 200
    print(f"  [{'OK' if full_ok else '!!'}] 全文接口（gold OA 对照） HTTP {r2.status_code}")

    if not full_ok:
        print(f"       {r2.text[:160]}")

    print()
    if full_ok:
        print("  >>> 全文权益可用，可以下载。")
    elif abstract_ok:
        print("  >>> key 有效，但**缺全文权益**（受限 API，默认不开通）。")
        print("      这不是配置错误。请走 API Support 表单申请，模板见 credentials.md。")
        print("      在拿到权益前，这批文献请让用户手动下载。")
    else:
        print("  >>> key 本身无效或未启用。检查 key 是否正确。")
    return full_ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Elsevier Article Retrieval API")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--xlsx")
    src.add_argument("--dois")
    ap.add_argument("--dest", default="./papers")
    ap.add_argument("--diagnose", action="store_true", help="只诊断，不下载")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    key = get("elsevier_api_key")
    if not key:
        print("缺少 Elsevier API key。")
        print("  申请: python doctor.py --guide")
        return 2

    if args.diagnose:
        return 0 if diagnose(key) else 1

    if not (args.xlsx or args.dois):
        ap.error("需要 --xlsx 或 --dois（或使用 --diagnose）")

    if not diagnose(key):
        print("\n全文权益不可用，放弃下载。")
        print("建议: python make_checklist.py --xlsx <表.xlsx> --dest <目录>  生成人工清单")
        return 1

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = [d for d in dois if d.lower().startswith("10.1016/")]
    dest = ensure_dir(args.dest)

    print(f"\nElsevier API · {len(dois)} 篇 → {dest}\n")
    ok = skip = fail = 0
    for i, doi in enumerate(dois, 1):
        out = dest / f"{doi_tag(doi)}.pdf"
        if valid_pdf(out):
            print(f"{i:3d}. skip   {doi}")
            skip += 1
            continue
        r = call(key, f"article/doi/{doi}", accept="application/pdf")
        if r.status_code == 200 and r.content[:5] == b"%PDF-":
            out.write_bytes(r.content)
            print(f"{i:3d}. OK     {doi}   {len(r.content):,} B")
            ok += 1
        else:
            print(f"{i:3d}. FAIL   {doi}   HTTP {r.status_code}  {r.text[:60]}")
            fail += 1
        time.sleep(args.sleep)

    print(f"\n成功 {ok} · 跳过 {skip} · 失败 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
