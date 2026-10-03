#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper-fetch 体检：本机有哪些凭证、哪些通道可用、缺的怎么申请。

用法:
    python doctor.py            # 体检
    python doctor.py --guide    # 打印逐项申请指引
    python doctor.py --probe    # 额外实测各通道连通性（会发网络请求）
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    CRED_FILE, get, load_credentials, publisher_of, redact,
)

CREDS_TRUE = "OK"
CREDS_FALSE = "--"
WARN = "!!"


def section(t: str) -> None:
    print()
    print("=" * 68)
    print(t)
    print("=" * 68)


def check_credentials() -> dict[str, bool]:
    section("1. 凭证")
    creds = load_credentials()

    items = [
        ("wiley_tdm_token", "Wiley TDM token", "Wiley 官方 TDM API（推荐通道）", True),
        ("elsevier_api_key", "Elsevier API key", "仅元数据/摘要；全文另需权益", False),
        ("crossref_mailto", "Crossref mailto", "进礼貌池，降低 429 概率", False),
    ]
    status = {}
    for key, label, note, required_for_core in items:
        v = creds.get(key, "")
        status[key] = bool(v)
        mark = CREDS_TRUE if v else CREDS_FALSE
        print(f"  [{mark}] {label:22s} {redact(v)}")
        print(f"        {note}")

    print()
    print(f"  凭证文件: {CRED_FILE}")
    print(f"            {'存在' if CRED_FILE.exists() else '不存在（可用环境变量代替）'}")
    return status


def check_network() -> None:
    section("2. 网络出口")
    try:
        import requests
    except ImportError:
        print("  ! 未安装 requests，跳过。pip install requests")
        return

    for fam, name in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        try:
            s = socket.socket(fam, socket.SOCK_DGRAM)
            host = "8.8.8.8" if fam == socket.AF_INET else "2001:4860:4860::8888"
            s.connect((host, 53))
            print(f"  {name} 本机地址: {s.getsockname()[0]}")
            s.close()
        except Exception as e:
            print(f"  {name}: 不可用 ({str(e)[:40]})")

    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                print(f"  公网出口 IP: {r.text.strip()}   (via {url.split('//')[1][:24]})")
                break
        except Exception:
            continue
    else:
        print("  公网出口 IP: 检测失败（部分网络屏蔽此类服务，不代表断网）")

    print()
    print("  提示：机构常同时有教育网与商业 ISP 出口，且 IPv4/IPv6 可能走不同线路。")
    print("        有些出版商的 API 只支持 IPv4（无 AAAA 记录），此时 IPv6 用不上。")
    print("        判断权限请**实测能否下载**，不要靠 IP 归属推测。")


def probe_channels() -> None:
    section("3. 通道连通性实测（--probe）")
    try:
        import requests
    except ImportError:
        print("  未安装 requests，跳过")
        return

    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}

    # Crossref：零凭证通道的代表
    try:
        r = requests.get("https://api.crossref.org/works/10.1038/s41929-024-01131-6",
                         headers={"User-Agent": "paper-fetch-doctor/1.0"}, timeout=20)
        print(f"  [{'OK' if r.status_code == 200 else '!!'}] Crossref API          HTTP {r.status_code}")
    except Exception as e:
        print(f"  [!!] Crossref API          失败: {str(e)[:50]}")

    # MDPI CDN
    try:
        u = ("https://mdpi-res.com/d_attachment/materials/materials-16-00394/"
             "article_deploy/materials-16-00394.pdf")
        r = requests.get(u, headers=UA, timeout=30)
        ok = r.status_code == 200 and r.content[:5] == b"%PDF-"
        print(f"  [{'OK' if ok else '!!'}] MDPI CDN               HTTP {r.status_code} "
              f"{len(r.content)} B")
    except Exception as e:
        print(f"  [!!] MDPI CDN              失败: {str(e)[:50]}")

    # Wiley TDM
    tok = get("wiley_tdm_token")
    if tok:
        try:
            import wiley_tdm  # noqa: F401
            print(f"  [{CREDS_TRUE}] wiley-tdm 包          已安装")
        except ImportError:
            print(f"  [{WARN}] wiley-tdm 包          未安装：pip install wiley-tdm")
    else:
        print(f"  [{CREDS_FALSE}] Wiley TDM              缺 token，见 credentials.md")

    # Elsevier
    ek = get("elsevier_api_key")
    if ek:
        try:
            r = requests.get(
                "https://api.elsevier.com/content/abstract/doi/10.1016/j.jcou.2025.103019",
                headers={"X-ELS-APIKey": ek, "Accept": "application/json"}, timeout=30)
            print(f"  [{'OK' if r.status_code == 200 else '!!'}] Elsevier 摘要 API      HTTP {r.status_code}")
            r2 = requests.get(
                "https://api.elsevier.com/content/article/doi/10.1016/j.jcou.2025.103019",
                headers={"X-ELS-APIKey": ek, "Accept": "application/json"}, timeout=30)
            full_ok = r2.status_code == 200
            print(f"  [{'OK' if full_ok else '!!'}] Elsevier 全文 API      HTTP {r2.status_code}"
                  + ("" if full_ok else "   ← 缺全文权益，见 credentials.md"))
        except Exception as e:
            print(f"  [!!] Elsevier API          失败: {str(e)[:50]}")
    else:
        print(f"  [{CREDS_FALSE}] Elsevier API           缺 key，见 credentials.md")


