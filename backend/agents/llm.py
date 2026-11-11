
"""Configurable LLM provider interface.

Local Ollama (default), optional external API (OFF unless explicitly
configured), or no provider. Callers must always have a deterministic
fallback. A paid API is never used unless LLM_API_ENABLED=true and
the required URL and key are configured.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from decimal import Decimal

from backend.core.http import HttpError, HttpTimeout, http_json

log = logging.getLogger("llm")


class LLMError(Exception):
    """Base class for LLM errors."""


class LLMTimeout(LLMError):
    """The LLM did not respond within the configured deadline."""


class LLMUnavailable(LLMError):
    """The configured LLM provider is unavailable."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0
    cost_usd: Decimal | None = None


class NullProvider:
    name, model = "none", None

    def generate(self, system: str, user: str, timeout: float) -> LLMResponse:
        raise LLMUnavailable(
            "No LLM provider is configured; using deterministic templates."
        )

    def is_available(self) -> bool:
        return False


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        try:
            http_json(
                "GET",
                f"{self.base_url}/api/tags",
                timeout=2,
            )
            return True
        except HttpError:
            return False

    def generate(
        self,
        system: str,
        user: str,
        timeout: float,
    ) -> LLMResponse:
        start = time.monotonic()

        body = {
            "model": self.model,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 384,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            _, data = http_json(
                "POST",
                f"{self.base_url}/api/chat",
                body,
                timeout=timeout,
            )
        except HttpTimeout as e:
            raise LLMTimeout(str(e)) from None
        except HttpError as e:
            raise LLMUnavailable(
                f"Ollama not reachable: {type(e).__name__}"
            ) from None

        response_text = (data.get("message") or {}).get("content")

        if not isinstance(response_text, str):
            raise LLMError(
                "Ollama returned an unexpected response shape"
            )

        return LLMResponse(
            text=response_text,
            provider=self.name,
            model=self.model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=Decimal("0"),
        )


class ApiProvider:
    """OpenAI-compatible API.

    Sends redacted text to a third party and may incur charges.
    """

    name = "api"

    def __init__(self, url: str, key: str, model: str):
        if not (url and key and model):
            raise LLMUnavailable(
                "External API requires LLM_API_URL, "
                "LLM_API_KEY and LLM_API_MODEL"
            )

        self.url = url
        self._key = key
        self.model = model

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        system: str,
        user: str,
        timeout: float,
    ) -> LLMResponse:
        start = time.monotonic()

        body = {
            "model": self.model,
            "stream": False,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            _, data = http_json(
                "POST",
                self.url,
                body,
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self._key}"
                },
            )
        except HttpTimeout as e:
            raise LLMTimeout(str(e)) from None
        except HttpError as e:
            raise LLMUnavailable(
                f"API not reachable: {type(e).__name__}"
            ) from None

        try:
            response_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(
                "API returned an unexpected response shape"
            ) from None

        usage = data.get("usage") or {}

        return LLMResponse(
            text=response_text,
            provider=self.name,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=None,
        )


class FakeProvider:
    """Scripted provider for tests and demos."""

    name, model = "fake", "fake-model"

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.prompts = []

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        system: str,
        user: str,
        timeout: float,
    ) -> LLMResponse:
        self.prompts.append((system, user))

        if not self.script:
            raise LLMError("FakeProvider has no scripted responses")

        item = self.script[
            min(self.calls, len(self.script) - 1)
        ]
        self.calls += 1

        if isinstance(item, tuple) and item[0] == "sleep":
            time.sleep(item[1])
            item = item[2] if len(item) > 2 else "{}"

        if isinstance(item, Exception):
            raise item

        return LLMResponse(
            text=item,
            provider=self.name,
            model=self.model,
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=1,
            cost_usd=Decimal("0"),
        )


def build_provider(settings):
    kind = settings.llm_provider

    if kind == "ollama":
        return OllamaProvider(
            settings.ollama_url,
            settings.ollama_model,
        )

    if kind == "api":
        if not settings.llm_api_enabled:
            log.warning(
                "LLM_PROVIDER=api but LLM_API_ENABLED is not true; "
                "no external calls will be made"
            )
            return NullProvider()

        return ApiProvider(
            settings.llm_api_url,
            settings.llm_api_key,
            settings.llm_api_model,
        )

    return NullProvider()


def call_with_deadline(
    provider,
    system: str,
    user: str,
    timeout: float,
) -> LLMResponse:
    """Enforce a hard wall-clock deadline."""

    executor = ThreadPoolExecutor(max_workers=1)

    try:
        future = executor.submit(
            provider.generate,
            system,
            user,
            timeout,
        )

        return future.result(timeout=timeout)

    except FutureTimeout:
        raise LLMTimeout(
            f"No answer within {timeout} seconds"
        ) from None

    finally:
        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )
