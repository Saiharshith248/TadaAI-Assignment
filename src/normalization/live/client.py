"""Minimal HTTP client for the organizer's demo sign-in service and provider APIs.

Read-only GETs only. Secrets (API key, tokens, session ids) are never logged or
written; snapshots contain provider response bodies only. Standard library only.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SIGNIN_URL = "https://tada-demo-provider-signin.onrender.com/signin"
TENANTS = {"prismhr": "prism", "isolved": "isol", "ukg-ready": "ukg"}


class LiveError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if Path("/etc/ssl/cert.pem").exists():   # macOS python.org builds ship without a CA bundle
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


def load_api_key(env_file: Optional[Path] = None) -> str:
    key = os.environ.get("DEMO_SIGNIN_API_KEY")
    if key:
        return key.strip()
    path = env_file or Path.cwd() / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip().removeprefix("export ").strip() == "DEMO_SIGNIN_API_KEY":
                    return v.strip().strip("'\"")
    raise LiveError("DEMO_SIGNIN_API_KEY not set (environment or .env)")


class _Spinner:
    """Single-line progress indicator on stderr (only when attached to a terminal)."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label_fn):
        self._label, self._stop = label_fn, threading.Event()
        self._t = None

    def __enter__(self):
        if sys.stderr.isatty():
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def _run(self):
        start, i = time.time(), 0
        while not self._stop.wait(0.1):
            sys.stderr.write(f"\r{self.FRAMES[i % len(self.FRAMES)]} {self._label()} ({time.time() - start:.0f}s)\033[K")
            sys.stderr.flush()
            i += 1

    def __exit__(self, *exc):
        if self._t:
            self._stop.set()
            self._t.join()
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


class Session:
    """Signed-in provider session; re-signs-in once on 401 (tokens are short-lived)."""

    def __init__(self, provider: str, api_key: str, verbose: bool = True):
        self.provider, self.tenant, self._key, self.verbose = provider, TENANTS[provider], api_key, verbose
        self._ctx = _ssl_context()
        self.calls = 0
        self.signin()

    # -- transport
    def _http(self, method: str, url: str, headers: Dict[str, str], body: Any = None, timeout: int = 120) -> Tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ctx) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else ""
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]

    def signin(self) -> None:
        with _Spinner(lambda: f"[{self.provider}] signing in (demo server may be waking up)"):
            status, body = self._http("POST", SIGNIN_URL, {"X-API-Key": self._key}, {"tenant": self.tenant}, timeout=180)
        if status != 200 or not isinstance(body, dict):
            raise LiveError(f"sign-in for {self.tenant} failed with HTTP {status}")
        auth = body.get("auth") or {}
        self._token = auth.get("sessionId") or auth.get("access_token")
        usage = body.get("usage") or {}
        self._header = (usage.get("header_name") or "Authorization", usage.get("header_prefix") or "")
        self.base_url = body["base_url"].rstrip("/")
        self.tenant_id = body.get("tenant_id")
        self.context = body.get("context") or {}

    def get(self, path: str, **params: Any) -> Tuple[int, Any]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        url = f"{url}{'&' if '?' in url else '?'}{query}" if query else url
        for attempt in (1, 2):
            name, prefix = self._header
            with _Spinner(lambda: f"[{self.provider}] fetching... {self.calls} API calls done"):
                status, body = self._http("GET", url, {name: prefix + self._token})
            self.calls += 1
            if status == 401 and attempt == 1:
                self.signin()
                continue
            if status == 429 and attempt == 1:
                time.sleep(5)
                continue
            return status, body
        return status, body

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{self.provider}] {msg}", file=sys.stderr)
