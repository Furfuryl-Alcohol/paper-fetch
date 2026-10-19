#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 Wiley 官方 TDM API 下载 —— 无反爬，官方许可。

纯标准库实现（`_http` 基于 urllib），不再依赖 `wiley-tdm` 包。
API 本身就是一次 GET：

    GET https://api.wiley.com/onlinelibrary/tdm/v1/articles/{urlencoded DOI}
    Header: Wiley-TDM-Client-Token: <uuid>

限速
----
官方规定长期批量 60 请求/10 分钟（≈10 秒/篇），并设 3 篇/秒的峰值。
本脚本默认 10 秒/篇，且拒绝低于 5 秒 —— **慢是特性不是缺陷**，
慢速正是长期不被封的关键。

403 的两种含义
--------------
- **单篇** 403：该刊不在机构订阅内（正常现象）
- **全部** 403：IP 鉴权失败 —— 官方只支持 IP 鉴权，
  需从机构登记的 IP 段发起请求

用法:
    python fetch_wiley_tdm.py --xlsx 表.xlsx --dest ./papers
    python fetch_wiley_tdm.py --dois 10.1002/anie.202512175 --dest ./papers
    python fetch_wiley_tdm.py --xlsx 表.xlsx --dest ./papers --rate 10
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    doi_tag, ensure_dir, get, norm_doi, read_doi_list, redact, valid_pdf,
)
import _http as requests  # noqa: E402

API = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/"
MANUAL = "https://onlinelibrary.wiley.com/doi/epdf/"
TIMEOUT = (5, 30)          # (connect, read) —— 与官方客户端一致
MIN_RATE = 5.0             # 官方客户端的硬下限
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def download_one(doi: str, token: str, dest: Path) -> tuple[str, int, str]:
    """返回 (状态, 字节数, 说明)。状态：OK/SKIP/DENIED/NOT_FOUND/RATE_LIMITED/ERROR。"""
    out = dest / f"{doi_tag(doi)}.pdf"
    if out.exists() and valid_pdf(out):
        return "SKIP", out.stat().st_size, "已存在有效 PDF"

    url = API + urllib.parse.quote(doi, safe="")
    headers = {
        "Wiley-TDM-Client-Token": token,
        "User-Agent": "paper-fetch/1.0 (Wiley TDM)",
    }

    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT,
                             allow_redirects=True)
        except requests.RequestException as e:
            if attempt == 2:
                return "ERROR", 0, f"网络错误: {str(e)[:120]}"
            time.sleep(3 * (attempt + 1))
            continue

        if r.status_code == 429:                      # 限流，退避后重试
            if attempt == 2:
                return "RATE_LIMITED", 0, "连续触发限流，稍后再跑"
            time.sleep(30 * (attempt + 1))
            continue

        if r.status_code == 200:
            # 不校验就会把 200 + HTML 错误页存成假 PDF
            if r.content[:5] == b"%PDF-" and len(r.content) > 20000:
                out.write_bytes(r.content)
                return "OK", len(r.content), ""
            return ("ERROR", len(r.content),
                    "HTTP 200 但内容不是 PDF（可能是错误页，未落盘）")

        if r.status_code == 403:
            return ("DENIED", 0,
                    f"该刊不在机构订阅内，或 IP 鉴权失败。手动下载: {MANUAL}{doi}")
        if r.status_code == 404:
            return "NOT_FOUND", 0, "Wiley 无此 DOI（或尚未分配）"
        if r.status_code >= 500:
            if attempt == 2:
                return "ERROR", 0, f"HTTP {r.status_code}（服务端错误）"
            time.sleep(5 * (attempt + 1))
            continue
        return "ERROR", 0, f"HTTP {r.status_code}: {r.text[:160]}"

    return "ERROR", 0, "重试耗尽"


def main() -> int:
    ap = argparse.ArgumentParser(description="Wiley 官方 TDM API 下载（零第三方依赖）")
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
        print('  export WILEY_TDM_TOKEN="<uuid>"   # PowerShell: $env:WILEY_TDM_TOKEN="<uuid>"')
        print("  申请步骤: python doctor.py --guide")
        return 2
    if not UUID_RE.match(token):
        print("[warn] token 不是标准 UUID 格式，仍会尝试使用。")

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = [d for d in dois if d.lower().startswith("10.1002/")]
    if not dois:
        print("没有 10.1002/* 的 DOI，无需走 Wiley 通道。")
        return 0

    rate = max(float(args.rate), MIN_RATE)
    if rate < args.rate:
        print(f"[hint] 已把间隔提升到官方下限 {MIN_RATE:g} 秒。")

    dest = ensure_dir(args.dest)
    print(f"Wiley 官方 TDM API（纯标准库）· {len(dois)} 篇 → {dest}")
    print(f"token: {redact(token)}   限速: {rate:g} 秒/篇\n")

    results: list[tuple[str, str, int, str]] = []
    denied: list[str] = []
    ok = skip = fail = 0

    for i, doi in enumerate(dois, 1):
        status, size, msg = download_one(doi, token, dest)
        results.append((doi, status, size, msg))
        if status == "OK":
            ok += 1
        elif status == "SKIP":
            skip += 1
        else:
            fail += 1
            if status == "DENIED":
                denied.append(doi)
        tail = f"   {msg}" if msg else ""
        print(f"{i:3d}. {status:12s} {doi:34s} {size:>10,} B{tail}")

        if i < len(dois):
            time.sleep(rate)

    print(f"\n成功 {ok} · 跳过 {skip} · 失败 {fail}")

    if denied:
        print()
        print("Access Denied 的 DOI（通常是该刊不在机构订阅内，属正常现象）：")
        for d in denied:
            print("   ", d)
        if len(denied) == len(dois):
            print("\n若**全部** Access Denied，则可能是 IP 鉴权问题：")
            print("  官方文档明确只支持 IP 鉴权，需从机构登记的 IP 段内发起请求。")
            print("  找图书馆确认机构 WOL 账号是否配置了 IP 访问。")

    csv_path = dest / "wiley_tdm_results.csv"
    try:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["doi", "status", "bytes", "message"])
            w.writerows(results)
        print(f"\n明细已存: {csv_path}")
    except OSError as e:
        print(f"[warn] 结果 CSV 写入失败: {e}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
