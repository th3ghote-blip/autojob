"""Thin Claude wrapper used by the research and letter agents."""
from __future__ import annotations

import os
from functools import lru_cache

from anthropic import Anthropic

DEFAULT_MODEL = "claude-opus-4-7"


@lru_cache(maxsize=1)
def client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def complete(*, system: str, user: str, model: str = DEFAULT_MODEL, max_tokens: int = 2000) -> dict:
    """Single-turn completion. Returns {'text': str, 'tokens_in': int, 'tokens_out': int, 'model': str}."""
    msg = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    return {
        "text": text,
        "tokens_in": msg.usage.input_tokens,
        "tokens_out": msg.usage.output_tokens,
        "model": model,
    }
