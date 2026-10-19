#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小 HTTP 层 —— 仅用标准库，接口兼容本 skill 用到的 requests 子集。

为什么不用 requests
------------------
很多 Agent 宿主（DeepSeek Harness、容器、沙箱）自带精简 Python，
没有 requests。本 skill 只用到很少的几个能力，用 urllib 实现即可，
从而做到「零第三方依赖、任何 Python 3.10+ 都能跑」。

支持的接口（刻意保持与 requests 一致，调用处无需改写）
----------------------------------------------------
    Session()
        .headers                  普通 dict，可 update / 逐项赋值
        .get / .post / .delete / .request
        .close()
    requests.get(url, headers=..., timeout=..., data=..., allow_redirects=...)

    Response
        .status_code  .content  .text  .json()
        .headers      .url      .ok    .raise_for_status()
        .iter_content(chunk_size)

    exceptions: RequestException / Timeout / ConnectionError / HTTPError

不支持（本 skill 未使用）：stream=、proxies=、verify=、auth=、files=。
需要时再加，不要假装支持。
"""
from __future__ import annotations

import gzip
import json as _json
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.cookiejar import CookieJar


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class RequestException(Exception):
    pass


class Timeout(RequestException):
    pass


class ConnectionError(RequestException):  # noqa: A001 - 有意与 requests 同名
    pass


class HTTPError(RequestException):
    pass


# ---------------------------------------------------------------------------
# 响应
# ---------------------------------------------------------------------------
class CaseInsensitiveDict(dict):
    """HTTP 头不区分大小写。

    注意：必须重写 __init__。dict 的 C 层构造会绕过 __setitem__，
    导致直接 CaseInsensitiveDict(mapping) 时键没有归一化。
    """

    def __init__(self, data=None, **kw):
        super().__init__()
        if data:
            for k, v in dict(data).items():
                self[k] = v
        for k, v in kw.items():
            self[k] = v

    def _k(self, key):
        return key.lower() if isinstance(key, str) else key

    def __getitem__(self, key):
        return super().__getitem__(self._k(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._k(key), value)

    def __contains__(self, key):
        return super().__contains__(self._k(key))

    def get(self, key, default=None):
        return super().get(self._k(key), default)

    def pop(self, key, *a):
        return super().pop(self._k(key), *a)

    def update(self, *a, **kw):
        for k, v in dict(*a, **kw).items():
            self[k] = v


def _decode_body(body: bytes, headers: dict) -> bytes:
    """按 Content-Encoding 解压。urllib 不会替你做这件事。"""
    ce = headers.get("Content-Encoding", "").lower().strip()
    if ce == "gzip":
        try:
            return gzip.decompress(body)
        except OSError:
            return body
    if ce == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                return body
    return body


class Response:
    def __init__(self, status_code: int, content: bytes,
                 headers: dict, url: str) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = CaseInsensitiveDict(headers or {})
        self.url = url
        self.encoding = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        if self.encoding:
            return self.content.decode(self.encoding, "replace")
        charset = ""
        ct = self.headers.get("Content-Type", "")
        for part in ct.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip("\"'")
                break
        if charset:
            try:
                return self.content.decode(charset, "replace")
            except LookupError:
                pass
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("latin-1", "replace")

    def json(self):
        # JSON 一律按 UTF-8 解（RFC 8259），不要被错误的 charset 带偏
        try:
            return _json.loads(self.content.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return _json.loads(self.text)

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def raise_for_status(self) -> None:
        if 400 <= self.status_code:
            raise HTTPError(f"{self.status_code} error for url: {self.url}")

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"<Response [{self.status_code}]>"


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Session:
    def __init__(self) -> None:
        self.headers = CaseInsensitiveDict()
        self.cookies = CookieJar()
        self._openers: dict[bool, urllib.request.OpenerDirector] = {}

    def _opener(self, allow_redirects: bool):
        if allow_redirects not in self._openers:
            handlers = [urllib.request.HTTPCookieProcessor(self.cookies)]
            if not allow_redirects:
                handlers.append(_NoRedirect())
            self._openers[allow_redirects] = urllib.request.build_opener(*handlers)
        return self._openers[allow_redirects]

    def request(self, method: str, url: str, *,
                headers: dict | None = None,
                timeout=None,
                data=None,
                json=None,
                params: dict | None = None,
                allow_redirects: bool = True,
                **_ignored) -> Response:
        if params:
            sep = "&" if urllib.parse.urlparse(url).query else "?"
            url = url + sep + urllib.parse.urlencode(params, doseq=True)

        body = None
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            headers = {"Content-Type": "application/json", **(headers or {})}
        elif data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
                headers = {"Content-Type": "application/x-www-form-urlencoded",
                           **(headers or {})}
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = data

        merged = {"Accept-Encoding": "identity"}
        merged.update(self.headers)
        if headers:
            merged.update(headers)

        req = urllib.request.Request(url, data=body, method=method.upper())
        for k, v in merged.items():
            req.add_header(k, str(v))

        if isinstance(timeout, (tuple, list)):
            timeout = max(float(x) for x in timeout if x is not None) or None
        elif timeout is not None:
            timeout = float(timeout)

        try:
            with self._opener(allow_redirects).open(req, timeout=timeout) as r:
                raw = r.read()
                hdrs = dict(r.headers.items())
                status = getattr(r, "status", 200)
                final_url = r.geturl()
        except urllib.error.HTTPError as e:
            raw = e.read()
            hdrs = dict(e.headers.items()) if e.headers else {}
            status = e.code
            final_url = url
        except socket.timeout as e:
            raise Timeout(str(e)) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                raise Timeout(str(e.reason)) from e
            raise ConnectionError(str(e.reason)) from e
        except OSError as e:
            raise ConnectionError(str(e)) from e

        hdrs = CaseInsensitiveDict(hdrs)
        return Response(status, _decode_body(raw, hdrs), hdrs, final_url)

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)

    def head(self, url: str, **kw) -> Response:
        return self.request("HEAD", url, **kw)

    def delete(self, url: str, **kw) -> Response:
        return self.request("DELETE", url, **kw)

    def close(self) -> None:
        self._openers.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# 模块级便捷函数（每次新建 Session，与 requests 行为一致）
# ---------------------------------------------------------------------------
def get(url: str, **kw) -> Response:
    with Session() as s:
        return s.get(url, **kw)


def post(url: str, **kw) -> Response:
    with Session() as s:
        return s.post(url, **kw)


def head(url: str, **kw) -> Response:
    with Session() as s:
        return s.head(url, **kw)


def delete(url: str, **kw) -> Response:
    with Session() as s:
        return s.delete(url, **kw)


class exceptions:  # noqa: N801 - 模仿 requests.exceptions
    RequestException = RequestException
    Timeout = Timeout
    ConnectionError = ConnectionError
    HTTPError = HTTPError
