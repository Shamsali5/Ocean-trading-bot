"""Minimal HTTP helpers with a requests-like interface."""

from __future__ import annotations

import json as json_lib
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class RequestException(RuntimeError):
    """Network-layer exception compatible with requests-style usage."""


@dataclass
class _Response:
    _body: bytes
    status_code: int

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return json_lib.loads(self._body.decode("utf-8"))

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RequestException(f"HTTP error status {self.status_code}")


def _perform(request: Request, timeout: int) -> _Response:
    try:
        with urlopen(request, timeout=timeout) as raw:
            status = getattr(raw, "status", 200)
            body = raw.read()
            return _Response(_body=body, status_code=int(status))
    except HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return _Response(_body=body, status_code=int(exc.code))
    except URLError as exc:
        raise RequestException(str(exc.reason)) from exc
    except OSError as exc:
        raise RequestException(str(exc)) from exc


def get(url: str, params: dict | None = None, timeout: int = 30) -> _Response:
    query = urlencode(params or {})
    full_url = f"{url}?{query}" if query else url
    request = Request(full_url, method="GET")
    return _perform(request, timeout=timeout)


def post(url: str, json: dict | None = None, timeout: int = 30) -> _Response:
    payload = json or {}
    body = json_lib.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _perform(request, timeout=timeout)
