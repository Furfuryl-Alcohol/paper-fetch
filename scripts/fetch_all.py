#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一条命令跑完：按出版商分发到各通道 → 重命名 → 生成人工清单。

设计上刻意保持简单：
  · 不维护状态机 —— 已下载的 PDF 会被各通道自动跳过，中断后重跑即可
  · 不做并发 —— Wiley 的限速是硬约束，并行只会更快被封
  · 只做编排 —— 下载逻辑仍在各 fetch_*.py 里

用法:
    python fetch_all.py --xlsx 表.xlsx --dest ./papers
    python fetch_all.py --xlsx 表.xlsx --dest ./papers --dry-run
    python fetch_all.py --dois 10.1038/xxxx,10.1002/yyyy --dest ./papers
    python fetch_all.py --xlsx 表.xlsx --dest ./papers --skip elsevier,wiley
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from _common import get, norm_doi, publisher_of, read_doi_list  # noqa: E402

PY = sys.executable

# (lane key, 显示名, 脚本, 处理的出版商, 额外参数)
LANES = [
    ("crossref", "Crossref TDM (Springer/Nature)", "fetch_crossref_tdm.py",
     {"Springer", "Nature"}, ["--only", "10.1007,10.1186,10.1038"]),
    ("mdpi", "MDPI CDN", "fetch_mdpi_cdn.py", {"MDPI"}, []),
    ("wiley", "Wiley TDM", "fetch_wiley_tdm.py", {"Wiley"}, []),
    ("elsevier", "Elsevier API", "fetch_elsevier_api.py", {"Elsevier"}, []),
]
MANUAL = {"RSC", "IOP", "ACS", "TaylorFrancis", "Oxford", "Science", "?"}
CRED = {
    "wiley": ("wiley_tdm_token", "WILEY_TDM_TOKEN"),
    "elsevier": ("elsevier_api_key", "ELSEVIER_API_KEY"),
}


def dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="一条命令跑完 paper-fetch")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xlsx", help="含 DOI 列的表格（xlsx/csv/txt）")
    src.add_argument("--dois", help="逗号分隔的 DOI")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    ap.add_argument("--skip", default="",
                    help="跳过的通道: " + ",".join(k for k, *_ in LANES))
    args = ap.parse_args()

    # 父进程的 print 默认块缓冲，会让子进程输出跑到计划表前面
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    dois = ([norm_doi(d) for d in args.dois.split(",") if d.strip()]
            if args.dois else read_doi_list(args.xlsx))
    dois = dedupe(dois)
    if not dois:
        print("没有读到任何 DOI。")
        return 2

    groups = defaultdict(list)
    for d in dois:
        groups[publisher_of(d)].append(d)

    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}
    print(f"共 {len(dois)} 篇 → {args.dest}\n")

    plan = []
    for key, label, script, pubs, extra in LANES:
        picked = [d for p in pubs for d in groups.get(p, [])]
        if not picked:
            continue
        if key in skip:
            print(f"  {label:34s} {len(picked):3d} 篇  （--skip）")
            continue
        needed = CRED.get(key)
        if needed and not get(needed[0]):
            print(f"  {label:34s} {len(picked):3d} 篇  （缺 {needed[1]}，跳过）")
            continue
        plan.append((key, label, script, picked, extra))
        print(f"  {label:34s} {len(picked):3d} 篇")

    manual = [d for p in MANUAL for d in groups.get(p, [])]
    if manual:
        print(f"  {'人工清单':34s} {len(manual):3d} 篇  → 需手动下载")

    covered = {p for _, _, _, pubs, _ in LANES for p in pubs} | MANUAL
    other = [d for p, ds in groups.items() if p not in covered for d in ds]
    if other:
        print(f"  {'未识别出版商':34s} {len(other):3d} 篇  → 无自动通道")

    if args.dry_run:
        print("\n--dry-run：未执行。")
        return 0

    dest = Path(args.dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="paper-fetch-"))
    failed: list[str] = []
    try:
        for key, label, script, picked, extra in plan:
            lane_file = tmpdir / f"{key}.txt"
            lane_file.write_text("\n".join(picked), encoding="utf-8")
            cmd = [PY, "-u", str(HERE / script), "--xlsx", str(lane_file),
                   "--dest", str(dest)] + extra
            print(f"\n{'=' * 60}\n{label} · {len(picked)} 篇\n{'=' * 60}")
            if subprocess.run(cmd).returncode != 0:
                failed.append(label)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if args.xlsx:
        print(f"\n{'=' * 60}\n重命名\n{'=' * 60}")
        subprocess.run([PY, "-u", str(HERE / "rename_by_meta.py"),
                        "--xlsx", args.xlsx, "--dest", str(dest)])
        print(f"\n{'=' * 60}\n人工清单\n{'=' * 60}")
        subprocess.run([PY, "-u", str(HERE / "make_checklist.py"),
                        "--xlsx", args.xlsx, "--dest", str(dest)])
    else:
        print("\n[hint] 传 --xlsx 才能自动重命名并生成人工清单"
              "（--dois 没有标题元数据）。")

    print("\n完成。" + (f" 有通道返回非零: {', '.join(failed)}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
