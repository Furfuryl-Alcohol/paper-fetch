# -*- coding: utf-8 -*-
"""人工下载循环（可选扩展 · 默认关闭）：脚本翻页，人点下载；脚本负责「判定 + 归档」。

判定机制（唯一可靠的那个）
--------------------------
不用 Playwright 的下载事件 —— 实测它**时灵时不灵**：下载被 Playwright 接管时
事件才来（文件进 playwright-artifacts 临时目录、GUID 名）；若人是在浏览器自己
新开的 PDF 预览标签里点的下载，就不接管、事件不来（文件进浏览器默认目录）。
两种情况下脚本都收不到 → 不跳转。

  改回**轮询 Edge 自己的下载记录库**（History.downloads，state=1 即完成）：
  实测 id=1~6 一笔不漏，与"被谁接管"无关，且带 target_path。

归档
----
拿到 target_path 后，按清单里的「将命名」**复制/移动到目标目录**并校验 %PDF-
（源在 playwright 临时目录时顺手删掉，别的地方保留）。于是无论文件原本落在
临时目录还是浏览器自己的默认下载目录，最后都会在目标目录里、名字是对的。

人的职责：文章页点 View PDF → 预览器里点【下载】。存哪不用管。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TITLE_RE = re.compile(r"^(\d+)\.\s+(.*?)\s+\((\d{4})\)\s*$")
PUB_RE = re.compile(r"^───\s*(.+?)\s*─+$")
URL_RE = re.compile(r"^链接\s*:\s*(\S+)")
NAME_RE = re.compile(r"^将命名\s*:\s*(.+)$")
DEST_RE = re.compile(r"^目标目录\s*:\s*(.+)$")
DOI_RE = re.compile(r"doi\.org/(10\.\S+)")

DEFAULT_PROFILE = Path.home() / ".paper-dl" / "edge-profile"
SETTINGS_PATH = Path.home() / ".paper-fetch" / "settings.json"

# ── 合规边界（务必先读）──────────────────────────────────────────
# 本工具**不下载任何东西**：每一篇都必须由人亲手点。它只做三件辅助的事——
# 把浏览器导航到下一篇 DOI 落地页、判断"人下完了没有"、把文件归档改名。
# 不破验证码、不绕付费墙（识别到无权限反而跳过）、不抓页面内容、不存凭证。
#
# 即便如此：Elsevier / IOP / RSC / ACS 的条款明文禁止"自动化程序访问其网站"，
# 本工具确实驱动浏览器访问它们 —— 属于灰色地带。所以本功能**默认关闭**，
# 仅在你确认"有权访问这些内容、并自担使用风险"后才启用。


def manual_loop_enabled(cli_flag: bool) -> bool:
    if cli_flag:
        return True
    try:
        cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return bool(cfg.get("manual_browser_loop_enabled"))
    except Exception:
        return False


def sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name))
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:170]


# ── 无权限快速识别 ──
# 刻意【不含】'institutional login' / 'access through your institution'：
# 那两句在所有 Wiley/ACS 页眉都有，拿来当信号会误伤有权限的文章（实测教训）。
NO_ACCESS_MARKERS = (
    "get access", "purchase pdf", "buy pdf", "buy this article",
    "purchase this article", "purchase access", "rent this article",
    "add to cart", "get full access", "buy article",
)
def sniff_no_access(page) -> str | None:
    """返回命中的强付费墙标记（小写），没有则 None。

    实测对照（2026-10-10）：无权限的 Wiley 页命中 'get access'；有权限的
    ScienceDirect 页 marker=None。而"页面里有 PDF 链接"这个条件**两种情况下
    都成立**（无权限时也留着 /doi/pdf/），所以它不能当判据 —— 已弃用。
    """
    try:
        txt = page.evaluate(
            "() => (document.body ? document.body.innerText : '').toLowerCase()")
    except Exception:
        return None
    for mk in NO_ACCESS_MARKERS:
        if mk in txt:
            return mk
    return None


def sniff_all(ctx) -> tuple[str | None, str]:
    """在所有标签里找付费墙标记，返回 (标记, 出现在哪个网址)。

    实测：Wiley 的付费墙信号**只在 ePDF 页**（人点 View PDF 之后才出现），
    落地页上完全没有 —— 所以必须扫所有标签，不能只看工作标签。
    """
    for pg in ctx.pages:
        u = pg.url or ""
        if not u.startswith(("http://", "https://")):
            continue
        mk = sniff_no_access(pg)
        if mk:
            return mk, u
    return None, ""


def parse_checklist(path: Path) -> tuple[list[dict], str]:
    entries, cur, pub, dest = [], {}, None, ""
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if m := DEST_RE.match(s):
            dest = m.group(1).strip()
        elif m := PUB_RE.match(s):
            pub = m.group(1).strip()
        elif m := TITLE_RE.match(s):
            if cur.get("url"):
                entries.append(cur)
            cur = {"n": int(m.group(1)), "title": m.group(2), "year": m.group(3), "pub": pub}
        elif m := URL_RE.match(s):
            cur["url"] = m.group(1)
        elif m := NAME_RE.match(s):
            cur["name"] = m.group(1).strip()
    if cur.get("url"):
        entries.append(cur)
    for e in entries:
        d = DOI_RE.search(e["url"])
        e["doi"] = d.group(1) if d else e["url"]
    return entries, dest


# ── 下载记录库 ──
def db_rows(hist: Path, since_id: int = 0) -> list[tuple[int, str]]:
    """[(id, target_path)]，只取 state=1 的。"""
    try:
        con = sqlite3.connect(f"file:{hist.as_posix()}?immutable=1", uri=True)
        try:
            return con.execute(
                "SELECT id, target_path FROM downloads WHERE state=1 AND id > ? ORDER BY id",
                (since_id,)).fetchall()
        finally:
            con.close()
    except Exception:
        return []


def db_max_id(hist: Path) -> int:
    try:
        con = sqlite3.connect(f"file:{hist.as_posix()}?immutable=1", uri=True)
        try:
            return con.execute("SELECT COALESCE(MAX(id),0) FROM downloads").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return -1


def archive(src: Path, dest_dir: Path, name: str) -> tuple[bool, str]:
    """把 src 归档到 dest_dir/name，校验 %PDF-。返回 (ok, 说明)。"""
    try:
        out = dest_dir / sanitize(name)
        if out.exists() and out.stat().st_size == src.stat().st_size:
            return True, f"已存在同大小文件，跳过：{out.name}"
        shutil.copy2(src, out)
        with out.open("rb") as f:
            head = f.read(5)
        ok = head.startswith(b"%PDF-")
        # 源在 Playwright 临时目录里就清掉（那是垃圾）
        if "playwright-artifacts" in str(src).lower():
            try:
                src.unlink()
            except Exception:
                pass
        return ok, f"{out}  {out.stat().st_size}B" + ("" if ok else "  ❌不是PDF")
    except Exception as e:
        return False, f"归档失败：{e!r}"


def tidy_tabs(ctx, keep):
    """只保留工作标签。

    专用 profile 里其余标签都是"上一篇点开 PDF 留下的查看器页"。必须清掉，
    否则多标签 sniff 会拿**上一篇**的付费墙标记来判定**这一篇**（会连环误判）。
    """
    for pg in list(ctx.pages):
        if pg is keep:
            continue
        try:
            pg.close()
        except Exception:
            pass
    try:
        keep.bring_to_front()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="人工下载循环（可选扩展·默认关闭；脚本翻页，人点下载）")
    ap.add_argument("--list", required=True)
    ap.add_argument("--dest", default="", help="目标目录（省略则用清单里的「目标目录」）")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--timeout", type=int, default=180, help="单篇无下载的最长等待秒数")
    ap.add_argument("--no-access-grace", type=int, default=20,
                    help="识别出无权限后再等几秒就跳过（留给你反悔/强行下载）")
    ap.add_argument("--state", default="dl_state.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-input", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--enable-manual-loop", action="store_true",
                    help="确认有权访问并自担风险，启用本扩展（默认关闭）")
    args = ap.parse_args()

    if not manual_loop_enabled(args.enable_manual_loop):
        print("【本扩展默认关闭 · 合规考虑】")
        print("它不下载任何东西 —— 每一篇都由你亲手点；但确实会驱动浏览器访问")
        print("出版商站点，而 Elsevier/IOP/RSC/ACS 的条款禁止自动化程序访问其网站。")
        print("确认对该内容有访问权、并自担风险后，任选其一启用：")
        print(f'  1) 在 {SETTINGS_PATH} 写入  {{"manual_browser_loop_enabled": true}}')
        print("  2) 或运行时加参数 --enable-manual-loop")
        return 3

    hist = Path(args.profile) / "Default" / "History"
    ents, dest_from_list = parse_checklist(Path(args.list))
    dest = Path(args.dest or dest_from_list or ".")
    print(f"清单：{len(ents)} 条   目标目录：{dest}")
    print(f"下载记录库：{hist}  (存在={hist.exists()})")
    print(f"库中已有 {len(db_rows(hist))} 条完成记录，最大 id={db_max_id(hist)}\n")

    state_path = Path(args.state)
    done = set()
    if state_path.exists():
        try:
            done = set(json.loads(state_path.read_text(encoding="utf-8")).get("done", []))
        except Exception:
            pass
    todo = [e for e in ents if e["doi"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"已完成 {len(done)}，待处理 {len(todo)}\n")
    if args.dry_run:
        for e in todo:
            print(f"  [{e['n']:>2}] {e['pub']:<12} {e['title'][:56]}")
        return 0
    if not todo:
        print("没有待处理项。")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    def save_state():
        state_path.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        except Exception as e:
            print(f"连不上 Edge（端口 {args.port}）：{e}")
            return 2
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        cmd = {"v": None}
        interactive = sys.stdin.isatty() and not args.no_input

        def reader():
            while True:
                try:
                    cmd["v"] = input().strip().lower()
                except EOFError:
                    return

        if interactive:
            threading.Thread(target=reader, daemon=True).start()
        else:
            print("（无交互终端：靠下载记录自动推进）")

        print("已连上 Edge。判定=轮询 Edge 下载记录库；文件由脚本归档到目标目录。")
        print("操作：文章页点 View PDF → 预览器里点【下载】。存哪不用管。\n")

        try:
            for i, e in enumerate(todo, 1):
                print(f"── [{i}/{len(todo)}] #{e['n']} {e['pub']} ──────────────")
                print(f"   {e['title']}\n   {e['url']}")

                tidy_tabs(ctx, page)          # 清掉上一篇的残留标签，避免误判
                base = db_max_id(hist)
                try:
                    page.goto(e["url"], wait_until="domcontentloaded", timeout=60_000)
                except Exception as ex:
                    print(f"   导航异常（仍可手动处理）：{ex}")

                page.wait_for_timeout(1500)          # 等页面渲染稳定
                flagged = False
                eff = args.timeout

                cmd["v"] = None
                t0, tick, res = time.time(), 0, None
                while True:
                    page.wait_for_timeout(300)
                    tick += 1
                    if tick % 4 == 0:
                        hits = db_rows(hist, base)
                        if hits:
                            res = "db"
                            break
                        if not flagged:
                            mk, where = sniff_all(ctx)
                            if mk:
                                flagged = True
                                eff = min(eff, (time.time() - t0) + args.no_access_grace)
                                print(f"   ⚠ 疑似无权限（「{mk}」出现于 {where[:70]}）"
                                      f"→ {args.no_access_grace}s 后跳过（未记完成，下次还会来）")
                    c = cmd["v"]
                    if c is not None:
                        res = "skip" if c.startswith("s") else ("quit" if c.startswith("q") else "enter")
                        cmd["v"] = None
                        break
                    if time.time() - t0 > eff:
                        res = "timeout"
                        break

                if res == "quit":
                    print("\n退出（进度已保存）。")
                    break
                if res == "db":
                    ok_all = True
                    for _, tp in hits:
                        src = Path(tp)
                        if not src.exists():
                            print(f"   ⚠ 记录里的文件不存在：{tp}")
                            ok_all = False
                            continue
                        ok, msg = archive(src, dest, e.get("name", ""))
                        print(f"   {'✓' if ok else '✗'} {msg}")
                        ok_all = ok_all and ok
                    if ok_all:
                        done.add(e["doi"])
                        save_state()
                        print("   → 下一篇")
                        tidy_tabs(ctx, page)
                    else:
                        print("   ⚠ 有文件没归好，未记完成；回车仍可强制推进")
                elif res == "enter":
                    done.add(e["doi"])
                    save_state()
                    print("   ✓ 回车确认 → 下一篇")
                    tidy_tabs(ctx, page)
                elif res == "skip":
                    print("   ⊘ 跳过（未记完成）")
                else:
                    if not interactive:
                        print("   ⏱ 超时 → 跳过（无交互终端）")
                        continue
                    print("   ⏱ 超时 —— 回车继续 / s 跳过 / q 退出")
                    cmd["v"] = None
                    while cmd["v"] is None:
                        page.wait_for_timeout(300)
                    if cmd["v"].startswith("q"):
                        break
                    if not cmd["v"].startswith("s"):
                        done.add(e["doi"])
                        save_state()
                        print("   ✓ 记为完成")
        except KeyboardInterrupt:
            print("\n中断（进度已保存）。")
        finally:
            save_state()

    print(f"\n本轮结束。累计完成 {len(done)}/{len(ents)}。文件都在：{dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
