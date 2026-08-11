"""LLM client — supports DeepSeek, OpenAI-compatible APIs."""

import os
import json
import urllib.request
import urllib.error
from typing import Optional


class LLM:
    """Thin wrapper around LLM APIs."""

    def __init__(self, config: dict):
        cfg = config.get("llm", config)  # support both top-level and nested
        self.model = cfg.get("model", "deepseek-chat")
        self.base_url = cfg.get("base_url", "https://api.deepseek.com").rstrip("/")
        self.temperature = cfg.get("temperature", 0.8)
        self.max_tokens = cfg.get("max_tokens", 2000)

        # API key: from env or .env
        provider = cfg.get("provider", "deepseek")
        env_key = f"{provider.upper()}_API_KEY"
        self.api_key = os.environ.get(env_key, "")
        if not self.api_key:
            # Try reading from ~/.hermes/.env
            env_path = os.path.expanduser("~/.hermes/.env")
            if os.path.exists(env_path):
                for line in open(env_path):
                    if line.startswith(env_key):
                        self.api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not self.api_key:
            raise RuntimeError(
                f"No API key found. Set {env_key} in environment or ~/.hermes/.env"
            )

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
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            raise RuntimeError(f"LLM API error {e.code}: {error_body[:500]}")
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}")

    def think(self, character_name: str, prompt: str, temperature: Optional[float] = None) -> str:
        """Convenience: one-shot prompt with character context."""
        system = f"You are {character_name}. Respond in character, in Chinese."
        return self.chat([{"role": "user", "content": prompt}], system=system, temperature=temperature)
