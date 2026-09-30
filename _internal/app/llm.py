"""Klient lokalnego serwera Ollama (http://localhost:11434). Bez kluczy API, bez opłat."""
from __future__ import annotations

import json
import re
import threading
from typing import Callable, Optional

import requests


class LLMError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class Ollama:
    def __init__(self, url: str = "http://localhost:11434"):
        self.url = url.rstrip("/")

    def is_running(self) -> bool:
        try:
            return requests.get(self.url + "/api/version", timeout=2).ok
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            r = requests.get(self.url + "/api/tags", timeout=5)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except Exception:
            return []

    def has_model(self, model: str) -> bool:
        names = self.list_models()
        if model in names:
            return True
        if ":" not in model:
            return f"{model}:latest" in names
        return False

    def pull(self, model: str, progress: Optional[Callable[[str, float], None]] = None,
             cancel: Optional[threading.Event] = None) -> None:
        import time
        last = 0.0
        with requests.post(self.url + "/api/pull", json={"model": model, "stream": True}, stream=True, timeout=(10, 600)) as r:
            if not r.ok:
                raise LLMError(f"Nie udało się pobrać modelu {model}: {r.text[:300]}")
            for line in r.iter_lines():
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if not line:
                    continue
                d = json.loads(line)
                if "error" in d:
                    raise LLMError(d["error"])
                total, done = d.get("total") or 0, d.get("completed") or 0
                now = time.monotonic()
                if progress and (now - last > 0.25 or d.get("status") == "success"):
                    last = now
                    progress(d.get("status", ""), (done / total) if total else -1)

    def chat(self, model: str, messages: list[dict], *, num_ctx: int = 16384, temperature: float = 0.3,
             json_mode: bool = False, on_token: Optional[Callable[[str], None]] = None,
             cancel: Optional[threading.Event] = None, keep_alive: str = "10m") -> str:
        payload = {
            "model": model, "messages": messages, "stream": True, "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature, "repeat_penalty": 1.1},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            r = requests.post(self.url + "/api/chat", json=payload, stream=True, timeout=(10, 900))
        except requests.ConnectionError as e:
            raise LLMError("Brak połączenia z Ollamą. Czy Ollama jest uruchomiona?") from e
        out = []
        with r:
            if not r.ok:
                raise LLMError(f"Ollama zwróciła błąd {r.status_code}: {r.text[:300]}")
            for line in r.iter_lines():
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if not line:
                    continue
                d = json.loads(line)
                if "error" in d:
                    raise LLMError(d["error"])
                tok = d.get("message", {}).get("content", "")
                if tok:
                    out.append(tok)
                    if on_token:
                        on_token(tok)
                if d.get("done"):
                    break
        return _THINK_RE.sub("", "".join(out)).strip()

    def unload(self, model: str) -> None:
        try:
            requests.post(self.url + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
        except Exception:
            pass
