#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为「无官方自助通道」的出版商生成人工下载清单。

为什么需要这个而不是自动化
--------------------------
RSC / IOP / ACS 明文禁止或未开放自动化批量下载；Elsevier 常因权益未开而卡住。
手动下载是正常个人使用，不在禁止之列 —— 所以正确做法是**把清单做好**，
而不是写爬虫。详见 references/access-matrix.md 的「合规边界」。

两层"进度"机制（互相补充）
------------------------
1. **文件检测（权威）** —— 每次重新运行本脚本，都会扫描 `--dest` 目录，
   已经下到的条目会自动从清单消失。**这是判断"还缺什么"的可靠依据。**
2. **勾选标记（便利）** —— HTML 里的复选框，状态存浏览器 localStorage。
   实测：同一浏览器会话内刷新页面可保留；**跨浏览器重启是否保留取决于该浏览器
   是否有持久化 profile**（用户日常用的 Edge/Chrome 有，无痕窗口/临时 profile 没有）
   —— 所以别把它当唯一依据，丢了就重新生成清单。

产出两个文件
-----------
1. `待下载清单.html` —— 勾选追踪 + 进度条 + 「复制剩余 DOI」（方便粘进图书馆
   文献传递系统）+ 「重置进度」。
2. `待下载清单.txt` —— 纯文本，方便打印或贴给他人。

用法:
    python make_checklist.py --xlsx 表.xlsx --dest ./papers
    python make_checklist.py --xlsx 表.xlsx --dest ./papers --all   # 含所有未完成项
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    norm_doi, publisher_of, safe_filename, valid_pdf,
)

# 默认只列「无官方自助通道」的出版商；--all 则列出所有未完成项
MANUAL_ONLY = {"RSC", "IOP", "ACS", "TaylorFrancis", "Oxford", "Science", "?"}
ORDER = ["Elsevier", "Wiley", "RSC", "ACS", "IOP", "Springer", "Nature", "MDPI",
         "TaylorFrancis", "Oxford", "Science", "?"]

HINTS = {
    "RSC": "无自助 API。TDM 需提前两周申请且供 XML 不是 PDF —— 10 篇以内直接手动下更快。",
    "IOP": "明文封锁 systematic downloading，批量走 SFTP（contentsupport@ioppublishing.org）。",
    "ACS": "TDM 是付费商品，无免费自助通道。",
    "Elsevier": "需全文权益（受限 API，默认不开通）。若 API 不可用，手动下载是最快的；"
                "同时可让图书馆协助申请 instToken（长期方案）。",
    "Wiley": "有官方 TDM API。单篇 Access Denied 多半是该刊不在机构订阅内。",
    "Springer": "有零凭证通道（Crossref TDM），先试 fetch_crossref_tdm.py。",
    "Nature": "有零凭证通道（Crossref TDM），先试 fetch_crossref_tdm.py。",
    "MDPI": "有零凭证通道（CDN），先试 fetch_mdpi_cdn.py。",
}


