"""Text model adapter for OpenAI-compatible chat-completion APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_LOCAL_PROVIDERS = frozenset({"ollama", "local"})
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def strip_model_extras(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def assistant_text(message: dict[str, object] | None) -> str:
    msg = message or {}
    raw = str(msg.get("content") or "").strip()
    if not raw:
        raw = str(msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
    return strip_model_extras(raw)


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _load_secret(name: str) -> str:
    return (
        _parse_dotenv(PROJECT_ROOT / ".env").get(name, "")
        or os.environ.get(name, "")
        or _parse_dotenv(Path.home() / ".hermes" / ".env").get(name, "")
    )


class OpenAICompatibleTextModel:
    """Explicitly configured model with observable request/error budgets."""

    def __init__(self, config: dict[str, object]) -> None:
        nested = config.get("llm", config)
        if not isinstance(nested, dict):
            raise ValueError("model config must be a JSON object")
        provider = str(nested.get("provider") or _load_secret("LLM_PROVIDER") or "deepseek").lower()
        self.provider = provider
        self.temperature = float(nested.get("temperature", 0.8))
        self.max_tokens = int(nested.get("max_tokens", 2000))
        self.request_count = 0
        self.call_count = 0
        self.error_count = 0

        if provider in _LOCAL_PROVIDERS:
            self.model = str(nested.get("model") or _load_secret("OLLAMA_MODEL") or "qwen3.8")
            self.base_url = str(
                nested.get("base_url")
                or _load_secret("OLLAMA_BASE_URL")
                or "http://127.0.0.1:11434/v1"
            ).rstrip("/")
            self.api_key = str(nested.get("api_key") or _load_secret("OLLAMA_API_KEY") or "ollama")
        else:
            self.model = str(nested.get("model") or _load_secret("LLM_MODEL") or "deepseek-chat")
            self.base_url = str(
                nested.get("base_url")
                or _load_secret(f"{provider.upper()}_BASE_URL")
                or "https://api.deepseek.com"
            ).rstrip("/")
            env_key = f"{provider.upper()}_API_KEY"
            self.api_key = str(nested.get("api_key") or _load_secret(env_key))
            if not self.api_key:
                raise RuntimeError(f"No API key found. Set {env_key} explicitly or in an env file")

    def complete(self, prompt: str, timeout_seconds: float | None = None) -> str:
        return self.chat(
            [{"role": "user", "content": prompt}],
            timeout_seconds=timeout_seconds,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        temperature: float | None = None,
        think: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        full_messages: list[dict[str, str]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        body: dict[str, object] = {
            "model": self.model,
            "messages": full_messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        if self.provider in _LOCAL_PROVIDERS:
            body["think"] = bool(think)
            if not think:
                body["reasoning_effort"] = "none"

        timeout = timeout_seconds or (300.0 if self.provider in _LOCAL_PROVIDERS else 120.0)
        last_error: Exception | None = None
        self.request_count += 1
        for attempt in range(3):
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    data = json.loads(response.read())
                self.call_count += 1
                return assistant_text(data["choices"][0].get("message"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode() if exc.fp else str(exc)
                last_error = RuntimeError(f"LLM API error {exc.code}: {error_body[:500]}")
                if exc.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_error = RuntimeError(f"LLM request failed: {exc}")
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
        self.error_count += 1
        raise last_error or RuntimeError("LLM request failed")

    @property
    def budget(self) -> dict[str, int]:
        return {
            "requests": self.request_count,
            "successful_calls": self.call_count,
            "errors": self.error_count,
        }
