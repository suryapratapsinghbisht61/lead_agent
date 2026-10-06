"""Check that the configured LLM works.

    uv run python scripts/check_llm.py                       # uses .env settings
    uv run python scripts/check_llm.py --provider ollama --model qwen2.5:3b
    uv run python scripts/check_llm.py --list-models         # Gemini models your key can use
"""

import argparse
import os
import time

from pydantic import BaseModel, Field


class Greeting(BaseModel):
    """Tiny schema to prove structured output works (the agent depends on it)."""

    message: str = Field(description="A one-sentence friendly greeting")
    language: str = Field(description="The language the greeting is written in")


def list_gemini_models() -> None:
    from google import genai

    from app.core.config import get_settings

    client = genai.Client(api_key=get_settings().google_api_key)
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name.removeprefix("models/"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", help="override LLM_PROVIDER")
    parser.add_argument("--model", help="override LLM_MODEL")
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    # Environment variables beat .env values, so this overrides settings for this run only.
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    if args.list_models:
        list_gemini_models()
        return

    from app.core.config import get_settings
    from app.services.llm import get_llm

    s = get_settings()
    print(f"Provider: {s.llm_provider}  Model: {s.llm_model}")
    llm = get_llm()

    start = time.perf_counter()
    reply = llm.invoke("Say hello in one short sentence.")
    print(f"\n1) Plain text ({time.perf_counter() - start:.1f}s):\n   {reply.text}")

    start = time.perf_counter()
    structured = llm.with_structured_output(Greeting).invoke("Greet a developer in Hindi.")
    print(f"\n2) Structured output ({time.perf_counter() - start:.1f}s):\n   {structured!r}")
    print("\nLLM OK")


if __name__ == "__main__":
    main()