def load_meta(xlsx: Path) -> dict[str, tuple[str, str, str]]:
    """DOI -> (期刊名, 标题, 年份)。"""
    import pandas as pd
    df = pd.read_excel(xlsx, header=0)
    cols = {str(c).strip().lower(): c for c in df.columns}
    doi_col = cols.get("doi")
    if doi_col is None:
        raise ValueError(f"表格里找不到 DOI 列。实际列：{list(df.columns)[:12]}")
    title_col = next((cols[k] for k in ("article title", "title", "标题") if k in cols), None)
    src_col = next((cols[k] for k in ("source title", "journal", "期刊", "来源出版物")
                    if k in cols), None)
    yr_col = next((cols[k] for k in ("publication year", "year", "年份") if k in cols), None)

    out = {}
    for _, r in df.iterrows():
        d = norm_doi(str(r[doi_col]))
        if d:
            out[d] = (str(r[src_col]).strip() if src_col else "",
                      str(r[title_col]).strip() if title_col else "",
                      str(r[yr_col]).strip() if yr_col else "")
    return out


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def main() -> int:
    ap = argparse.ArgumentParser(description="生成人工下载清单（带进度追踪）")
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
    for doi, (journal, title, year) in meta.items():
        hit = doi.lower().replace("/", "_") in tags
        if not hit and title:
            hit = any(safe_filename(title)[:60].lower() in n for n in names_lower)
        if hit:
            continue
        pub = publisher_of(doi)
        if args.all or pub in MANUAL_ONLY:
            todo.append((doi, journal, title, year, pub))

    if not todo:
        print("没有需要人工处理的条目 —— 全部已下载。")
        return 0

    todo.sort(key=lambda x: (ORDER.index(x[4]) if x[4] in ORDER else 99, x[1], x[2]))

    # 进度存储键：由 DOI 集合派生，换清单不会串台
    sig = hashlib.sha1("|".join(sorted(d for d, *_ in todo)).encode()).hexdigest()[:12]

    # ---------------- TXT ----------------
    L = [f"待手动下载清单 — 共 {len(todo)} 篇",
         f"目标目录: {dest}",
         "做法: 点 DOI 链接 → 页面上点 Download / PDF → 存进上面那个目录",
         "文件名不用改，下完跑 rename_by_meta.py 批量重命名。", ""]
    cur = None
    for i, (doi, j, t, y, p) in enumerate(todo, 1):
        if p != cur:
            L += ["", f"─── {p} " + "─" * max(0, 48 - len(p))]
            if p in HINTS:
                L.append("   " + HINTS[p])
            cur = p
        L += [f"{i:3d}. {t or '(无标题)'}" + (f"  ({y})" if y else ""),
              f"     期刊  : {j}",
              f"     链接  : https://doi.org/{doi}",
              f"     将命名: {j} - {t}.pdf", ""]
    txt = dest.parent / "待下载清单.txt"
    txt.write_text("\n".join(L), encoding="utf-8")

    # ---------------- HTML ----------------
    rows, cur = [], None
    for i, (doi, j, t, y, p) in enumerate(todo, 1):
        if p != cur:
            hint = HINTS.get(p, "")
            rows.append(
                '<tr class="sep"><td colspan="3"><b>' + esc(p) + '</b>'
                + (f'<div class="h">{esc(hint)}</div>' if hint else '')
                + '</td></tr>')
            cur = p
        meta_line = esc(j) + (f" · {esc(y)}" if y else "")
        rows.append(
            f'<tr class="item" data-i="{i}">'
            f'<td class="chk"><input type="checkbox" id="c{i}"></td>'
            f'<td><label for="c{i}"><span class="ttl">{esc(t or "(无标题)")}</span></label>'
            f'<div class="j">{meta_line}  ·  '
            f'<a href="https://doi.org/{esc(doi)}" target="_blank" rel="noopener">'
            f'打开 DOI ↗</a></div></td>'
            f'<td class="f">{esc(j)} - {esc(t or "")}.pdf</td></tr>')

    css = """
body{font-family:'Segoe UI',Arial,sans-serif;padding:24px 28px;color:#202124;margin:0}
h1{font-size:18px;margin:0 0 10px}
.bar{position:sticky;top:0;background:#fff;padding:10px 0 14px;border-bottom:1px solid #e8eaed;z-index:5;margin-bottom:8px}
.track{height:8px;background:#e8eaed;border-radius:4px;overflow:hidden;margin:8px 0}
.fill{height:100%;background:#1a73e8;width:0;transition:width .25s}
.stat{font-size:13px;color:#5f6368}
.stat b{color:#202124}
button{font:inherit;font-size:12.5px;padding:5px 11px;margin-right:8px;border:1px solid #dadce0;
       background:#fff;border-radius:6px;cursor:pointer}
button:hover{background:#f8f9fa}
.note{color:#5f6368;font-size:12.5px;line-height:1.6;margin:0 0 4px}
code{background:#f1f3f4;padding:1px 5px;border-radius:3px;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}
td{border-bottom:1px solid #eee;padding:8px 9px;vertical-align:top}
.sep td{background:#f1f3f4;font-weight:700;font-size:12px;letter-spacing:.4px}
.sep .h{font-weight:400;color:#5f6368;font-size:11.5px;margin-top:3px;letter-spacing:0}
.chk{width:26px}
.chk input{width:15px;height:15px;cursor:pointer}
.ttl{cursor:pointer}
.j{color:#5f6368;font-size:11.5px;margin-top:3px}
.f{color:#9aa0a6;font-size:11px;font-family:Consolas,monospace;width:34%}
a{color:#1a73e8;text-decoration:none}a:hover{text-decoration:underline}
tr.done .ttl{text-decoration:line-through;color:#9aa0a6}
tr.done .f{opacity:.5}
"""
    js = """
const KEY = "pfchecklist:""" + sig + """";
function load(){ try{ return new Set(JSON.parse(localStorage.getItem(KEY)||"[]")); }catch(e){ return new Set(); } }
function save(s){ try{ localStorage.setItem(KEY, JSON.stringify([...s])); }catch(e){} }
let done = load();
const total = document.querySelectorAll("tr.item").length;
function render(){
  document.querySelectorAll("tr.item").forEach(tr=>{
    const i = tr.dataset.i, on = done.has(i);
    tr.classList.toggle("done", on);
    const cb = tr.querySelector("input");
    if (cb) cb.checked = on;
  });
  const n = done.size;
  document.getElementById("cnt").textContent = n;
  document.getElementById("fill").style.width = (total? n*100/total : 0) + "%";
  document.getElementById("todo").textContent = total - n;
}
document.querySelectorAll("tr.item input").forEach(cb=>{
  cb.addEventListener("change", ()=>{
    const i = cb.closest("tr").dataset.i;
    if (cb.checked) { done.add(i); } else { done.delete(i); }
    save(done); render();
  });
});
document.getElementById("copy").addEventListener("click", async ()=>{
  const left = [...document.querySelectorAll("tr.item")]
    .filter(tr=>!done.has(tr.dataset.i))
    .map(tr=>{ const a=tr.querySelector("a[href^='https://doi.org/']"); return a?a.href.replace("https://doi.org/",""):null; })
    .filter(Boolean);
  if(!left.length){ alert("已全部完成"); return; }
  try{ await navigator.clipboard.writeText(left.join("\\n")); alert("已复制 "+left.length+" 个 DOI 到剪贴板"); }
  catch(e){ alert("复制失败，请手动选择。剩余 "+left.length+" 个 DOI"); }
});
document.getElementById("reset").addEventListener("click", ()=>{
  if(confirm("清空所有勾选？")){ done = new Set(); save(done); render(); }
});
render();
"""

    html = ('<!doctype html><html lang="zh"><head><meta charset="utf-8">'
            '<title>待下载清单</title><style>' + css + '</style></head><body>'
            '<div class="bar">'
            '<h1>待手动下载 &mdash; ' + str(len(todo)) + ' 篇</h1>'
            '<div class="track"><div class="fill" id="fill"></div></div>'
            '<div class="stat">已完成 <b id="cnt">0</b> / ' + str(len(todo))
            + ' &nbsp;·&nbsp; 剩余 <b id="todo">' + str(len(todo)) + '</b>'
            ' &nbsp;·&nbsp; <button id="copy">复制剩余 DOI</button>'
            '<button id="reset">重置进度</button></div>'
            '</div>'
            '<p class="note">点标题打开文章页 → 点 Download / PDF → 存进 <code>'
            + esc(str(dest)) + '</code><br>'
            '勾选即记录进度（存在浏览器本地，关掉再开还在）。'
            '文件名不用手动改，下完跑 <code>rename_by_meta.py</code> 批量归位。</p>'
            '<table>' + ''.join(rows) + '</table>'
            '<script>' + js + '</script></body></html>')
    htmlp = dest.parent / "待下载清单.html"
    htmlp.write_text(html, encoding="utf-8")

    print(f"共 {len(todo)} 篇")
    print("按出版商:", dict(Counter(x[4] for x in todo)))
    print()
    print(f"  {htmlp}   ← 推荐：带进度追踪")
    print(f"  {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
