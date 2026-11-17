# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared resolution of model-endpoint env var triplets.

Every triplet (``REASONING``, ``NON_REASONING``, ``EMBED``, ``RERANK``) exposes
three fields — ``ENDPOINT`` (URL), ``API_KEY``, and ``MODEL`` — as
``<PREFIX>_<FIELD>`` env vars. Any field left unset falls back to the
corresponding ``DEFAULT_MODELS_<FIELD>``, so a single ``DEFAULT_MODELS_*`` triplet
can supply the shared endpoint/key/model for all of them. Each field also falls
back to its legacy pre-triplet env var name (``NVIDIA_API_KEY`` / ``BASE_URL`` /
``MODEL_NAME``) for backward compatibility.

When even ``DEFAULT_MODELS_<FIELD>`` is unset, a built-in default is used. There
are two sets — one for ``sk-`` inference-api keys and one for ``nvapi-``
integrate/build.nvidia.com keys — and the set is chosen from the API key that
applies to the same triplet.
"""

from __future__ import annotations

import os

# Built-in endpoint/model defaults, selected by the triplet's API key prefix.
# Keyed by ``<PREFIX>_<FIELD>``. API keys are intentionally absent (they have no
# safe hardcoded default and fall back to ``DEFAULT_MODELS_API_KEY`` /
# ``NVIDIA_API_KEY`` instead).
_DEFAULTS_BY_KEY_PREFIX: dict[str, dict[str, str]] = {
    # inference-api.nvidia.com (sk-... keys).
    "sk-": {
        "REASONING_ENDPOINT": "https://inference-api.nvidia.com/v1",
        "REASONING_MODEL": "azure/anthropic/claude-opus-5-5",
        "NON_REASONING_ENDPOINT": "https://inference-api.nvidia.com/v1",
        "NON_REASONING_MODEL": "azure/anthropic/claude-opus-5-5",
        "EMBED_ENDPOINT": "https://inference-api.nvidia.com/v1",
        "EMBED_MODEL": "nvidia/nvidia/nemotron-3.5-embed-1b-nvfp4",
        "RERANK_ENDPOINT": "https://inference-api.nvidia.com/v1/rerank",
        "RERANK_MODEL": "nvidia/nvidia/nemotron-3.5-rerank-8b-bf16",
    },
    # integrate.api.nvidia.com / build.nvidia.com (nvapi-... keys).
    "nvapi-": {
        "REASONING_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "REASONING_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "NON_REASONING_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "NON_REASONING_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "EMBED_ENDPOINT": "https://integrate.api.nvidia.com/v1",
        "EMBED_MODEL": "nvidia/nemotron-3.5-embed-1b",
        "RERANK_ENDPOINT": (
            "https://ai.api.nvidia.com/v1/retrieval/nvidia/"
            "nemotron-3.5-rerank-8b/reranking"
        ),
        "RERANK_MODEL": "nvidia/nemotron-3.5-rerank-8b",
    },
}

# Default set to use when the API key matches no known prefix (or is unset).
_FALLBACK_KEY_PREFIX = "sk-"


# Legacy (pre-triplet) env var names, still honored so existing deployments and
# --set nvidiaApiKey / BASE_URL / MODEL_NAME configs keep working.
_LEGACY_ENV: dict[str, str] = {
    "API_KEY": "NVIDIA_API_KEY",
    "ENDPOINT": "BASE_URL",
    "MODEL": "MODEL_NAME",
}


def _default(field: str) -> str:
    """Shared default for *field*: ``DEFAULT_MODELS_<field>`` then the legacy name."""
    value = os.environ.get(f"DEFAULT_MODELS_{field}", "")
    if not value and field in _LEGACY_ENV:
        value = os.environ.get(_LEGACY_ENV[field], "")
    return value


def _resolve_api_key(prefix: str) -> str:
    """Effective API key for *prefix* (own env var, else the shared default)."""
    return os.environ.get(f"{prefix}_API_KEY", "") or _default("API_KEY")


def _builtin_default(prefix: str, key: str) -> str:
    """Built-in default for ``<prefix>_<field>``, chosen by the key prefix."""
    api_key = _resolve_api_key(prefix)
    for key_prefix, defaults in _DEFAULTS_BY_KEY_PREFIX.items():
        if api_key.startswith(key_prefix):
            return defaults.get(key, "")
    return _DEFAULTS_BY_KEY_PREFIX[_FALLBACK_KEY_PREFIX].get(key, "")


def resolve(prefix: str, field: str) -> str:
    """Resolve one triplet field.

    Order of precedence: the ``<prefix>_<field>`` env var, then the shared
    ``DEFAULT_MODELS_<field>``, then a built-in default chosen by whether the
    triplet's API key is an ``sk-`` or ``nvapi-`` key.
    """
    key = f"{prefix}_{field}"
    return os.environ.get(key, "") or _default(field) or _builtin_default(prefix, key)


# Chat-client families selectable with ``<PREFIX>_CLIENT`` /
# ``DEFAULT_MODELS_CLIENT``. ``nvidia`` is ChatNVIDIA (the default);
# ``openai`` is the stock OpenAI client for OpenAI-compatible gateways such as
# Volcengine ARK that do not implement the NVIDIA endpoint catalogue
# (``/v1/models`` probing, NVIDIA parameter names).
_CLIENT_ALIASES: dict[str, str] = {
    "nvidia": "nvidia",
    "chatnvidia": "nvidia",
    "openai": "openai",
    "openai-compatible": "openai",
    "openai_compatible": "openai",
    "chatopenai": "openai",
}

# Endpoint signatures that unambiguously identify a non-NVIDIA OpenAI-compatible
# gateway. Volcengine ARK serves ``https://ark.<region>.volces.com/api/v3``; the
# ``/api/v3`` path is ARK's OpenAI-compatible mount across its regions.
_OPENAI_COMPATIBLE_HOST_SUFFIXES = ("volces.com",)
_OPENAI_COMPATIBLE_PATH_PARTS = ("/api/v3",)


def _infer_client(endpoint: str) -> str:
    """Infer the chat-client family from *endpoint* when ``*_CLIENT`` is unset."""
    if not endpoint:
        return "nvidia"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
    except ValueError:
        return "nvidia"
    host = (parsed.hostname or "").lower()
    if any(host.endswith(suffix) for suffix in _OPENAI_COMPATIBLE_HOST_SUFFIXES):
        return "openai"
    path = parsed.path.rstrip("/")
    if any(
        path == part.rstrip("/") or path.endswith(part)
        for part in _OPENAI_COMPATIBLE_PATH_PARTS
    ):
        return "openai"
    return "nvidia"


def resolve_client(prefix: str) -> str:
    """Resolve the chat-client family for *prefix*.

    Order of precedence: the ``<prefix>_CLIENT`` env var, then the shared
    ``DEFAULT_MODELS_CLIENT``, then inference from the triplet's endpoint
    (OpenAI-compatible gateways such as Volcengine ARK), then ``"nvidia"``.
    Unknown values fall back to inference rather than silently selecting a
    non-existent client.
    """
    raw = (
        (
            os.environ.get(f"{prefix}_CLIENT", "")
            or os.environ.get("DEFAULT_MODELS_CLIENT", "")
        )
        .strip()
        .lower()
    )
    if raw in _CLIENT_ALIASES:
        return _CLIENT_ALIASES[raw]
    return _infer_client(resolve(prefix, "ENDPOINT"))
