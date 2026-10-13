"""Model access: one OpenAI-compatible chat endpoint, with a response cache.

Any server that implements POST {base_url}/chat/completions works: a local
Ollama (http://localhost:11434/v1), a hosted provider of open-weight models, or
a LiteLLM gateway. The model is chosen in the environment, never in the code:

    AUDITIQ_LLM_BASE_URL   e.g. http://localhost:11434/v1
    AUDITIQ_LLM_MODEL      exact model identifier, recorded with every result
    AUDITIQ_LLM_API_KEY    optional for a local server

Every response is stored in a SQLite cache keyed by the full request, so a
repeated run costs nothing and returns the same text. The m agreement re-runs
of one prompt differ in their ``sample`` number, which is part of the key.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from .config import load_env
from .policy import PROJECT_ROOT

DEFAULT_CACHE = PROJECT_ROOT / ".auditiq" / "llm_cache.sqlite"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 600.0
    max_tokens: int = 700
    json_mode: bool = True       # send response_format={"type": "json_object"}
    send_seed: bool = True       # send the sample number as "seed"
    max_retries: int = 5
    extra_body: dict = field(default_factory=dict)
    # Context window of the server, in tokens. When set, a prompt that would not
    # fit is refused instead of being sent: some servers (a local Ollama with its
    # default 4,096 tokens) cut an oversize prompt without saying so.
    context_tokens: int | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = PROJECT_ROOT / ".env") -> "LLMSettings":
        load_env(env_file)
        base_url, model = os.environ.get("AUDITIQ_LLM_BASE_URL"), os.environ.get("AUDITIQ_LLM_MODEL")
        if not base_url or not model:
            raise RuntimeError(
                "No model is configured. Set AUDITIQ_LLM_BASE_URL and AUDITIQ_LLM_MODEL "
                "(see .env.example); configuration C1 needs no model.")
        flag = lambda name, default: os.environ.get(name, default).strip().lower() not in ("0", "false", "no")  # noqa: E731
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=os.environ.get("AUDITIQ_LLM_API_KEY", ""),
            timeout=float(os.environ.get("AUDITIQ_LLM_TIMEOUT", "600")),
            max_tokens=int(os.environ.get("AUDITIQ_LLM_MAX_TOKENS", "700")),
            json_mode=flag("AUDITIQ_LLM_JSON_MODE", "1"),
            send_seed=flag("AUDITIQ_LLM_SEND_SEED", "1"),
            extra_body=json.loads(os.environ.get("AUDITIQ_LLM_EXTRA_BODY", "{}")),
            context_tokens=int(os.environ["AUDITIQ_LLM_CONTEXT"]) if os.environ.get("AUDITIQ_LLM_CONTEXT") else None,
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False


class ChatClient(Protocol):
    model: str

    def complete(self, messages: list[dict], *, temperature: float = 0.0, sample: int = 0) -> LLMResponse: ...


class ResponseCache:
    """Responses keyed by the SHA-256 of the request. Safe to share between threads."""

    def __init__(self, path: Path | str = DEFAULT_CACHE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, model TEXT, request TEXT, text TEXT,"
            " prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms REAL, created_at TEXT)")
        self._db.commit()

    @staticmethod
    def key(request: dict) -> str:
        return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def get(self, request: dict) -> LLMResponse | None:
        with self._lock:
            row = self._db.execute(
                "SELECT text, prompt_tokens, completion_tokens, latency_ms FROM responses WHERE key = ?",
                (self.key(request),)).fetchone()
        return None if row is None else LLMResponse(row[0], row[1], row[2], row[3], cached=True)

    def put(self, request: dict, response: LLMResponse) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.key(request), request.get("model"), json.dumps(request, ensure_ascii=False), response.text,
                 response.prompt_tokens, response.completion_tokens, response.latency_ms,
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self._db.commit()

    def close(self) -> None:
        self._db.close()


class LLMError(RuntimeError):
    pass


class OpenAIChatClient:
    """Chat completions over HTTP, with retries on rate limits and server errors."""

    def __init__(self, settings: LLMSettings, cache: ResponseCache | None = None,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.model = settings.model
        self.cache = cache
        self._sleep = sleep
        headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
        self._http = httpx.Client(base_url=settings.base_url, headers=headers, timeout=settings.timeout,
                                  transport=transport)

    def _body(self, messages: list[dict], temperature: float, sample: int) -> dict:
        s = self.settings
        body = {"model": s.model, "messages": messages, "temperature": temperature, "max_tokens": s.max_tokens}
        if s.json_mode:
            body["response_format"] = {"type": "json_object"}
        if s.send_seed:
            body["seed"] = sample
        body.update(s.extra_body)
        return body

    def complete(self, messages: list[dict], *, temperature: float = 0.0, sample: int = 0) -> LLMResponse:
        body = self._body(messages, temperature, sample)
        limit = self.settings.context_tokens
        if limit:
            # 2.7 characters per token is cautious: the densest prompts measured on
            # this pipeline (tables of invoice numbers and amounts) had 2.8.
            needed = int(sum(len(m["content"]) for m in messages) / 2.7) + self.settings.max_tokens
            if needed > limit:
                raise LLMError(f"the prompt needs about {needed} tokens with its reply, more than the context "
                               f"of {limit} tokens (AUDITIQ_LLM_CONTEXT); raise the server's context or shorten the input")
        # The sample number is part of the key even when it is not sent as a seed.
        request = {"base_url": self.settings.base_url, "sample": sample, **body}
        if self.cache is not None:
            hit = self.cache.get(request)
            if hit is not None:
                log.debug("%s: reply from the cache", self.settings.model)
                return hit
        response = self._post(body)
        log.info("%s: %d tokens in, %d out, %.1f s", self.settings.model, response.prompt_tokens,
                 response.completion_tokens, response.latency_ms / 1000)
        if self.cache is not None:
            self.cache.put(request, response)
        return response

    def _post(self, body: dict) -> LLMResponse:
        last = ""
        for attempt in range(self.settings.max_retries + 1):
            started = time.perf_counter()
            try:
                reply = self._http.post("/chat/completions", json=body)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if reply.status_code == 200:
                    data = reply.json()
                    usage = data.get("usage") or {}
                    return LLMResponse(
                        text=data["choices"][0]["message"].get("content") or "",
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                        latency_ms=round((time.perf_counter() - started) * 1000, 1))
                last = f"HTTP {reply.status_code}: {reply.text[:300]}"
                if reply.status_code not in (408, 409, 429) and reply.status_code < 500:
                    raise LLMError(f"{self.settings.base_url} rejected the request ({last})")
                retry_after = reply.headers.get("retry-after", "")
                if retry_after.replace(".", "", 1).isdigit():
                    self._sleep(min(float(retry_after), 120.0))
                    continue
            log.warning("%s: attempt %d of %d failed (%s)", self.settings.base_url, attempt + 1,
                        self.settings.max_retries + 1, last[:200])
            self._sleep(min(2.0 ** attempt, 60.0))
        raise LLMError(f"{self.settings.base_url} failed after {self.settings.max_retries + 1} attempts ({last})")

    def close(self) -> None:
        self._http.close()


class ScriptedClient:
    """A stand-in for tests: ``responder(messages, temperature, sample)`` returns the reply text.

    It makes no network call and must never be used to produce a result.
    """

    model = "scripted-test-double"

    def __init__(self, responder: Callable[[list[dict], float, int], str]):
        self._responder = responder
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def complete(self, messages: list[dict], *, temperature: float = 0.0, sample: int = 0) -> LLMResponse:
        with self._lock:
            self.calls.append({"messages": messages, "temperature": temperature, "sample": sample})
        text = self._responder(messages, temperature, sample)
        return LLMResponse(text=text, prompt_tokens=sum(len(m["content"]) for m in messages) // 4,
                           completion_tokens=len(text) // 4, latency_ms=1.0)


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict:
    """The first JSON object in a model reply.

    Tolerates a reasoning block, a Markdown code fence and prose around the
    object. Raises ValueError when the reply contains no JSON object.
    """
    cleaned = _THINK.sub("", text or "")
    decoder = json.JSONDecoder()
    position = cleaned.find("{")
    while position != -1:
        try:
            value, _ = decoder.raw_decode(cleaned, position)
        except json.JSONDecodeError:
            position = cleaned.find("{", position + 1)
            continue
        if isinstance(value, dict):
            return value
        position = cleaned.find("{", position + 1)
    raise ValueError("the reply contains no JSON object")
