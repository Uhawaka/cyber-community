"""LLM client — supports DeepSeek, OpenAI-compatible APIs."""

import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _load_secret(name: str) -> str:
    """Resolve a secret with project-local .env winning over stale shell env.

    Priority:
      1. <project>/.env
      2. process environment
      3. ~/.hermes/.env
    """
    project_val = _parse_dotenv(PROJECT_ROOT / ".env").get(name, "")
    if project_val:
        return project_val
    env_val = os.environ.get(name, "")
    if env_val:
        return env_val
    return _parse_dotenv(Path.home() / ".hermes" / ".env").get(name, "")


class LLM:
    """Thin wrapper around LLM APIs."""

    def __init__(self, config: dict):
        cfg = config.get("llm", config)  # support both top-level and nested
        provider = cfg.get("provider") or _load_secret("LLM_PROVIDER") or "deepseek"
        self.model = cfg.get("model") or _load_secret("LLM_MODEL") or "deepseek-chat"
        self.base_url = (
            cfg.get("base_url")
            or _load_secret(f"{provider.upper()}_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.temperature = cfg.get("temperature", 0.8)
        self.max_tokens = cfg.get("max_tokens", 2000)

        env_key = f"{provider.upper()}_API_KEY"
        self.api_key = _load_secret(env_key)
        if not self.api_key:
            raise RuntimeError(
                f"No API key found. Set {env_key} in project .env, "
                f"environment, or ~/.hermes/.env (see .env.example)"
            )

        self.call_count = 0
        self.error_count = 0

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send a chat request and return the response text."""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        body = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": self.max_tokens,
        }

        url = f"{self.base_url}/chat/completions"
        last_err: Exception | None = None
        for attempt in range(3):
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read())
                self.call_count += 1
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                last_err = RuntimeError(f"LLM API error {e.code}: {error_body[:500]}")
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                self.error_count += 1
                raise last_err
            except Exception as e:
                last_err = RuntimeError(f"LLM request failed: {e}")
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                self.error_count += 1
                raise last_err
        self.error_count += 1
        raise last_err or RuntimeError("LLM request failed")

    def think(
        self,
        character_name: str,
        prompt: str,
        temperature: Optional[float] = None,
        speech_language: str = "zh",
    ) -> str:
        """Convenience: one-shot prompt with character context."""
        from engine.language import think_system
        system = think_system(character_name, speech_language)
        return self.chat([{"role": "user", "content": prompt}], system=system, temperature=temperature)
