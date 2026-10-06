"""Prompt templates, one file per LLM step. Edit wording here, not in the node code."""

import yaml


def profile_text(profile: dict) -> str:
    """Render config/services.yaml as compact text for the system prompt."""
    return yaml.safe_dump(profile, sort_keys=False, allow_unicode=True).strip()
