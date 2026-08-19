# -*- coding: utf-8 -*-
"""Market category catalogue and search validation.

Covers the local (non-network) parts of ``app/routers/market.py`` and
``market/categories.py``: the category tab catalogue with its language
selection and unknown-language fallback, and the search endpoint's
unknown-provider validation, which rejects before any outbound request is
made.

The actual marketplace search is deliberately not exercised here — it
fans out to external provider APIs, so a test would depend on outbound
network. Only the validation branch that short-circuits ahead of that is
asserted.

API endpoints:
  - GET  /api/market/categories
  - GET  /api/market/providers
  - POST /api/market/search
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)


def _categories(app_server, **params) -> list[dict]:
    resp = app_server.api_request(
        "GET",
        "/api/market/categories",
        params=params or None,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list) and body, body
    return body


@pytest.mark.integration
@pytest.mark.p1
def test_categories_have_stable_ids_and_labels(app_server):
    """The category catalogue exposes an id and a label per entry.

    Test purpose:
      - Cover list_categories: every tab the console renders needs both
        fields, and the ids must be unique so tab selection is
        unambiguous.
    """
    entries = _categories(app_server)
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)), ids
    for entry in entries:
        assert entry.get("id"), entry
        assert entry.get("label"), entry


@pytest.mark.integration
@pytest.mark.p1
def test_categories_labels_are_localized(app_server):
    """A zh request returns different labels than the en request.

    Test purpose:
      - Cover the language lookup in list_categories / _lang_key. Ids
        must stay identical across languages while at least one label
        changes, proving the localisation is applied rather than ignored.
    """
    en = {e["id"]: e["label"] for e in _categories(app_server, lang="en")}
    zh = {e["id"]: e["label"] for e in _categories(app_server, lang="zh")}
    assert set(en) == set(zh), (sorted(en), sorted(zh))
    assert any(
        en[key] != zh[key] for key in en
    ), "zh labels are identical to en; localisation did not apply"


@pytest.mark.integration
@pytest.mark.p2
def test_categories_unknown_language_falls_back(app_server):
    """An unrecognised language falls back to a supported one.

    Test purpose:
      - Cover _lang_key's default: an unknown code must not raise a
        KeyError while building the label list.
    """
    fallback = {
        e["id"]: e["label"] for e in _categories(app_server, lang="integ-xx")
    }
    en = {e["id"]: e["label"] for e in _categories(app_server, lang="en")}
    assert set(fallback) == set(en), (sorted(fallback), sorted(en))


@pytest.mark.integration
@pytest.mark.p2
def test_market_providers_listing(app_server):
    """The provider catalogue lists the keys search accepts.

    Test purpose:
      - Cover the providers endpoint, whose keys are exactly what
        market_search validates ``provider_pages`` against.
    """
    resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, (list, dict)) and body, body


@pytest.mark.integration
@pytest.mark.p1
def test_search_rejects_unknown_provider(app_server):
    """An unknown provider key is refused before any network call.

    Test purpose:
      - Cover market_search's provider validation. This is the only
        search branch safe to assert offline: it raises before the
        outbound fan-out, and the message must name the offending key.
    """
    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "integ probe",
            "provider_pages": {"integ-not-a-provider": 1},
            "limit": 1,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text
    assert "integ-not-a-provider" in resp.text, resp.text
