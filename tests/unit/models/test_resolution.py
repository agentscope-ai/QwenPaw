"""Private selection and server publication precedence."""

from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
async def test_private_override_and_trusted_publication_take_precedence():
    from qwenpaw.models.runtime import resolve_selection, TrustedPublication
    from tests.unit.models.test_governance import actor

    class Governance:
        async def require_model(self, actor, agent_id, provider_id, model):
            if model == "disabled":
                raise ValueError("disabled")
            return {
                "provider_id": provider_id,
                "model": model,
                "max_input_length": 32000,
            }

    manager = SimpleNamespace(
        get_provider=lambda _: SimpleNamespace(has_model=lambda _: True),
        get_active_model=lambda: {"provider_id": "p", "model": "global"},
    )
    config = SimpleNamespace(active_model={"provider_id": "p", "model": "agent"})
    service = Governance()
    result = await resolve_selection(
        service, actor(), "a", config, manager, {"provider_id": "p", "model": "private"}
    )
    assert (
        result["active_llm"]["model"] == "private"
        and result["source"] == "conversation"
    )
    result = await resolve_selection(
        service,
        actor(),
        "a",
        config,
        manager,
        None,
        TrustedPublication("p", "published"),
    )
    assert result["locked"] and result["active_llm"]["model"] == "published"
    with pytest.raises(ValueError, match="disabled"):
        await resolve_selection(
            service,
            actor(),
            "a",
            config,
            manager,
            {"provider_id": "p", "model": "disabled"},
        )


def test_client_publication_claims_fail_closed():
    from qwenpaw.models.runtime import validate_candidate

    with pytest.raises(ValueError, match="authority_unavailable"):
        validate_candidate({"shared_app_id": "forged"})
    with pytest.raises(ValueError, match="model_slot_override_not_supported"):
        validate_candidate({"model_slot_override": {"provider_id": "p", "model": "m"}})
    with pytest.raises(ValueError):
        validate_candidate({"requested_model": {}})


@pytest.mark.asyncio
async def test_builder_boundary_revalidates_selected_model(monkeypatch):
    from qwenpaw.models.runtime import recheck_model_authority
    from tests.unit.models.test_governance import actor

    request = SimpleNamespace(
        _model_authority=(actor(), "a", {"provider_id": "p", "model": "revoked"})
    )

    class Service:
        async def require_model(self, *args):
            raise ValueError("revoked")

    monkeypatch.setattr("qwenpaw.models.runtime.get_model_service", lambda _: Service())
    with pytest.raises(ValueError, match="revoked"):
        await recheck_model_authority(request, object())