def channel_summary(status: dict) -> None:
    section("4. 因此可用的通道")
    rows = [
        ("Springer 10.1007 / 10.1186", True, "零凭证 · Crossref TDM 链接"),
        ("Nature 10.1038", True, "零凭证 · Crossref TDM 链接"),
        ("MDPI 10.3390", True, "零凭证 · mdpi-res.com CDN"),
        ("Wiley 10.1002", status.get("wiley_tdm_token", False),
         "需 TDM token" if not status.get("wiley_tdm_token") else "官方 TDM API"),
        ("Elsevier 10.1016", status.get("elsevier_api_key", False),
         "需 API key + 全文权益" if not status.get("elsevier_api_key") else "查全文权益"),
        ("RSC 10.1039", False, "无自助通道 → 人工清单"),
        ("IOP 10.1149", False, "无自助通道 → 人工清单"),
        ("ACS 10.1021", False, "无免费通道 → 人工清单"),
    ]
    for name, ok, note in rows:
        print(f"  [{'OK' if ok else '--'}] {name:28s} {note}")
    print()
    print("  下一步：")
    print("    python gap_report.py    --xlsx <表.xlsx> --dest <目标目录>")
    print("    python fetch_crossref_tdm.py --xlsx <表.xlsx> --dest <目标目录>")
    if not status.get("wiley_tdm_token"):
        print("    python doctor.py --guide     # 看 Wiley token 怎么申请")


GUIDE = """
======================================================================
凭证申请指引
======================================================================

【Wiley TDM token】—— 自助，即时，推荐先办
  1. 用机构邮箱注册 Wiley Online Library 账号
  2. 打开 https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining
  3. 登录后领取 TDM API Token（UUID 格式）
  4. 存起来：
       export WILEY_TDM_TOKEN="<uuid>"
     或写进 ~/.paper-fetch/credentials.json 的 "wiley_tdm_token"
  注意：只支持 IP 鉴权，请求必须从机构登记的 IP 段内发出。
        全部 Access Denied 时找图书馆确认机构账号配了 IP 访问。

【Crossref mailto】—— 无需申请
  export CROSSREF_MAILTO="you@institution.edu"

【Elsevier API key】—— 自助，即时
  1. 用机构邮箱注册 https://account.elsevier.com/auth
  2. 打开 https://dev.elsevier.com/ → "I want an API Key"
  3. "Create API key" → 填 Label（不带空格）→ 同意两份协议 → Submit
  4. 在 "My API Key" 页面复制 key

【Elsevier 全文权益】—— 需人工审批，48-72 小时，可能被拒
  !! 这是关键：只拿到 API key 的话，摘要能取、全文一律 403。
     全文能力是受限 API，默认不开通，要单独申请。
  提交表单：https://www.elsevier.support/dataasaservice/contact
    Product 选  ScienceDirect APIs   （别选 ScienceDirect Journals Data）
    Your question 栏写清三件事：
      (1) 连 gold OA 文章也 403      → 排除"没订阅"
      (2) 同一 IP 在网站上能看全文    → 排除权益问题
      (3) 摘要接口返回 200           → 证明 key 有效
    详细模板见 references/credentials.md

【instToken】—— 必须由机构出面，个人申请不到
  1. 首选：让图书馆管理员用 AdminTool 生成
     https://www.elsevier.com/solutions/sciencedirect/support/admin-tool
  2. 备选：向 helpdesk 申请，需提供 CustomerID（图书馆知道）
     https://service.elsevier.com/app/contact/supporthub/sciencedirect/
  限制：只能 https、只能服务端保存、代表机构完整权限、Elsevier 可随时撤销。

======================================================================
安全提醒
======================================================================
 * 令牌只放环境变量或 ~/.paper-fetch/credentials.json，别写进脚本或仓库
 * 不要截图、不要在对话里完整打印；贴给第三方时用前4位+后4位
 * 本 skill 的任何文件都不含密钥，迁移设备后可安全复制
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="paper-fetch 体检")
    ap.add_argument("--guide", action="store_true", help="打印凭证申请指引")
    ap.add_argument("--probe", action="store_true", help="额外实测通道连通性")
    args = ap.parse_args()

    if args.guide:
        print(GUIDE)
        return 0

    print("paper-fetch 体检")
    status = check_credentials()
    check_network()
    if args.probe:
        probe_channels()
    channel_summary(status)

    if not status.get("wiley_tdm_token") or not status.get("crossref_mailto"):
        print()
        print("  有缺项 → python doctor.py --guide")
    return 0


if __name__ == "__main__":
    sys.exit(main())
