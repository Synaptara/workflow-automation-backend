import requests

from . import register
from .base import BaseExecutor

DEFAULT_MODEL = "openai/gpt-oss-20b"

# Groq retired these model IDs. Workflows saved before the shutdown still carry
# the old ID in their stored config, so remap instead of failing with a 404.
DEPRECATED_MODELS = {
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "qwen/qwen3-32b": "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct": "openai/gpt-oss-120b",
}


@register("groq_ai")
class GroqAIExecutor(BaseExecutor):
    def execute(self, config: dict, context: dict) -> dict:
        api_key = config.get("api_key")
        prompt = config.get("prompt")

        if not api_key or not prompt:
            raise ValueError("Groq AI requires an API key and a prompt.")

        # Empty/missing -> default; retired ID -> its replacement; otherwise as given.
        model = (config.get("model") or "").strip() or DEFAULT_MODEL
        model = DEPRECATED_MODELS.get(model, model)

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": str(prompt)}],
            "temperature": 0.5,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)

        if not resp.ok:
            error_message = resp.text
            try:
                error_message = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise ValueError(f"Groq API Error ({resp.status_code}): {error_message}")

        data = resp.json()
        reply = data["choices"][0]["message"]["content"]

        # "model" reports what was actually used, not what was stored in config.
        return {"reply": reply, "model": model, "usage": data.get("usage", {})}
