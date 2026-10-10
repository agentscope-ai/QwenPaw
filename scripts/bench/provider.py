# -*- coding: utf-8 -*-
"""Resolve dispatch provider and model overrides without reading secrets."""

import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .common import load, save


def selection(value: str) -> list[str]:
    """Resolve configured defaults or an explicit provider selection."""
    catalog = load(Path(f".github/bench/providers.yaml"))
    if value == f"default":
        selected = [
            key for key, spec in catalog.items() if spec.get(f"default")
        ]
    elif value == f"all":
        selected = list(catalog)
    else:
        selected = list(dict.fromkeys(p.strip() for p in value.split(f",")))
    if not selected or any(not provider for provider in selected):
        raise ValueError(f"Configure default providers or select provider IDs")
    return selected


def _provider_spec(provider: str, base_url: str, secret_name: str) -> dict:
    """Resolve a provider without accepting inline credentials."""
    catalog = load(Path(f".github/bench/providers.yaml"))
    spec = copy.deepcopy(catalog.get(provider, {}))
    if not re.fullmatch(rf"[a-zA-Z0-9_.-]+", provider):
        raise ValueError(f"Invalid provider ID")
    spec[f"original_url"] = spec.get(f"base_url")
    if base_url:
        spec[f"base_url"] = base_url
    if secret_name:
        spec[f"secret_name"] = secret_name
    endpoint = urlsplit(spec.get(f"base_url", f""))
    if (
        endpoint.scheme != f"https"
        or not endpoint.hostname
        or any(
            (
                endpoint.username,
                endpoint.password,
                endpoint.query,
                endpoint.fragment,
            ),
        )
    ):
        raise ValueError(
            f"Provider requires an HTTPS endpoint without credentials",
        )
    if not re.fullmatch(rf"[A-Z_][A-Z0-9_]*", spec.get(f"secret_name", f"")):
        raise ValueError(f"Provider requires a Bench secret name, not a key")
    if spec[f"secret_name"].startswith((f"GITHUB_", f"ACTIONS_")):
        raise ValueError(
            f"Reserved workflow tokens cannot be model credentials",
        )
    spec.setdefault(f"protocol", f"openai")
    return spec


def _model_cards(defaults: list, models: str, model_options: str) -> list:
    """Validate selected model capabilities and generation options."""
    known = {m[f"id"]: m for m in defaults}
    selected = (
        list(known)
        if models == f"all"
        else list(
            dict.fromkeys(m.strip() for m in models.split(f",")),
        )
    )
    if not selected:
        raise ValueError(f"Provider has no default models; specify model IDs")
    if any(
        not re.fullmatch(rf"[A-Za-z0-9][A-Za-z0-9_.:/-]{{0,159}}", m)
        or m == f"all"
        for m in selected
    ):
        raise ValueError(f"Invalid model selection")
    options = json.loads(model_options)
    if not isinstance(options, dict) or set(options) - set(selected):
        raise ValueError(f"Model options must reference selected model IDs")
    cards = []
    allowed = {
        f"supports_image",
        f"max_input_tokens",
        f"max_output_tokens",
        f"generate_kwargs",
    }
    for model in selected:
        card = copy.deepcopy(
            known.get(model, {f"id": model, f"supports_image": False}),
        )
        override = options.get(model, {})
        if not isinstance(override, dict) or set(override) - allowed:
            raise ValueError(f"Unsupported model option")
        card.update(override)
        if type(card[f"supports_image"]) is not bool:
            raise ValueError(f"supports_image must be boolean")
        for field in (f"max_input_tokens", f"max_output_tokens"):
            if field in card and (
                type(card[field]) is not int or card[field] <= 0
            ):
                raise ValueError(f"Token limits must be positive integers")
        if f"generate_kwargs" in card and not isinstance(
            card[f"generate_kwargs"],
            dict,
        ):
            raise ValueError(f"generate_kwargs must be an object")
        cards.append(card)
    return cards


def configured(
    source: Path,
    target: Path,
    *,
    provider: str,
    models: str,
    base_url: str = f"",
    secret_name: str = f"",
    model_options: str = f"{{}}",
    price_snapshot: str = f"",
) -> Path:
    """Materialize the effective checked configuration for manifest hashing."""
    spec = _provider_spec(provider, base_url, secret_name)
    settings = load(source / f"models.yaml")
    settings[f"models"] = _model_cards(
        spec.get(f"models", []),
        models,
        model_options,
    )
    settings[f"base_url"] = spec[f"base_url"]
    settings[f"provider"] = {
        f"id": provider,
        f"secret_name": spec[f"secret_name"],
        f"protocol": spec[f"protocol"],
    }
    pricing = price_snapshot or (
        spec.get(f"prices", f"")
        if spec[f"base_url"] == spec[f"original_url"]
        else f""
    )
    if pricing:
        path = Path(pricing).resolve()
        path.relative_to(Path.cwd().resolve())
        prices = load(path)
    else:
        prices = {
            f"version": f"unpriced",
            f"base_url": spec[f"base_url"],
            f"currency": f"USD",
            f"unit_tokens": 1000000,
            f"fx": {f"date": None, f"cny_per_usd": None},
            f"models": {},
        }
    suite = load(source / f"suite.yaml")
    if suite[f"harness"] == f"QwenPaw" and spec[f"protocol"] != f"openai":
        raise ValueError(
            f"QwenPaw runtime provider requires OpenAI-compatible API",
        )
    for name, value in (
        (f"models.yaml", settings),
        (f"prices.yaml", prices),
        (f"suite.yaml", suite),
        (f"harbor.yaml", load(source / f"harbor.yaml")),
    ):
        save(target / name, value)
    return target
