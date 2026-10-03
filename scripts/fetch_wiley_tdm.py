#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 Wiley 官方 TDM API 下载 —— 无反爬，官方许可。

用 Wiley 官方的 wiley-tdm 客户端，不自己拼 API。

前置:
    pip install wiley-tdm
    export WILEY_TDM_TOKEN="<uuid>"      # 申请见 credentials.md

官方限速: 3 篇/秒、60 请求/10 分钟。长期批量建议 10 秒/篇（默认值）。
**慢是特性不是缺陷** —— 慢速正是长期不被封的关键。

用法:
    python fetch_wiley_tdm.py --xlsx 表.xlsx --dest ./papers
    python fetch_wiley_tdm.py --dois 10.1002/anie.202512175 --dest ./papers
    python fetch_wiley_tdm.py --xlsx 表.xlsx --dest ./papers --rate 10
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ensure_dir, get, norm_doi, read_doi_list, redact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Wiley 官方 TDM API 下载")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xlsx", help="含 DOI 列的表格")
    src.add_argument("--dois", help="逗号分隔的 DOI")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--rate", type=float, default=10.0,
                    help="每篇间隔秒数（默认 10，官方建议长期值，不可低于 5）")
    args = ap.parse_args()

    token = get("wiley_tdm_token")
    if not token:
        print("缺少 Wiley TDM token。")
        print("  export WILEY_TDM_TOKEN=\"<uuid>\"")
        print("  申请步骤: python doctor.py --guide")
        return 2
    os.environ["TDM_API_TOKEN"] = token

    try:
        from wiley_tdm import TDMClient
    except ImportError:
        print("未安装官方客户端：pip install wiley-tdm")
        return 2

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = [d for d in dois if d.lower().startswith("10.1002/")]
    if not dois:
        print("没有 10.1002/* 的 DOI，无需走 Wiley 通道。")
        return 0

    dest = ensure_dir(args.dest)
    print(f"Wiley 官方 TDM API · {len(dois)} 篇 → {dest}")
    print(f"token: {redact(token)}   限速: {args.rate} 秒/篇\n")

    tdm = TDMClient(download_dir=dest)
    tdm.api_rate_limit = max(args.rate, 5.0)     # 官方下限 5 秒

    results = tdm.download_pdfs(dois)

    ok = fail = 0
    denied: list[str] = []
    for r in results:
        st = str(getattr(r, "status", "?"))
        p = getattr(r, "path", None)
        size = Path(p).stat().st_size if p and Path(p).exists() else 0
        if size > 20000:
            ok += 1
        else:
            fail += 1
            if "denied" in st.lower():
                denied.append(getattr(r, "doi", "?"))
        print(f"  {st:14s} {getattr(r, 'doi', '?'):34s} {size:>10,} B")

    print(f"\n成功 {ok} · 失败 {fail}")

    if denied:
        print()
        print("Access Denied 的 DOI（通常是该刊不在机构订阅内，属正常现象）：")
        for d in denied:
            print("   ", d)
        print("若**全部** Access Denied，则可能是 IP 鉴权问题：")
        print("  官方文档明确只支持 IP 鉴权，需从机构登记的 IP 段内发起请求。")
        print("  找图书馆确认机构 WOL 账号是否配置了 IP 访问。")

    try:
        tdm.save_results(str(dest / "wiley_tdm_results.csv"))
        print(f"\n明细已存: {dest / 'wiley_tdm_results.csv'}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
