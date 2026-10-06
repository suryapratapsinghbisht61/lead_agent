"""Model factory: returns LangChain chat models based on .env settings.

The rest of the code never knows whether it is talking to Gemini, Ollama or
anything else. Switching models = editing .env.

get_llms() returns [main model, *fallback models]. Free tiers have small DAILY
quotas per model, so when one model is used up, the agent moves on to the next
(see structured_call in app/agent/utils.py).
"""

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter

from app.core.config import get_settings


def _build(model: str) -> BaseChatModel:
    s = get_settings()

    # Provider-specific connection settings.
    extra: dict = {}
    if s.llm_provider == "google_genai":
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is empty. Add it to .env (see .env.example).")
        extra["google_api_key"] = s.google_api_key
    elif s.llm_provider == "ollama":
        extra["base_url"] = s.ollama_base_url
        extra["num_ctx"] = 8192  # Ollama's default context is small; our prompts include page text

    # Free tiers limit requests per minute. This limiter makes every call wait
    # its turn instead of failing with a 429 "rate limit exceeded" error.
    rate_limiter = InMemoryRateLimiter(
        requests_per_second=s.llm_requests_per_minute / 60,
        check_every_n_seconds=0.2,
        max_bucket_size=1,  # no bursts: spread calls evenly
    )

    return init_chat_model(
        model,
        model_provider=s.llm_provider,
        rate_limiter=rate_limiter,
        max_retries=2,  # built-in retry with backoff on temporary API errors
        **extra,
    )


@lru_cache  # one shared set of models (and rate limiters) per process
def get_llms() -> list[BaseChatModel]:
    s = get_settings()
    names = [s.llm_model] + [m.strip() for m in s.llm_fallback_models.split(",") if m.strip()]
    return [_build(name) for name in dict.fromkeys(names)]  # dict.fromkeys = drop duplicates, keep order


def get_llm() -> BaseChatModel:
    """Just the main model (used by scripts/check_llm.py)."""
    return get_llms()[0]
