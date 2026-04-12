"""GitHub Models Client — Free LLMs via the GitHub Models API."""

from __future__ import annotations

import os

from agent_framework.openai import OpenAIChatCompletionClient

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"


def create_client(
    model: str | None = None,
    token: str | None = None,
) -> OpenAIChatCompletionClient:
    """Create an OpenAI-compatible client for GitHub Models.

    Reads GITHUB_TOKEN and GITHUB_MODEL from the environment
    if not explicitly provided.
    """
    token = token or os.environ.get("GITHUB_TOKEN", "")
    model = model or os.environ.get("GITHUB_MODEL", "gpt-4o")

    if not token:
        raise ValueError(
            "GITHUB_TOKEN not set. Create a GitHub PAT with 'models:read' scope: "
            "https://github.com/settings/tokens"
        )

    return OpenAIChatCompletionClient(
        api_key=token,
        model=model,
        base_url=GITHUB_MODELS_ENDPOINT,
    )
