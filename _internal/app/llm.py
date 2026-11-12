"""Klient lokalnego serwera Ollama (http://localhost:11434). Bez kluczy API, bez opłat."""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable, Optional

import requests
from .i18n import tr


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
        had = self.has_model(model)          # model pobrany już wcześniej (np. przez kogoś innego) – nie jest „nasz”
        self._pull(model, progress, cancel)
        if not had:
            from .setup.state import remember
            remember("ollama_models", model)

    def _pull(self, model: str, progress, cancel) -> None:
        last = 0.0
        with requests.post(self.url + "/api/pull", json={"model": model, "stream": True}, stream=True, timeout=(10, 600)) as r:
            if not r.ok:
                raise LLMError(tr("Nie udało się pobrać modelu {model}: {x}", model=model, x=r.text[:300]))
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
             cancel: Optional[threading.Event] = None, keep_alive: str = "10m",
             num_predict: Optional[int] = None, stop_json: bool = False) -> str:
        """num_predict – limit długości odpowiedzi (tokeny). stop_json=True – przerwij, gdy główny obiekt JSON
        się zamknie (z format=json modele potrafią potem sypać puste znaki aż do końca kontekstu).
        Statystyki ostatniego wywołania (czasy, tokeny) – w self.last_stats."""
        payload = {
            "model": model, "messages": messages, "stream": True, "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature, "repeat_penalty": 1.1},
        }
        if num_predict:
            payload["options"]["num_predict"] = int(num_predict)
        if json_mode:
            payload["format"] = "json"
        t0 = time.monotonic()
        self.last_stats = st = {"chars": sum(len(str(m.get("content", ""))) for m in messages), "num_ctx": num_ctx}
        try:
            r = requests.post(self.url + "/api/chat", json=payload, stream=True, timeout=(10, 900))
        except requests.ConnectionError as e:
            raise LLMError(tr("Brak połączenia z Ollamą. Czy Ollama jest uruchomiona?")) from e
        out = []
        scan = JsonEnd() if stop_json else None
        try:
            self._stream(r, out, st, t0, scan, on_token, cancel)
        finally:
            st["total_s"] = time.monotonic() - t0
        return _THINK_RE.sub("", "".join(out)).strip()

    @staticmethod
    def _stream(r, out, st, t0, scan, on_token, cancel) -> None:
        with r:
            if not r.ok:
                raise LLMError(tr("Ollama zwróciła błąd {status_code}: {x}", status_code=r.status_code, x=r.text[:300]))
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
                    if "first_s" not in st:
                        st["first_s"] = time.monotonic() - t0      # ładowanie + czytanie promptu
                    st["chunks"] = st.get("chunks", 0) + 1        # ~ liczba wygenerowanych tokenów
                    out.append(tok)
                    if on_token:
                        on_token(tok)
                    if scan is not None and scan.feed(tok):
                        st["stopped_json"] = True
                        break
                if d.get("done"):
                    for k in ("prompt_eval_count", "eval_count", "done_reason"):
                        if k in d:
                            st[k] = d[k]
                    for k in ("load_duration", "prompt_eval_duration", "eval_duration"):
                        if d.get(k):
                            st[k.replace("_duration", "_s")] = d[k] / 1e9
                    break

    def unload(self, model: str) -> None:
        try:
            requests.post(self.url + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
        except Exception:
            pass

    def loaded(self) -> list[dict]:
        """Modele załadowane teraz w Ollamie (/api/ps)."""
        try:
            r = requests.get(self.url + "/api/ps", timeout=5)
            r.raise_for_status()
            return [m for m in r.json().get("models", []) if isinstance(m, dict)]
        except Exception:
            return []

    def unload_others(self, keep: str) -> list[str]:
        """Zwolnij z pamięci wszystkie modele oprócz keep – żeby model zadania zmieścił się na karcie graficznej."""
        out = []
        for m in self.loaded():
            name = m.get("name") or m.get("model") or ""
            if name and name != keep:
                self.unload(name)
                out.append(name)
        return out

    def preload(self, model: str, num_ctx: int, keep_alive: str = "30m") -> float:
        """Załaduj model z podanym num_ctx (pusty prompt); zwraca czas w sekundach. Ten sam num_ctx trzeba potem
        trzymać w całym zadaniu, inaczej Ollama przeładuje model."""
        t0 = time.monotonic()
        try:
            requests.post(self.url + "/api/generate",
                          json={"model": model, "prompt": "", "keep_alive": keep_alive, "stream": False,
                                "options": {"num_ctx": num_ctx, "num_predict": 1}}, timeout=(10, 600)).close()
        except Exception:
            pass
        return time.monotonic() - t0


class JsonEnd:
    """Śledzi strumień tekstu; feed() zwraca True, gdy zamknął się pierwszy obiekt/tablica JSON (napisy pomija)."""

    def __init__(self):
        self.depth = 0
        self.started = False
        self.in_str = False
        self.esc = False

    def feed(self, text: str) -> bool:
        for ch in text:
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif ch == "\\":
                    self.esc = True
                elif ch == '"':
                    self.in_str = False
            elif ch == '"':
                self.in_str = True
            elif ch in "{[":
                self.depth += 1
                self.started = True
            elif ch in "}]":
                self.depth -= 1
                if self.started and self.depth <= 0:
                    return True
        return False
