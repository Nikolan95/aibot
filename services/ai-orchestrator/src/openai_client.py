from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    model: str


def get_llm_config() -> LlmConfig:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    return LlmConfig(enabled=bool(key), model=model)


def llm_reply(*, model: str, system: str, user: str) -> str | None:
    """
    Returns a short assistant message, or None if OPENAI_API_KEY missing.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    # Import here so the service can still run without the dependency in some environments.
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=api_key)

    # Prefer Responses API when available; fall back to Chat Completions for SDKs without it.
    try:
        if hasattr(client, "responses"):
            resp = client.responses.create(  # type: ignore[attr-defined]
                model=model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            text = getattr(resp, "output_text", None)
            if isinstance(text, str) and text.strip():
                return text.strip()
            return None

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.6,
        )
        choice = resp.choices[0] if resp.choices else None
        content = getattr(getattr(choice, "message", None), "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        return None
    except Exception as exc:
        # Keep the worker resilient; just fall back to deterministic replies.
        # No secrets are logged.
        print("openai error:", repr(exc))
        return None
