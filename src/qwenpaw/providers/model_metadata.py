# -*- coding: utf-8 -*-
"""Provider catalog lookup and exact model-name template selection."""

from __future__ import annotations

from dataclasses import dataclass

from .model_catalog import catalog_documents, matching_catalog_keys
from .model_info import ModelInfo


@dataclass(frozen=True)
class CatalogMatch:
    """Metadata with enough provenance to explain an automatic value."""

    model: ModelInfo
    source: str
    reference: str
    updated_at: str | None


def model_metadata(
    provider_id: str,
    base_url: str,
    model_id: str,
    template_id: str | None = None,
) -> list[CatalogMatch]:
    """Find service-specific records before exact original-owner templates."""
    endpoint = base_url.rstrip(f"/")
    matches: list[CatalogMatch] = []
    templates: dict[str, list[CatalogMatch]] = {}
    keys = matching_catalog_keys(
        provider_id,
        endpoint,
        model_id,
        template_id,
    )
    for document, source in catalog_documents(keys):
        for key, provider in document.providers.items():
            exact_endpoint = endpoint in {
                url.rstrip(f"/") for url in provider.api_urls
            }
            service_match = exact_endpoint or (
                key == provider_id and not provider.api_urls
            )
            for model in provider.models:
                reference = f"{key}/{model.id}"
                if service_match and model.id == model_id:
                    matches.append(
                        CatalogMatch(
                            model,
                            source,
                            reference,
                            document.published_at,
                        )
                    )
                eligible_template = provider.template_owner and (
                    provider.template_model_ids is None
                    or model.id in provider.template_model_ids
                )
                if eligible_template and (
                    reference == template_id
                    if template_id
                    else model.id == model_id
                ):
                    templates.setdefault(reference, []).append(
                        CatalogMatch(
                            model,
                            f"template",
                            reference,
                            document.published_at,
                        )
                    )
    # A name shared by multiple owners is ambiguous, never first-match wins.
    template_matches = (
        next(iter(templates.values())) if len(templates) == 1 else []
    )
    return list(reversed(matches)) + list(reversed(template_matches))


def list_model_templates() -> list[dict[str, str]]:
    """List original-owner templates without importing service settings."""
    templates = {}
    for document, _ in catalog_documents():
        for key, provider in document.providers.items():
            if provider.template_owner:
                for model in provider.models:
                    if (
                        provider.template_model_ids is not None
                        and model.id not in provider.template_model_ids
                    ):
                        continue
                    reference = f"{key}/{model.id}"
                    templates[reference] = {
                        f"id": reference,
                        f"name": model.name,
                        f"model_id": model.id,
                        f"provider_id": key,
                    }
    return list(templates.values())


def provider_catalog_models(
    provider_id: str, base_url: str
) -> list[ModelInfo]:
    """Load the complete service shard for its candidate pool."""
    endpoint = base_url.rstrip(f"/")
    keys = matching_catalog_keys(provider_id, endpoint, f"", None)
    models = {}
    for document, _ in catalog_documents(keys):
        for key, entry in document.providers.items():
            if key != provider_id and endpoint not in {
                url.rstrip(f"/") for url in entry.api_urls
            }:
                continue
            for model in entry.models:
                models[model.id] = model
    return list(models.values())
