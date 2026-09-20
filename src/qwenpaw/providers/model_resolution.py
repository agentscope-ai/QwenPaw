# -*- coding: utf-8 -*-
"""Resolve token capabilities once for UI and runtime consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .context_windows import DEFAULT_CONTEXT_WINDOW, known_context_size
from .model_billing import effective_billing
from .model_info import ModelInfo
from .model_metadata import model_metadata
from .model_ranking import model_ranking

if TYPE_CHECKING:
    from .provider import Provider


def resolve_model_info(
    provider: Provider,
    model: ModelInfo,
    discovered: ModelInfo | None = None,
) -> ModelInfo:
    """Enrich a copy; automatic values never become persisted overrides."""
    result = ModelInfo.model_validate(model.model_dump())
    local = provider.is_local or not provider._context_catalog_enabled()
    matches = (
        []
        if local
        else model_metadata(
            provider.id,
            provider.base_url,
            model.id,
            result.template_id,
        )
    )
    provenance: dict[str, dict[str, Any]] = {}
    catalog_values = {}
    for field in (
        f"max_input_length",
        f"input_token_limit",
        f"max_output_length",
        f"supports_image",
        f"supports_video",
        f"supports_audio",
        f"supports_tool_calling",
        f"ranking_id",
        f"released_at",
        f"thinking_control",
    ):
        for match in matches:
            value = getattr(match.model, field)
            if field in match.model.model_fields_set and value is not None:
                catalog_values[field] = value
                origin = match.model.capability_provenance.get(field, {})
                provenance[field] = {
                    f"source": match.source,
                    f"reference": origin.get(f"reference", match.reference),
                    f"updated_at": origin.get(f"updated_at", match.updated_at),
                }
                break
    automatic = catalog_values.get(f"max_input_length")
    context_source = provenance.get(f"max_input_length", {}).get(f"source")
    if automatic is None:
        if (
            not result.max_input_length_configured
            and result.max_input_length != DEFAULT_CONTEXT_WINDOW
        ):
            automatic = result.max_input_length
            context_source = f"catalog"
        else:
            automatic = None if local else known_context_size(model.id)
            context_source = f"catalog" if automatic else f"default"
            automatic = automatic or DEFAULT_CONTEXT_WINDOW
    for candidate in (model, discovered):
        api_context = getattr(
            candidate,
            f"max_input_length_auto_detected",
            None,
        )
        if api_context and context_source != f"user":
            automatic, context_source = api_context, f"api"
            provenance[f"max_input_length"] = {
                f"source": f"api",
                f"reference": provider.base_url,
                f"updated_at": getattr(candidate, f"discovered_at", None),
            }
            break
    result.automatic_max_input_length = automatic
    result.effective_max_input_length = automatic
    result.context_length_source = context_source
    if result.max_input_length_configured:
        result.effective_max_input_length = result.max_input_length
        result.context_length_source = f"user"
        provenance[f"max_input_length"] = {f"source": f"user"}
    for field in (f"input_token_limit", f"max_output_length"):
        if discovered is not None and (
            getattr(result, f"{field}_source") != f"user"
            and getattr(discovered, field) is not None
            and getattr(discovered, f"{field}_source") == f"api"
        ):
            setattr(result, field, getattr(discovered, field))
            setattr(result, f"{field}_source", f"api")
        existing = getattr(result, field)
        source = getattr(result, f"{field}_source")
        if existing is not None and (
            source == f"user"
            or (
                source in {f"api", f"adapter"}
                and provenance.get(field, {}).get(f"source") != f"user"
            )
        ):
            provenance[field] = {
                f"source": source,
                f"reference": provider.base_url,
                f"updated_at": result.discovered_at,
            }
        elif field in catalog_values:
            setattr(result, field, catalog_values[field])
            setattr(result, f"{field}_source", provenance[field][f"source"])
        elif existing is not None:
            provenance[field] = {f"source": source}
    for field in (
        f"supports_image",
        f"supports_video",
        f"supports_audio",
        f"supports_tool_calling",
        f"ranking_id",
        f"released_at",
        f"thinking_control",
    ):
        if field in catalog_values and (
            getattr(result, field) is None
            or (
                field != f"released_at"
                and field not in result.config_overrides
                and result.probe_source != f"probed"
                and (
                    result.source != f"discovered"
                    or result.probe_source == f"documentation"
                )
            )
        ):
            setattr(result, field, catalog_values[field])
    # Endpoint evidence wins over cards, including an explicit paid change.
    if discovered is not None and discovered.billing != f"unknown":
        result.billing = discovered.billing
        result.billing_source = discovered.billing_source
        result.billing_checked_at = discovered.billing_checked_at
        result.pricing = dict(discovered.pricing)
        provenance[f"billing"] = {
            f"source": discovered.billing_source or f"api",
            f"reference": provider.base_url,
            f"updated_at": discovered.billing_checked_at,
        }
    if result.billing == f"unknown" or result.billing_source == f"catalog":
        for match in matches:
            if (
                match.source != f"template"
                and match.model.billing != f"unknown"
            ):
                result.billing = match.model.billing
                result.billing_source = f"catalog"
                result.billing_checked_at = match.model.billing_checked_at
                result.pricing = dict(match.model.pricing)
                provenance[f"billing"] = dict(
                    match.model.capability_provenance.get(
                        f"billing",
                        {f"source": f"catalog"},
                    ),
                )
                break
    if result.billing == f"unknown" and result.is_free:
        result.billing = f"free"
    result.billing = effective_billing(result)
    result.is_free = result.billing == f"free"
    if discovered is not None and discovered.probe_source == f"api":
        for field in (
            f"supports_image",
            f"supports_audio",
            f"supports_video",
            f"supports_tool_calling",
        ):
            if field not in result.config_overrides and (
                getattr(discovered, field) is not None
            ):
                setattr(result, field, getattr(discovered, field))
                provenance[field] = {
                    f"source": f"api",
                    f"reference": provider.base_url,
                    f"updated_at": discovered.discovered_at,
                }
    if discovered is not None and discovered.released_at:
        result.released_at = discovered.released_at
    result.ranking = model_ranking(result.ranking_id)
    modalities = (
        result.supports_image,
        result.supports_audio,
        result.supports_video,
    )
    if f"supports_multimodal" not in result.config_overrides:
        result.supports_multimodal = (
            True
            if True in modalities
            else False if all(value is False for value in modalities) else None
        )
    if result.input_token_limit is not None:
        result.automatic_max_input_length = min(
            result.automatic_max_input_length,
            result.input_token_limit,
        )
        if result.input_token_limit < result.effective_max_input_length:
            result.effective_max_input_length = result.input_token_limit
            result.context_length_source = result.input_token_limit_source
    output_provenance = provenance.get(f"max_output_length", {})
    if output_provenance.get(f"updated_at"):
        result.max_output_length_updated_at = output_provenance[f"updated_at"]
    result.capability_provenance = provenance
    return result
