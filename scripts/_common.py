#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper-fetch 共用工具：凭证读取、DOI 规范化、PDF 校验、编码修正。

凭证读取顺序（**本文件不含任何密钥**）：
    1. 环境变量
    2. ~/.paper-fetch/credentials.json
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

# --- 中文 Windows 控制台是 GBK，直接打印非 GBK 字符会 UnicodeEncodeError ---
for _s in ("stdout", "stderr"):
    try:
        setattr(sys, _s, io.TextIOWrapper(
            getattr(sys, _s).buffer, encoding="utf-8", errors="replace"))
    except Exception:
        pass

CRED_DIR = Path.home() / ".paper-fetch"
CRED_FILE = CRED_DIR / "credentials.json"

# 键名 → 环境变量名
ENV_KEYS = {
    "wiley_tdm_token": "WILEY_TDM_TOKEN",
    "elsevier_api_key": "ELSEVIER_API_KEY",
    "crossref_mailto": "CROSSREF_MAILTO",
}


# --------------------------------------------------------------------------
# 凭证
# --------------------------------------------------------------------------

def load_credentials() -> dict:
    """读取凭证。环境变量优先于文件。绝不打印值。"""
    creds: dict[str, str] = {}

    if CRED_FILE.exists():
        try:
            data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and v.strip():
                        creds[k] = v.strip()
        except Exception as e:
            print(f"[warn] 无法解析 {CRED_FILE}: {e}", file=sys.stderr)

    for key, env in ENV_KEYS.items():
        v = os.environ.get(env, "").strip()
        if v:
            creds[key] = v

    return creds


def get(key: str, default: str = "") -> str:
    return load_credentials().get(key, default)


def redact(value: str) -> str:
    """把凭证显示成可安全贴给第三方的形式。"""
    if not value:
        return "(未配置)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


def save_credentials(updates: dict) -> Path:
    """把新凭证合并进 credentials.json，并设权限 600。"""
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    cur = {}
    if CRED_FILE.exists():
        try:
            cur = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update({k: v for k, v in updates.items() if v})
    CRED_FILE.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(CRED_FILE, 0o600)
    except Exception:
        pass  # Windows 上基本无效，尽力而为
    return CRED_FILE


# --------------------------------------------------------------------------
# DOI / 文件
# --------------------------------------------------------------------------

def doi_tag(doi: str) -> str:
    """DOI → 安全文件名。10.1002/anie.123 → 10.1002_anie.123"""
    return re.sub(r"[^a-z0-9.]", "_", str(doi).strip().lower())


def norm_doi(doi: str) -> str:
    """剥掉 DOI 的 URL 外壳。"""
    d = str(doi).strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    return d.strip()


def valid_pdf(path) -> bool:
    """校验是不是真 PDF。别信 HTTP 200 —— 有些站点对无权内容返回 HTML 错误页。"""
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size < 20000:
            return False
        with p.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False


def publisher_of(doi: str) -> str:
    """DOI 前缀 → 出版商标签。"""
    pref = norm_doi(doi).split("/")[0]
    return {
        "10.1002": "Wiley", "10.1007": "Springer", "10.1186": "Springer",
        "10.1038": "Nature", "10.3390": "MDPI", "10.1016": "Elsevier",
        "10.1039": "RSC", "10.1149": "IOP", "10.1021": "ACS",
        "10.1080": "TaylorFrancis", "10.1093": "Oxford", "10.1126": "Science",
    }.get(pref, "?")


def safe_filename(name: str, limit: int = 150) -> str:
    """清成 Windows/macOS/Linux 都能用的文件名。"""
    import unicodedata
    n = unicodedata.normalize("NFC", str(name))
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", n)
    n = re.sub(r"\s+", " ", n).strip().rstrip(".")
    return n[:limit].strip()


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_doi_list(path) -> list[str]:
    """从 txt / csv / xlsx 里取 DOI 列表。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if p.suffix.lower() in (".xlsx", ".xls"):
        import pandas as pd
        df = pd.read_excel(p, header=0)
        col = next((c for c in df.columns if str(c).strip().lower() == "doi"), None)
        if col is None:
            raise ValueError(f"{p} 里找不到 DOI 列，实际列：{list(df.columns)[:10]}")
        return [norm_doi(d) for d in df[col].dropna().astype(str) if norm_doi(d)]

    text = p.read_text(encoding="utf-8", errors="replace")
    found = re.findall(r"10\.\d{4,9}/[^\s,;\"'<>\\)\]]+", text)
    return [norm_doi(x) for x in found]
