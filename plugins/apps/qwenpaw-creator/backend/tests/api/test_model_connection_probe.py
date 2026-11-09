# -*- coding: utf-8 -*-
"""Connectivity probes must measure the route production actually calls.

Image and video probes stay on free read-only APIs: submitting a real
generation task is billable, and the DashScope gateway rejects an async
submission that omits ``X-DashScope-Async`` with 403. ASR is the exception —
one second of generated silence costs a fraction of a cent, and the free
probes it used to rely on (``GET /models/{id}``, the upload-policy call) said
nothing about transcription, which is how three dead ASR routes stayed green.
"""

# pylint: disable=unused-argument,redefined-outer-name
# The stub transport and the two fake httpx clients below have to
# mirror the real call signature: ``_send_probe`` posts its body with
# the keyword ``json`` while this module imports the ``json`` codec to
# build the canned replies the route grades, and the stub transport
# ignores the request object it is handed.

from __future__ import annotations

import asyncio
import io
import json
import types
import wave

import httpx
import pytest

from api import model_routes
from api.model_routes import (
    ProbeDestinationError,
    _asr_provider,
    _assert_probe_destination,
    _assert_probe_peer,
    _minimax_base_resp_error,
    _non_secret_probe_params,
    _prepare_probe_payload,
    _probe_payload,
    _probe_target_refusal,
    _send_probe,
    _silent_wav_bytes,
    _validate_section_connectivity,
)
from domain.errors import ValidationError
from models import media_transport
from schemas.models import ModelConnectionTestRequest


def _request(**overrides) -> ModelConnectionTestRequest:
    payload = {
        "type": "asr",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "sk-test",
        "model_name": "fun-asr",
        "protocol": "DashScope Fun-ASR",
        "provider": "fun-asr",
    }
    payload.update(overrides)
    return ModelConnectionTestRequest(**payload)


@pytest.fixture(name="uploaded_samples")
def _uploaded_samples(monkeypatch: pytest.MonkeyPatch) -> list:
    """Stub the DashScope temporary-OSS upload, recording what it was given."""

    calls: list = []

    async def upload(path, **kwargs):
        calls.append((path.name, path.read_bytes(), kwargs))
        return "oss://dashscope/creator-probe.wav"

    monkeypatch.setattr(
        media_transport,
        "upload_local_file_to_dashscope_temp",
        upload,
    )
    return calls


def _probe(request):
    return asyncio.run(_prepare_probe_payload(request))


def test_asr_fun_probe_submits_a_real_transcription_task(
    uploaded_samples,
) -> None:
    """Fun-ASR is probed on the route production transcribes with.

    Regression guard: the probe used to call the DashScope upload-policy API,
    which says nothing about transcription, so a platform answering 404 on
    ``asr/transcription`` still showed a green connection test.
    """

    url, headers, payload = _probe(_request())

    assert url == (
        "https://dashscope.aliyuncs.com/api/v1"
        "/services/audio/asr/transcription"
    )
    # Without this header the gateway answers 403 "does not support
    # asynchronous calls" — the failure that pushed the probe onto the
    # zero-cost policy call in the first place.
    assert headers["X-DashScope-Async"] == "enable"
    assert headers["X-DashScope-OssResourceResolve"] == "enable"
    assert payload == {
        "_attests": "asr-fun",
        "model": "fun-asr",
        "input": {"file_urls": ["oss://dashscope/creator-probe.wav"]},
        "parameters": {},
    }
    # The sample really was uploaded, and it really is audio.
    name, sample, kwargs = uploaded_samples[0]
    assert name == "creator-probe.wav"
    assert sample == _silent_wav_bytes()
    assert kwargs["media_type"] == "audio/wav"
    assert kwargs["api_key"] == "sk-test"


def test_asr_fun_probe_does_not_double_a_token_portal_path(
    uploaded_samples,
) -> None:
    """A base URL already carrying the transcription path must not repeat it.

    ``_fun_asr_base`` strips the suffix for production; the probe has to join
    back to the same URL or the proxy rejects the doubled path with 403.
    """

    del uploaded_samples
    url, _headers, _payload = _probe(
        _request(
            base_url=(
                "https://dashscope.aliyuncs.com/api/v1"
                "/services/audio/asr/transcription"
            ),
        ),
    )

    assert url == (
        "https://dashscope.aliyuncs.com/api/v1"
        "/services/audio/asr/transcription"
    )


def test_asr_qwen3_probe_uses_the_multimodal_generation_route(
    uploaded_samples,
) -> None:
    """qwen3-asr must not be probed as if it were Fun-ASR.

    The previous dispatch never produced ``qwen3-asr``, so that config was
    validated against the Fun-ASR upload-policy call while production posted
    to ``multimodal-generation`` — the route that answered 502 in the field.
    """

    del uploaded_samples
    url, headers, payload = _probe(
        _request(
            model_name="qwen3-asr-flash",
            provider="fun-asr",
            protocol="DashScope Qwen3-ASR",
        ),
    )

    assert url == (
        "https://dashscope.aliyuncs.com"
        "/api/v1/services/aigc/multimodal-generation/generation"
    )
    assert headers["X-DashScope-OssResourceResolve"] == "enable"
    assert "X-DashScope-Async" not in headers
    assert payload == {
        "_attests": "asr-qwen3",
        "model": "qwen3-asr-flash",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"audio": "oss://dashscope/creator-probe.wav"},
                    ],
                },
            ],
        },
        "parameters": {"result_format": "message"},
    }


def test_asr_whisper_probe_posts_a_real_multipart_transcription(
    uploaded_samples,
) -> None:
    """Whisper is probed by transcribing, not by looking the model up.

    ``GET /models/whisper-1`` only proves the key and the registry entry; the
    field failure was a 500 on ``audio/transcriptions`` itself.
    """

    url, headers, payload = _probe(
        _request(
            base_url="https://api.openai.com/v1",
            model_name="whisper-1",
            protocol="OpenAI Whisper",
            provider="whisper",
        ),
    )

    assert url == "https://api.openai.com/v1/audio/transcriptions"
    multipart = payload["_multipart_probe"]
    assert multipart["data"] == {
        "model": "whisper-1",
        "response_format": "verbose_json",
    }
    name, sample, mime = multipart["files"]["file"]
    assert (name, mime) == ("creator-probe.wav", "audio/wav")
    assert sample == _silent_wav_bytes()
    assert headers["Authorization"] == "Bearer sk-test"
    # OpenAI-compatible whisper takes the bytes inline: no DashScope upload.
    assert uploaded_samples == []


def test_asr_protocol_label_cannot_redirect_the_probe(
    uploaded_samples,
) -> None:
    """A Whisper protocol label must not move a Fun-ASR config's probe.

    ``get_asr_provider()`` reads only the stored provider, so this config
    transcribes through Fun-ASR. Probing ``audio/transcriptions`` instead
    would succeed against an OpenAI-compatible base URL and report green
    for a route production never calls.
    """

    del uploaded_samples
    url, headers, _payload = _probe(
        _request(
            base_url="https://api.openai.com/v1",
            model_name="whisper-1",
            protocol="OpenAI Whisper",
            provider="fun-asr",
        ),
    )

    assert url == (
        "https://api.openai.com/v1/services/audio/asr/transcription"
    )
    assert headers["X-DashScope-Async"] == "enable"


@pytest.mark.parametrize(
    ("provider", "protocol", "model_name", "expected"),
    [
        ("whisper", "", "whisper-1", "whisper"),
        # get_asr_provider() reads only the stored provider and defaults to
        # fun-asr, so the protocol label never decides the route.
        (None, "OpenAI Whisper", "whisper-1", "fun-asr"),
        # A protocol/provider mismatch is a broken config, not a licence to
        # probe the route the label implies.
        ("fun-asr", "OpenAI Whisper", "whisper-1", "fun-asr"),
        # get_asr_provider() only ever returns whisper or fun-asr, so a
        # qwen3-asr model arrives labelled fun-asr and is routed by name.
        ("fun-asr", "", "qwen3-asr-flash", "qwen3-asr"),
        (None, "", "qwen3-asr-flash", "qwen3-asr"),
        ("fun-asr", "DashScope Fun-ASR", "fun-asr", "fun-asr"),
        (None, "", "paraformer-v2", "fun-asr"),
    ],
)
def test_asr_provider_mirrors_the_production_dispatch(
    provider,
    protocol,
    model_name,
    expected,
) -> None:
    """The probe must run the route ``asr_model.transcribe`` would run."""

    assert (
        _asr_provider(
            _request(
                provider=provider,
                protocol=protocol,
                model_name=model_name,
            ),
        )
        == expected
    )


def test_silent_probe_sample_is_one_second_of_decodable_silence() -> None:
    """The sample must be real audio, or the probe proves nothing."""

    with wave.open(io.BytesIO(_silent_wav_bytes()), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16_000
        assert handle.getnframes() == 16_000
        assert handle.readframes(16_000) == b"\x00" * 32_000


def test_probe_payload_refuses_to_guess_an_asr_route() -> None:
    """ASR dispatch is async; the sync path must not silently fall through."""

    with pytest.raises(ValueError, match="_prepare_probe_payload"):
        _probe_payload(_request())


class _EmptyAsrConfig:
    """A stored config with nothing filled in, as a first-run install has."""

    class _Item:
        api_key = ""
        base_url = ""
        model_name = ""
        protocol = ""
        provider = None
        voice = ""
        reuse_llm_key = False

    asr = _Item()
    llm = _Item()


def test_connection_test_reports_an_unstageable_sample_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe that cannot stage its own sample must still report cleanly.

    The Fun-ASR and qwen3-asr probes upload the silent sample through the
    real DashScope temporary OSS, which refuses an absent credential with a
    ``RuntimeError``. Uncaught, that turned the endpoint whose whole job is
    explaining a broken configuration into a 500.
    """

    monkeypatch.setattr(model_routes, "load_model_config", _EmptyAsrConfig)

    response = asyncio.run(
        model_routes.test_model_connection(
            # require_api_key=False is the caller's choice; the probe still
            # has to cope with the empty credential instead of exploding.
            _request(api_key="", require_api_key=False),
        ),
    )

    assert not response.ok
    assert "RuntimeError" in response.error
    assert "API key" in response.error


def test_connection_test_reports_a_metadata_target_as_a_failure(
    uploaded_samples,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused destination is a diagnostic answer, not a server error.

    End to end, because the exception being a ``ValueError`` only matters if
    the route's handler still lists ``ValueError``: drop it from that tuple
    and the endpoint whose job is explaining a broken configuration answers
    with a 500 instead.
    """

    del uploaded_samples
    monkeypatch.setattr(model_routes, "load_model_config", _EmptyAsrConfig)

    response = asyncio.run(
        model_routes.test_model_connection(
            _request(
                base_url="http://169.254.169.254/latest/meta-data",
                require_api_key=False,
            ),
        ),
    )

    assert not response.ok
    assert "ProbeDestinationError" in response.error
    assert "元数据" in response.error


class _AcceptingResponse:
    """A provider reply that took the probe, without touching the network."""

    is_success = True

    def json(self) -> dict:
        return {}


class _ProbeConfig(_EmptyAsrConfig):
    """The first-run config above, plus the sections probes read."""

    image = _EmptyAsrConfig._Item()
    tts = _EmptyAsrConfig._Item()


def _accepted_connection_test(
    request: ModelConnectionTestRequest,
    monkeypatch: pytest.MonkeyPatch,
):
    """Run the whole endpoint against a provider that always accepts.

    The probe is prepared by the real routing code, because which verb it
    ends up using is the thing under test; only the socket is replaced.
    """

    async def fake_send(client, url, headers, payload):
        del client, url, headers, payload
        return _AcceptingResponse()

    monkeypatch.setattr(model_routes, "load_model_config", _ProbeConfig)
    monkeypatch.setattr(model_routes, "_send_probe", fake_send)
    return asyncio.run(model_routes.test_model_connection(request))


def test_connection_test_marks_a_real_request_as_capability_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A posted completion proves the modality answers, not just the key."""

    result = _accepted_connection_test(
        _request(
            type="llm",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            protocol="OpenAI 协议",
            provider=None,
        ),
        monkeypatch,
    )

    assert result.ok
    assert result.capability_verified is True


def test_connection_test_marks_a_read_only_probe_as_credential_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A free GET cannot show that a broken generation route got fixed.

    A model listing answers 200 for any valid key while keeping non-text
    models invisible, which is exactly how three dead ASR routes stayed
    green. Marking that pass as credential-level is what stops the UI from
    claiming a capability this test never exercised.
    """

    result = _accepted_connection_test(
        _request(
            type="image",
            base_url=(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1"
            ),
            model_name="wan2.7-image-pro",
            protocol="Aliyun Token Plan",
            provider=None,
        ),
        monkeypatch,
    )

    assert result.ok
    assert result.capability_verified is False


class _StubResponse:
    """A canned 2xx reply carrying the body the route has to grade."""

    is_success = True

    def __init__(self, text: str, content_type: str = "application/json"):
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self) -> object:
        return json.loads(self.text)


def _connection_test_replying(
    request: ModelConnectionTestRequest,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    content_type: str = "application/json",
):
    """Run the endpoint against one specific provider answer.

    The empty-JSON stand-in used everywhere else is exactly what a 200 that
    proved nothing looks like, so these cases need their own body.
    """

    async def fake_send(client, url, headers, payload):
        del client, url, headers, payload
        return _StubResponse(text, content_type)

    monkeypatch.setattr(model_routes, "load_model_config", _ProbeConfig)
    monkeypatch.setattr(model_routes, "_send_probe", fake_send)
    return asyncio.run(model_routes.test_model_connection(request))


def test_read_only_voice_listing_stays_credential_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A management POST is a POST, and that used to read as a verdict.

    ``cosyvoice-v3.5-plus`` has no system voices, so the probe lists the
    enrolled ones instead of synthesizing — an empty list with HTTP 200 says
    the credential works and nothing about the model producing audio.
    """

    result = _connection_test_replying(
        _request(
            type="tts",
            model_name="cosyvoice-v3.5-plus",
            protocol="DashScope CosyVoice",
            provider=None,
        ),
        monkeypatch,
        '{"output": {"voice_list": []}}',
    )

    assert result.ok
    assert result.capability_verified is False


def test_a_real_synthesis_probe_still_verifies_the_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard on the guard: a model with system voices posts audio.

    Demoting the listing must not demote the probe that actually asked the
    model to speak.
    """

    result = _connection_test_replying(
        _request(
            type="tts",
            model_name="qwen3-tts-flash",
            protocol="DashScope TTS",
            provider=None,
        ),
        monkeypatch,
        '{"output": {"audio": {"url": "https://cdn.example/a.wav"}}}',
    )

    assert result.ok
    assert result.capability_verified is True


@pytest.mark.parametrize(
    ("text", "content_type", "expected_ok", "expected_verified"),
    [
        # Silence transcribes to an empty string; that is a working route.
        ('{"text": "", "segments": []}', "application/json", True, True),
        ('{"text": "hello"}', "application/json", True, True),
        # An empty 204-style answer is not a transcription document. None
        # rather than False: the probe failed, so no grade applies.
        ("", "application/json", False, None),
        # A login interstitial answers 200 with markup.
        ("<html>Login required</html>", "text/html", False, None),
        # Some gateways wrap the refusal inside a 2xx.
        (
            '{"error": {"type": "authentication_error", '
            '"message": "denied"}}',
            "application/json",
            False,
            None,
        ),
        # DashScope native errors carry code/message rather than error.
        (
            '{"code": "Throttling", "message": "rate limit"}',
            "application/json",
            False,
            None,
        ),
        # A streaming answer is exactly what production cannot parse:
        # ``_whisper`` calls ``response.json()``, so the frame is a crash.
        (
            'event: error\\ndata: {"message": "boom"}\\n\\n',
            "text/event-stream",
            False,
            None,
        ),
        # The same interstitial behind a label that claims plain text: the
        # bytes, not the content type, decide what can be parsed.
        (
            "<html><body>Login</body></html>",
            "text/plain",
            False,
            None,
        ),
        # Valid JSON whose top level is a list — ``_whisper`` indexes fields
        # on it, which is an ``AttributeError``.
        ("[1,2]", "application/json", False, None),
        # The reader walks ``segments``, so a real segment document counts
        # even when no top-level ``text`` was promised.
        (
            '{"segments": [{"text": "hi", "start": 0.1, "end": 0.9}]}',
            "application/json",
            True,
            True,
        ),
        # A segment entry the reader cannot index is the next real request
        # failing, not an exotic but tolerable answer.
        ('{"segments": ["hi"]}', "application/json", False, None),
        (
            '{"segments": {"0": {"text": "hi"}}}',
            "application/json",
            False,
            None,
        ),
        # The old success stand-in: valid JSON, no transcription in it.
        ("{}", "application/json", True, False),
    ],
)
def test_whisper_probe_grades_a_2xx_before_claiming_capability(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    content_type: str,
    expected_ok: bool,
    expected_verified: bool | None,
) -> None:
    """HTTP 2xx alone cannot attest that a transcription came back."""

    result = _connection_test_replying(
        _request(
            type="asr",
            base_url="https://api.example.com/v1",
            model_name="whisper-1",
            protocol="OpenAI 协议",
            provider="whisper",
        ),
        monkeypatch,
        text,
        content_type,
    )

    assert result.ok is expected_ok
    assert result.capability_verified is expected_verified
    if not expected_ok:
        assert result.error


@pytest.mark.parametrize(
    ("text", "expected_ok", "expected_verified"),
    [
        # The shape a gateway writes when it pastes its own failure into
        # ``output``: production's first ``.get`` on it raises, and claiming
        # a verified transcription from it is the worst answer available.
        ('{"output": "upstream unavailable"}', False, None),
        ('{"output": []}', False, None),
        # The documented answers, both of which ``_qwen3_sentences`` walks.
        (
            '{"output": {"choices": [{"message": '
            '{"content": [{"text": "hi"}]}}]}}',
            True,
            True,
        ),
        (
            '{"output": {"sentence": {"text": "hi"}}}',
            True,
            True,
        ),
        ('{"text": "hi"}', True, True),
        # Readable but empty: the route answered and nothing was transcribed,
        # which is the credential-only verdict.
        ('{"output": {}}', True, False),
        ("{}", True, False),
    ],
)
def test_qwen3_probe_grades_the_document_production_reads(
    monkeypatch: pytest.MonkeyPatch,
    uploaded_samples: list,
    text: str,
    expected_ok: bool,
    expected_verified: bool | None,
) -> None:
    """``output`` has to be the object ``_qwen3_sentences`` indexes.

    The field-presence check accepted any truthy value there, so a provider
    error string certified the transcription route.
    """

    del uploaded_samples
    result = _connection_test_replying(
        _request(
            base_url="https://dashscope.aliyuncs.com/api/v1",
            model_name="qwen3-asr-flash",
            protocol="DashScope Qwen3-ASR",
            provider=None,
        ),
        monkeypatch,
        text,
    )

    assert result.ok is expected_ok
    assert result.capability_verified is expected_verified
    if not expected_ok:
        assert result.error


def test_section_validator_reports_a_refused_probe_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused sample upload belongs in the 422 channel, not a 500.

    ``_validate_section_connectivity`` has no caller today, so this pins the
    contract for whenever it is wired into config save: the ASR probe is the
    only one that can fail before it puts anything on the wire, and that
    failure is a finding about the section like any other.
    """

    async def refused_upload(*_args, **_kwargs):
        raise RuntimeError("DashScope upload policy missing max_file_size_mb")

    monkeypatch.setattr(
        media_transport,
        "upload_local_file_to_dashscope_temp",
        refused_upload,
    )

    with pytest.raises(ValidationError, match="max_file_size_mb"):
        asyncio.run(
            _validate_section_connectivity(
                "asr",
                {
                    "asr": {
                        "enabled": True,
                        "base_url": "https://dashscope.aliyuncs.com/api/v1",
                        "api_key": "sk-test",
                        "model_name": "fun-asr",
                        "protocol": "DashScope Fun-ASR",
                        "provider": "fun-asr",
                    },
                },
            ),
        )


class _FakeClient:
    """Records the request ``_send_probe`` would put on the wire."""

    def __init__(self) -> None:
        self.calls: list = []

    async def get(self, url, *, headers, params):
        self.calls.append(("GET", url, headers, params, None, None))
        return "response"

    async def post(self, url, *, headers, json=None, data=None, files=None):
        self.calls.append(("POST", url, headers, json, data, files))
        return "response"


def test_send_probe_shapes_the_request_per_probe_marker() -> None:
    """One sender for all three probe shapes, so none can drift apart."""

    client = _FakeClient()
    probe_url = "https://example.test/v1"
    auth = {"Content-Type": "application/json", "Authorization": "Bearer k"}
    for payload in (
        {"_get_probe": True, "action": "getPolicy"},
        {
            "_multipart_probe": {
                "data": {"model": "whisper-1"},
                "files": {"file": ("a.wav", b"\x00", "audio/wav")},
            },
        },
        {"model": "qwen-plus"},
    ):
        asyncio.run(
            _send_probe(client, probe_url, dict(auth), payload),
        )

    verb, _url, headers, params, _json, _files = client.calls[0]
    assert (verb, headers, params) == (
        "GET",
        {"Authorization": "Bearer k"},
        {"action": "getPolicy"},
    )

    verb, _url, headers, sent_json, data, files = client.calls[1]
    # httpx has to write the multipart boundary itself.
    assert verb == "POST"
    assert "Content-Type" not in headers
    assert sent_json is None
    assert data == {"model": "whisper-1"}
    assert files == {"file": ("a.wav", b"\x00", "audio/wav")}

    verb, _url, headers, sent_json, data, files = client.calls[2]
    assert (verb, sent_json, data, files) == (
        "POST",
        {"model": "qwen-plus"},
        None,
        None,
    )
    assert headers["Content-Type"] == "application/json"


class _FakeStream:
    """Stands in for httpx's network stream, naming the connected peer."""

    def __init__(self, peer: str) -> None:
        self.peer = peer

    def get_extra_info(self, key: str):
        return (self.peer, 443) if key == "server_addr" else None


class _FakeResponse:
    """A response whose peer is known, or that has no network stream."""

    def __init__(self, peer: str | None) -> None:
        self.extensions = (
            {} if peer is None else {"network_stream": _FakeStream(peer)}
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/",
        # AWS answers IPv6 from a ULA, Alibaba Cloud from the shared
        # address space: neither is link-local, so a range check alone
        # would let both through.
        "http://[fd00:ec2::254]/latest/meta-data/",
        "http://100.100.100.200/latest/meta-data/",
        # The same endpoints written as an IPv4-mapped IPv6 literal, which
        # a policy comparing parsed values has to see through.
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "http://[::ffff:100.100.100.200]/latest/meta-data/",
        "http://169.254.1.1:8080/v1/chat/completions",
        "http://[fe80::1]/v1",
    ],
)
def test_probe_destination_refuses_the_metadata_service(url: str) -> None:
    """Cloud metadata hands instance credentials to anything that asks.

    No model endpoint is ever served from those addresses, and a probe
    carries the configured API key, so reaching one would leak the key and
    read back the instance's own role credentials.
    """

    with pytest.raises(ProbeDestinationError, match="元数据"):
        _assert_probe_destination(url)


def test_probe_destination_error_is_a_value_error() -> None:
    """A refused destination must stay an ``ok=False`` answer, not a 500.

    ``test_model_connection`` catches ``(httpx.HTTPError, ValueError,
    RuntimeError)`` and renders the message as a diagnostic. Re-parenting
    this exception onto ``domain.errors.ValidationError`` would turn the
    endpoint whose job is explaining a broken configuration into a server
    error, which is the same trap the ASR upload refusal fell into.
    """

    assert issubclass(ProbeDestinationError, ValueError)


@pytest.mark.parametrize(
    "url",
    [
        # Self-hosted gateways are a first-class Creator setup.
        "http://localhost:11434/v1/chat/completions",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:1234/v1",
        "http://192.168.1.20:30010/v1/videos",
        "http://10.0.0.8/v1",
        "https://dashscope.aliyuncs.com/api/v1",
        "https://api.openai.com/v1/audio/transcriptions",
    ],
)
def test_probe_destination_allows_operator_configured_endpoints(
    url: str,
) -> None:
    """Loopback and RFC1918 targets must keep probing successfully.

    ``safe_remote_download.require_public_ip`` rejects every non-global
    address, but it guards URLs a provider handed us. A probe target is the
    Base URL the operator typed into the model form, so applying that policy
    here would break every Ollama, vLLM and SGLang deployment the moment its
    connection is tested.
    """

    _assert_probe_destination(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:25/_",
        "ftp://example.test/v1",
        "/v1/chat/completions",
        "https://dashscope.aliyuncs.com@evil.example/v1",
        "https://user:secret@example.test/v1",
    ],
)
def test_probe_destination_refuses_other_schemes_and_credentials(
    url: str,
) -> None:
    """Only a plain http(s) host the operator named may be probed.

    ``https://dashscope.aliyuncs.com@evil.example`` reads as a trusted host
    in a log while the request actually goes to evil.example with the
    bearer key attached.
    """

    with pytest.raises(ProbeDestinationError):
        _assert_probe_destination(url)


def test_probe_peer_refuses_a_metadata_socket() -> None:
    """The connected peer is checked, not just the hostname.

    A pre-flight lookup and the connection are separate resolutions, so a
    hostname can answer with a public address and then land on the metadata
    service. The peer the socket reached cannot lie about that.
    """

    for peer in (
        "169.254.169.254",
        "fd00:ec2::254",
        "100.100.100.200",
        "::ffff:100.100.100.200",
    ):
        with pytest.raises(ProbeDestinationError, match="元数据"):
            _assert_probe_peer(_FakeResponse(peer))

    # A public peer and a loopback gateway both pass, and a transport with
    # no network stream (a test double, in-process ASGI) has no peer to
    # verify, so it is skipped rather than failing every probe.
    _assert_probe_peer(_FakeResponse("93.184.216.34"))
    _assert_probe_peer(_FakeResponse("127.0.0.1"))
    _assert_probe_peer(_FakeResponse(None))
    _assert_probe_peer("response")


def test_send_probe_refuses_before_any_request_is_made() -> None:
    """A literal link-local target never reaches the wire.

    The credential is in the headers argument, so the point of checking
    first is that nothing carrying it is ever sent.
    """

    client = _FakeClient()

    with pytest.raises(ProbeDestinationError):
        asyncio.run(
            _send_probe(
                client,
                "http://169.254.169.254/latest/meta-data/",
                {"Authorization": "Bearer sk-live"},
                {"model": "qwen-plus"},
            ),
        )

    assert not client.calls


def test_send_probe_rejects_a_response_from_a_metadata_peer() -> None:
    """A hostname resolving onto the metadata service is caught too."""

    class _PeerClient(_FakeClient):
        async def post(
            self,
            url,
            *,
            headers,
            json=None,
            data=None,
            files=None,
        ):
            await super().post(
                url,
                headers=headers,
                json=json,
                data=data,
                files=files,
            )
            return _FakeResponse("100.100.100.200")

    client = _PeerClient()

    with pytest.raises(ProbeDestinationError, match="元数据"):
        asyncio.run(
            _send_probe(
                client,
                "https://gateway.example/v1",
                {},
                {"model": "qwen-plus"},
            ),
        )

    # The request did go out, which is exactly why the peer check exists.
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("base_url", "model_name"),
    [
        ("https://dashscope.aliyuncs.com/api/v1", "wan2.7-r2v"),
        (
            "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
            "wan3.0-video",
        ),
        (
            "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
            "kling/kling-v3-video-generation",
        ),
    ],
)
def test_bailian_video_probe_uses_configured_root_without_billing(
    base_url,
    model_name,
) -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="video",
            base_url=base_url,
            model_name=model_name,
            protocol="DashScope（百炼）",
            provider=None,
        ),
    )

    assert url == f"{base_url}/tasks/11111111-1111-4111-8111-111111111111"
    assert payload == {"_get_probe": True}
    assert "X-DashScope-Async" not in headers


@pytest.mark.parametrize(
    ("type_", "model_name"),
    [("image", "wan2.7-image-pro"), ("video", "happyhorse-1.1")],
)
def test_token_plan_probe_uses_models_endpoint(type_, model_name) -> None:
    url, headers, payload = _probe_payload(
        _request(
            type=type_,
            model_name=model_name,
            protocol="Aliyun Token Plan",
            base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
            provider=None,
        ),
    )
    assert url == (
        "https://token-plan.cn-beijing.maas.aliyuncs.com"
        "/compatible-mode/v1/models"
    )
    assert payload == {"_get_probe": True}
    assert headers["Authorization"] == "Bearer sk-test"


@pytest.mark.parametrize(
    ("protocol", "base_url", "model_name", "expected_url", "expected_params"),
    [
        (
            "Google Gemini（Veo）",
            "https://generativelanguage.googleapis.com/v1beta",
            "veo-3.1-generate-preview",
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "veo-3.1-generate-preview",
            {},
        ),
        (
            "MiniMax（海螺）",
            "https://api.minimax.io",
            "MiniMax-Hailuo-2.3",
            "https://api.minimax.io/v1/query/video_generation",
            {"task_id": "creator-connection-probe"},
        ),
        (
            "Kling（可灵官方）",
            "https://api-singapore.klingai.com",
            "kling-2.6",
            "https://api-singapore.klingai.com/tasks",
            {"task_ids": "creator-connection-probe"},
        ),
        (
            "Vidu（官方）",
            "https://api.vidu.com",
            "viduq3-mix",
            "https://api.vidu.com/ent/v2/credits",
            {"show_detail": "false"},
        ),
    ],
)
def test_direct_video_probes_are_read_only_and_protocol_specific(
    protocol,
    base_url,
    model_name,
    expected_url,
    expected_params,
) -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="video",
            protocol=protocol,
            base_url=base_url,
            model_name=model_name,
            provider=None,
        ),
    )

    assert url == expected_url
    assert payload.pop("_get_probe") is True
    assert payload == expected_params
    if protocol.startswith("Google"):
        assert headers["x-goog-api-key"] == "sk-test"
        assert "Authorization" not in headers
    elif protocol.startswith("Vidu"):
        assert headers["Authorization"] == "Token sk-test"
    else:
        assert headers["Authorization"] == "Bearer sk-test"


@pytest.mark.parametrize(
    ("model_name", "protocol"),
    [
        ("private-video-gateway", "DashScope（百炼）"),
        ("doubao-seedance-2.0-pro", "Volcano Engine（火山引擎）"),
        ("doubao-seedance-2.0-lite", "Volcano Engine（火山引擎）"),
    ],
)
def test_video_probe_rejects_unknown_model_before_network(
    model_name,
    protocol,
) -> None:
    with pytest.raises(ValueError, match="VIDEO_MODEL_CAPABILITY_UNKNOWN"):
        _probe_payload(
            _request(
                type="video",
                model_name=model_name,
                protocol=protocol,
                provider=None,
            ),
        )


class _Resp:
    def __init__(self, body, *, valid_json=True):
        self._body = body
        self._valid = valid_json

    def json(self):
        if not self._valid:
            raise ValueError("not json")
        return self._body


@pytest.mark.parametrize(
    ("body", "valid", "expect_fragment"),
    [
        # Config-level failures must surface even under HTTP 200.
        (
            {"base_resp": {"status_code": 1004, "status_msg": "login fail"}},
            True,
            "1004",
        ),
        ({"base_resp": {"status_code": 2049}}, True, "2049"),
        ({"base_resp": {"status_code": 1008}}, True, "1008"),
        # A throwaway task_id legitimately returns non-zero codes for a valid
        # key; those must NOT fail the connection probe.
        (
            {
                "base_resp": {
                    "status_code": 2013,
                    "status_msg": "task not found",
                },
            },
            True,
            None,
        ),
        ({"base_resp": {"status_code": 0}}, True, None),
        ({"status": "ok"}, True, None),
        ("", False, None),
    ],
)
def test_minimax_base_resp_error_surfaces_http200_failures(
    body,
    valid,
    expect_fragment,
) -> None:
    msg = _minimax_base_resp_error(_Resp(body, valid_json=valid))
    if expect_fragment is None:
        assert msg is None
    else:
        assert expect_fragment in msg


def test_minimax_image_probe_avoids_the_openai_models_path() -> None:
    # MiniMax has no GET /models/{id}; falling through to the OpenAI probe
    # surfaced an nginx HTML 404. It must hit the free task-query endpoint,
    # derived from whichever regional host the user configured.
    url, headers, payload = _probe_payload(
        _request(
            type="image",
            protocol="MiniMax（国内站）",
            base_url="https://api.minimax.cn",
            model_name="image-01",
            provider=None,
        ),
    )
    assert url == "https://api.minimax.cn/v1/query/video_generation"
    assert "/models/" not in url
    assert payload.pop("_get_probe") is True
    assert payload == {"task_id": "creator-connection-probe"}
    assert headers["Authorization"] == "Bearer sk-test"


def test_openai_image_probe_still_uses_model_retrieve() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="image",
            protocol="OpenAI 协议",
            base_url="https://api.openai.com/v1",
            model_name="gpt-image-2",
            provider=None,
        ),
    )
    assert url == "https://api.openai.com/v1/models/gpt-image-2"
    assert payload == {"_get_probe": True}


def test_llm_probe_still_posts_a_chat_ping() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen-plus",
            protocol="OpenAI 协议",
            provider=None,
        ),
    )

    assert url == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert "_get_probe" not in payload
    assert payload["model"] == "qwen-plus"


def test_anthropic_llm_probe_uses_messages_endpoint() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.anthropic.com",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
        ),
    )

    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert "max_tokens" not in payload
    assert payload["messages"] == [
        {"role": "user", "content": "Reply with pong only."},
    ]


def test_minimax_llm_probe_uses_anthropic_format() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.minimaxi.com/anthropic",
            model_name="MiniMax-M3",
            protocol="MiniMax",
            provider=None,
        ),
    )

    assert url == "https://api.minimaxi.com/anthropic/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert payload["model"] == "MiniMax-M3"


def test_gemini_llm_probe_uses_generate_content() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
        ),
    )

    # Gemini authenticates through the ``key=`` query parameter; a probe
    # without it always fails with 400/401/403.
    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent?key=sk-test"
    )
    assert "Authorization" not in headers
    assert payload["contents"] == [
        {"parts": [{"text": "Reply with pong only."}]},
    ]
    assert "maxOutputTokens" not in payload.get("generationConfig", {})


def test_gemini_llm_probe_omits_key_when_keyless() -> None:
    url, headers, _payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://generativelanguage.googleapis.com",
            api_key="",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
            require_api_key=False,
        ),
    )

    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent"
    )
    assert "Authorization" not in headers


def test_anthropic_llm_probe_omits_key_header_when_keyless() -> None:
    _url, headers, _payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://api.anthropic.com",
            api_key="",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
            require_api_key=False,
        ),
    )

    assert "x-api-key" not in headers
    assert "Authorization" not in headers
    assert headers["anthropic-version"] == "2023-06-01"


def test_opencode_keyless_llm_probe_posts_chat_ping_without_auth() -> None:
    # OpenCode Zen serves ``*-free`` models without an API key; the probe
    # must not send an (empty) Authorization header, which the gateway
    # would reject as an invalid key.
    url, headers, payload = _probe_payload(
        _request(
            type="llm",
            base_url="https://opencode.ai/zen/v1",
            api_key="",
            model_name="nemotron-3.5-lightning-free",
            protocol="OpenCode",
            provider=None,
            require_api_key=False,
        ),
    )

    assert url == "https://opencode.ai/zen/v1/chat/completions"
    assert "Authorization" not in headers
    assert payload["model"] == "nemotron-3.5-lightning-free"


def test_anthropic_vlm_probe_converts_image_to_anthropic_format() -> None:
    url, headers, payload = _probe_payload(
        _request(
            type="vlm",
            base_url="https://api.anthropic.com",
            model_name="claude-sonnet-4-20250514",
            protocol="Anthropic Claude",
            provider=None,
        ),
    )

    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    messages = payload["messages"]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    text_block = content[0]
    assert text_block["type"] == "text"
    assert text_block["text"] == "Reply with red only."
    image_block = content[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"


def test_gemini_vlm_probe_converts_image_to_inline_data() -> None:
    url, _headers, payload = _probe_payload(
        _request(
            type="vlm",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
            protocol="Google Gemini",
            provider=None,
        ),
    )

    assert url.endswith(
        "/v1beta/models/gemini-2.5-pro:generateContent?key=sk-test",
    )
    contents = payload["contents"]
    assert len(contents) == 1
    parts = contents[0]["parts"]
    assert len(parts) == 2
    assert parts[0] == {"text": "Reply with red only."}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"


@pytest.mark.parametrize(
    ("body_text", "expected_ok", "expected_verified", "expected_error"),
    [
        # An accepted submit that is still queued. The probe posts and
        # deliberately does not poll, so this is where the evidence stops.
        (
            '{"output": {"task_id": "t-1", "task_status": "PENDING"}}',
            True,
            False,
            "",
        ),
        # The same submit whose task had already failed, with the provider's
        # refusal nested inside ``output`` rather than at the top level.
        (
            '{"output": {"task_id": "t-1", "task_status": "FAILED", '
            '"code": "InvalidParameter", '
            '"message": "Failed to download audio"}}',
            False,
            None,
            "InvalidParameter",
        ),
        # A terminal failure the provider left unexplained is still terminal.
        # ``_error_wrapped_in_2xx`` only reacts to ``code``/``message``, so
        # this case is what proves the status list itself is consulted.
        (
            '{"output": {"task_id": "t-1", "task_status": "FAILED"}}',
            False,
            None,
            "FAILED",
        ),
        # A submit that produced no task at all is a refusal, not a mystery.
        ('{"output": {"task_status": "PENDING"}}', False, None, "task_id"),
        # A gateway that answers with a finished task, but names no subtask.
        # ``_fun_asr`` reads ``results`` only after a poll, so this proves the
        # queue took the work and nothing more.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED"}}',
            True,
            False,
            "",
        ),
        # A submit whose ``output`` production cannot index at all: the
        # reader takes ``output.task_id`` before it starts polling.
        ('{"output": "InternalError"}', False, None, "output"),
        # A state this code does not know is not evidence of a breakage.
        (
            '{"output": {"task_id": "t-1", "task_status": "HELD"}}',
            True,
            False,
            "",
        ),
    ],
)
def test_fun_asr_submit_is_graded_on_its_task_state(
    monkeypatch: pytest.MonkeyPatch,
    uploaded_samples: list,
    body_text: str,
    expected_ok: bool,
    expected_verified: bool | None,
    expected_error: str,
) -> None:
    """A task id says the queue took the work, not that a transcript exists.

    ``asr_model._fun_asr`` polls until ``task_status`` reaches SUCCEEDED and
    raises on anything else, so a probe that does not poll may not call a
    FAILED task a verified capability — and an unlisted state has to leave
    the verdict at "credential accepted" rather than inventing a failure.
    """

    del uploaded_samples
    result = _connection_test_replying(
        _request(),
        monkeypatch,
        body_text,
    )

    assert result.ok is expected_ok
    assert result.capability_verified is expected_verified
    if expected_error:
        assert expected_error in (result.error or "")


def test_asr_probe_refuses_a_metadata_base_without_staging_the_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No network side effect may run ahead of the destination policy.

    Staging the sample is a request of its own that carries the configured
    bearer, so guarding only ``_send_probe`` handed the key to a hostile base
    URL and explained the refusal afterwards. The policy has to decide first.
    """

    async def refuse_upload(path, **kwargs):
        del path, kwargs
        raise AssertionError("the probe uploaded before checking its target")

    monkeypatch.setattr(model_routes, "load_model_config", _ProbeConfig)
    monkeypatch.setattr(
        media_transport,
        "upload_local_file_to_dashscope_temp",
        refuse_upload,
    )

    result = asyncio.run(
        model_routes.test_model_connection(
            _request(base_url="http://169.254.169.254/api/v1"),
        ),
    )

    assert result.ok is False
    assert "元数据" in (result.error or "")


@pytest.mark.parametrize(
    ("body_text", "expected_ok", "expected_verified", "expected_error"),
    [
        # The task reports itself finished while its only subtask failed.
        # ``_fun_asr`` picks the first SUCCEEDED subtask and raises when there
        # is none, so the next real request would fail on this document.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED", '
            '"results": [{"subtask_status": "FAILED", '
            '"code": "InvalidParameter", '
            '"message": "Failed to download audio"}]}}',
            False,
            None,
            "没有成功的子任务",
        ),
        # Finished, and the successful subtask carries no transcript to
        # download: the reader indexes ``transcription_url`` outright.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED", '
            '"results": [{"subtask_status": "SUCCEEDED"}]}}',
            False,
            None,
            "transcription_url",
        ),
        # ``results`` as a string iterates into characters whose ``.get`` the
        # reader would call — the AttributeError one request away.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED", '
            '"results": "SUCCEEDED"}}',
            False,
            None,
            "results",
        ),
        # The document a real finished task produces.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED", '
            '"results": [{"subtask_status": "SUCCEEDED", '
            '"transcription_url": "https://oss.example.test/t.json"}]}}',
            True,
            True,
            "",
        ),
        # The silence this probe deliberately asked for is an answer, not a
        # breakage: ``_fun_asr`` returns an empty transcript for a no-speech
        # verdict even when the task itself ended FAILED.
        (
            '{"output": {"task_id": "t-1", "task_status": "FAILED", '
            '"code": "ASR_RESPONSE_HAVE_NO_WORDS"}}',
            True,
            True,
            "",
        ),
        # The same verdict seen one level down, in the subtask list.
        (
            '{"output": {"task_id": "t-1", "task_status": "SUCCEEDED", '
            '"results": [{"subtask_status": "FAILED", '
            '"code": "ASR_RESPONSE_HAVE_NO_WORDS"}]}}',
            True,
            True,
            "",
        ),
    ],
)
def test_fun_asr_terminal_document_is_graded_by_the_poll_reader(
    monkeypatch: pytest.MonkeyPatch,
    uploaded_samples: list,
    body_text: str,
    expected_ok: bool,
    expected_verified: bool | None,
    expected_error: str,
) -> None:
    """A terminal ``SUCCEEDED`` is a claim about its subtasks, not a verdict.

    Reproduced from the review: the submit grader stopped at ``task_status``,
    so a document whose subtasks had failed certified a transcription route
    that ``asr_model._fun_asr`` refuses with "Fun-ASR failed".
    """

    del uploaded_samples
    result = _connection_test_replying(
        _request(),
        monkeypatch,
        body_text,
    )

    assert result.ok is expected_ok
    assert result.capability_verified is expected_verified
    if expected_error:
        assert expected_error in (result.error or "")


def test_send_probe_leaves_the_callers_payload_whole() -> None:
    """A marker is the sender's to consume, not the caller's to lose.

    Every current caller builds its payload inline and drops it, which is what
    made the in-place ``pop`` look harmless. It is still a dictionary owned by
    the caller: a retry, or a log line taken between attempts, would find the
    markers — and with them the description of what the answer proved — gone.
    """

    client = _FakeClient()
    payload = {
        "_get_probe": True,
        "_attests": "asr-fun",
        "action": "getPolicy",
    }

    asyncio.run(
        _send_probe(
            client,
            "https://example.test/v1",
            {"Content-Type": "application/json"},
            payload,
        ),
    )

    assert payload == {
        "_get_probe": True,
        "_attests": "asr-fun",
        "action": "getPolicy",
    }
    # The markers still keep the request they describe off the wire.
    verb, _url, headers, params, _json, _files = client.calls[0]
    assert verb == "GET"
    assert params == {"action": "getPolicy"}
    assert "Content-Type" not in headers


# ---------------------------------------------------------------------------
# CWE-522: the probe must not launder a saved credential toward a foreign host
# ---------------------------------------------------------------------------


_SECTIONS = (
    "llm",
    "vlm",
    "asr",
    "tts",
    "s2v",
    "image",
    "video",
    "embedding",
)


def _stub_saved_config(monkeypatch, **sections: dict) -> None:
    """Pretend the operator already saved these provider endpoints.

    ``_stub_saved_config(monkeypatch, llm={"base_url": ..., "api_key": ...})``;
    a section left out reads as unsaved.
    """
    defaults = {
        "base_url": "",
        "api_key": "",
        "model_name": "glm-5",
        "protocol": "OpenAI Chat",
        "provider": None,
        "voice": "",
        "reuse_llm_key": False,
        "reuse_vlm_key": False,
        "use_llm": False,
    }
    saved = {
        name: types.SimpleNamespace(
            **{**defaults, **sections.get(name, {})},
        )
        for name in _SECTIONS
    }

    def _load_saved():
        return types.SimpleNamespace(**saved)

    def _written(section: str) -> str:
        raw = sections.get(section, {})
        return str(raw.get("base_url") or "").strip()

    monkeypatch.setattr(model_routes, "load_model_config", _load_saved)
    # The stub stands in for model_config.json, so whatever a test passes here
    # counts as written by the operator; built-in defaults stay out of it.
    monkeypatch.setattr(model_routes, "_operator_written_base_url", _written)


def _no_dispatch_client(monkeypatch) -> None:
    """Make any outbound probe fail the test instead of reaching a socket."""

    def _factory(*args, **kwargs):
        raise AssertionError("the probe must not be dispatched at all")

    monkeypatch.setattr(model_routes.httpx, "AsyncClient", _factory)


_ASR_SUBMIT_REPLY = {
    "output": {
        "task_id": "creator-connection-probe",
        "task_status": "PENDING",
    },
}


def _capture_dispatch(monkeypatch, reply: dict | None = None) -> list:
    """Record the URL and headers a probe would send, then report success.

    ``reply`` is the answer the route grades. An ASR probe is a real
    transcription submit, and a bare ``{}`` reads as a broken route rather
    than as an unfamiliar shape, so an ASR case has to answer like the task
    queue it reached; the routing point these cases test is unchanged.
    """
    sent: list[tuple[str, dict[str, str]]] = []
    document = reply if reply is not None else {}
    body = json.dumps(document)

    class _Response:
        is_success = True
        status_code = 200
        text = body
        content = body.encode("utf-8")
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return document

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None, params=None):
            sent.append((str(url), dict(headers or {})))
            return _Response()

        async def post(self, url, headers=None, json=None, **kwargs):
            del kwargs
            sent.append((str(url), dict(headers or {})))
            return _Response()

    monkeypatch.setattr(model_routes.httpx, "AsyncClient", _Client)
    return sent


def test_saved_key_is_never_sent_to_a_request_selected_host(
    monkeypatch,
) -> None:
    """Masked key + foreign Base URL would post the stored secret elsewhere."""
    _stub_saved_config(
        monkeypatch,
        llm={
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-saved",
        },
    )
    _no_dispatch_client(monkeypatch)
    request = ModelConnectionTestRequest(
        type="llm",
        base_url="https://collector.example.net/v1",
        api_key=model_routes.SECRET_MASK,
        model_name="glm-5",
        protocol="OpenAI Chat",
        provider=None,
        require_api_key=True,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert not response.ok
    assert "安全限制" in response.error
    assert "collector.example.net" in response.error


@pytest.mark.parametrize(
    ("supplied_key", "stored_key", "probed", "homes", "want_refusal"),
    [
        # The caller already holds this key, so testing a brand-new gateway
        # against it stays possible - that is the point of this endpoint.
        (
            "sk-typed",
            "",
            "https://gateway.example.com/v1",
            ("https://dashscope.aliyuncs.com/v1",),
            False,
        ),
        # Same origin, different path: the compatible-mode and api roots are
        # one endpoint family, and the key belongs to both.
        (
            "",
            "sk-saved",
            "https://dashscope.aliyuncs.com/api/v1",
            ("https://dashscope.aliyuncs.com/compatible-mode/v1",),
            False,
        ),
        # Host comparison is case-insensitive.
        (
            "",
            "sk-saved",
            "https://DASHSCOPE.aliyuncs.com/v1",
            ("https://dashscope.aliyuncs.com/v1",),
            False,
        ),
        # A saved key may not travel to a host chosen per-request.
        (
            "",
            "sk-saved",
            "http://127.0.0.1:9999/v1",
            ("https://dashscope.aliyuncs.com/v1",),
            True,
        ),
        # ... nor one scheme downgrade away, where it would leave in cleartext.
        (
            "",
            "sk-saved",
            "http://dashscope.aliyuncs.com/v1",
            ("https://dashscope.aliyuncs.com/v1",),
            True,
        ),
        # ... nor to another service listening on the same host.
        (
            "",
            "sk-saved",
            "http://127.0.0.1:8000/v1",
            ("http://127.0.0.1:11434/v1",),
            True,
        ),
        # ``casefold()`` reads these two as equal; HTTPX resolves them to
        # different domains, so the guard must not treat them as one home.
        (
            "",
            "sk-saved",
            "https://aßistant.example/v1",
            ("https://assistant.example/v1",),
            True,
        ),
        # An explicit port must match the saved one, defaults included.
        (
            "",
            "sk-saved",
            "https://dashscope.aliyuncs.com:443/v1",
            ("https://dashscope.aliyuncs.com/v1",),
            False,
        ),
        # Nothing is being sent, so there is nothing to bind: a keyless probe
        # is a plain URL check.
        (
            "",
            "",
            "http://127.0.0.1:11434/v1",
            ("http://localhost:11434/v1",),
            False,
        ),
        # A credential with no recorded home must not borrow the request's.
        (
            "",
            "sk-env",
            "https://other.example/v1",
            ("",),
            True,
        ),
    ],
)
def test_probe_target_guard_boundaries(
    supplied_key,
    stored_key,
    probed,
    homes,
    want_refusal,
) -> None:
    refusal = _probe_target_refusal(
        probed,
        "llm",
        supplied_key=supplied_key,
        stored_key=stored_key,
        trusted_base_urls=homes,
    )

    assert bool(refusal) is want_refusal


def test_probe_target_guard_rejects_non_http_targets() -> None:
    refusal = _probe_target_refusal(
        "file:///etc/passwd",
        "llm",
        supplied_key="sk-typed",
        stored_key="",
        trusted_base_urls=(),
    )

    assert "http" in refusal


def test_probe_target_guard_survives_an_unparseable_url() -> None:
    """A malformed address is a config error, never an escaping ValueError."""
    refusal = _probe_target_refusal(
        "https://[::1",
        "llm",
        supplied_key="sk-typed",
        stored_key="",
        trusted_base_urls=("https://[::1",),
    )

    assert "配置不完整" in refusal


def test_malformed_probe_url_returns_a_config_error_not_a_500(
    monkeypatch,
) -> None:
    """The guard parses before the route's try block, so it must not raise."""
    _stub_saved_config(
        monkeypatch,
        llm={
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-saved",
        },
    )
    _no_dispatch_client(monkeypatch)
    request = ModelConnectionTestRequest(
        type="asr",
        base_url="https://[::1",
        api_key="sk-test",
        model_name="fun-asr",
        protocol="DashScope Fun-ASR",
        provider="fun-asr",
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert not response.ok
    assert "配置不完整" in response.error


def test_keyless_probe_of_another_host_still_reaches_the_provider(
    monkeypatch,
) -> None:
    """With no credential anywhere, testing a local server is not a leak."""
    _stub_saved_config(
        monkeypatch,
        llm={"base_url": "http://localhost:11434/v1", "api_key": ""},
    )
    sent = _capture_dispatch(monkeypatch)
    request = ModelConnectionTestRequest(
        type="llm",
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        model_name="llama3",
        protocol="OpenAI Chat",
        provider=None,
        require_api_key=False,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert response.ok
    assert len(sent) == 1
    assert sent[0][0].startswith("http://127.0.0.1:11434")
    assert "Authorization" not in sent[0][1]


def test_environment_key_without_a_saved_home_is_refused(
    monkeypatch,
) -> None:
    """A key with no recorded origin must not adopt the request's target."""
    _stub_saved_config(monkeypatch, llm={"base_url": "", "api_key": "sk-env"})
    _no_dispatch_client(monkeypatch)
    request = ModelConnectionTestRequest(
        type="llm",
        base_url="https://other.example/v1",
        api_key="",
        model_name="glm-5",
        protocol="OpenAI Chat",
        provider=None,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert not response.ok
    assert "没有记录归属地址" in response.error


@pytest.mark.parametrize(
    ("section", "owner", "owner_key", "model_name", "protocol"),
    [
        ("asr", "llm", "sk-llm", "whisper-1", "OpenAI Whisper"),
        (
            "embedding",
            "vlm",
            "sk-vlm",
            "qwen3-vl-embedding",
            "DashScope Multimodal",
        ),
        (
            "embedding",
            "llm",
            "sk-llm",
            "qwen3-vl-embedding",
            "DashScope Multimodal",
        ),
    ],
)
def test_saved_cross_host_key_reuse_still_probes_its_own_host(
    monkeypatch,
    uploaded_samples,
    section,
    owner,
    owner_key,
    model_name,
    protocol,
) -> None:
    """An operator-saved reuse pair is authorised, per each half's own host.

    The route previously re-anchored a reused key to the owner endpoint only,
    which refused a config that was already saved and never edited by this
    request - and the hint to "save it first" could not help, because it was.
    The third case has no VLM credential at all, so the reuse switch reaches
    past the VLM to the LLM key and must follow the LLM endpoint instead.
    """
    saved_owner = {
        "base_url": f"https://{owner}.example/v1",
        "api_key": owner_key,
    }
    saved_section = {
        "base_url": "https://media.example/v1",
        "api_key": "",
        "model_name": model_name,
        "protocol": protocol,
        "reuse_llm_key": section == "asr",
        "reuse_vlm_key": section == "embedding",
    }
    _stub_saved_config(
        monkeypatch,
        **{owner: saved_owner, section: saved_section},
    )
    sent = _capture_dispatch(
        monkeypatch,
        reply=_ASR_SUBMIT_REPLY if section == "asr" else None,
    )
    request = ModelConnectionTestRequest(
        type=section,
        base_url="",
        api_key="",
        model_name=model_name,
        protocol=protocol,
        provider=None,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert response.ok, response.error
    assert len(sent) == 1
    assert sent[0][0].startswith("https://media.example")
    assert sent[0][1]["Authorization"] == f"Bearer {owner_key}"


def test_saved_key_is_not_tricked_by_an_idna_lookalike_host(
    monkeypatch,
) -> None:
    """A lookalike host that casefolds to the saved one is still foreign."""
    _stub_saved_config(
        monkeypatch,
        llm={
            "base_url": "https://assistant.example/v1",
            "api_key": "sk-saved",
        },
    )
    _no_dispatch_client(monkeypatch)
    request = ModelConnectionTestRequest(
        type="llm",
        base_url="https://aßistant.example/v1",
        api_key=model_routes.SECRET_MASK,
        model_name="glm-5",
        protocol="OpenAI Chat",
        provider=None,
    )

    response = asyncio.run(model_routes.test_model_connection(request))

    assert not response.ok
    assert "安全限制" in response.error


def test_get_probe_params_never_carry_the_credential() -> None:
    params = _non_secret_probe_params(
        {"model": "fun-asr", "token": "sk-secret", "flag": "false"},
        "sk-secret",
    )

    assert params == {"model": "fun-asr", "flag": "false"}
    assert _non_secret_probe_params({"model": "fun-asr"}, "") == {
        "model": "fun-asr",
    }
    # A wrapped credential is still the credential.
    assert (
        _non_secret_probe_params({"a": "Bearer sk-secret"}, "sk-secret") == {}
    )


# ---------------------------------------------------------------------------
# Round-2 review: a built-in default is not an operator authorization.
#
# These cases go through the real config assembly (a model_config.json under an
# isolated data root) and a real HTTPX client over MockTransport. Only that
# shows ``_defaults()`` at work, and only HTTPX itself can prove which URLs it
# is willing to build a request for - a stubbed client hid exactly those bugs.
# ---------------------------------------------------------------------------

_REAL_ENV_KEYS = (
    "TEXT_API_KEY",
    "TEXT_BASE_URL",
    "VLM_API_KEY",
    "VLM_BASE_URL",
    "ASR_API_KEY",
    "ASR_BASE_URL",
    "DASHSCOPE_API_KEY",
)


def _write_real_config(monkeypatch, tmp_path, config: dict) -> None:
    """Save ``config`` the way the product does, then let it be assembled."""
    data_root = tmp_path / "data-root"
    (data_root / "config").mkdir(parents=True, exist_ok=True)
    config_file = data_root / "config" / "model_config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    for name in _REAL_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_file))
    # pylint: disable-next=protected-access
    model_routes._invalidate_raw_config_cache()


def _real_transport_dispatch(monkeypatch, reply: dict | None = None) -> list:
    """Build the request with HTTPX; mock only the socket layer.

    ``reply`` carries the answer the route grades: an ASR probe is now an
    actual transcription submit, and a bare ``{}`` reads as a broken route
    rather than as an unfamiliar shape.
    """
    sent: list[tuple[str, str]] = []
    document = reply if reply is not None else {}

    def _handle(request: httpx.Request) -> httpx.Response:
        sent.append(
            (str(request.url), request.headers.get("authorization", "")),
        )
        return httpx.Response(200, json=document)

    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(
            *args,
            transport=httpx.MockTransport(_handle),
            **kwargs,
        )

    monkeypatch.setattr(model_routes.httpx, "AsyncClient", _factory)
    return sent


def _saved_llm_only(base_url: str = "https://llm.example/v1") -> dict:
    return {
        "llm": {
            "base_url": base_url,
            "api_key": "sk-review-owner-fake",
            "model_name": "glm-5",
            "protocol": "OpenAI Chat",
        },
    }


@pytest.mark.parametrize("model_type", ["asr", "embedding"])
def test_builtin_default_target_never_receives_a_foreign_saved_key(
    monkeypatch,
    tmp_path,
    model_type: str,
) -> None:
    """Unconfigured sections borrow a DashScope address, not a credential."""
    _write_real_config(monkeypatch, tmp_path, _saved_llm_only())
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(type=model_type),
        ),
    )

    assert not response.ok
    assert "归属地址不一致" in response.error
    assert not sent


def test_builtin_default_still_probes_when_the_saved_key_owns_that_origin(
    monkeypatch,
    tmp_path,
    uploaded_samples,
) -> None:
    """A DashScope key may reach the built-in DashScope endpoint.

    Deliberately an unlisted task state: the submit is not a transcript, so
    the verdict stays credential-only and this case keeps testing where the
    key went rather than what the task produced.
    """
    _write_real_config(
        monkeypatch,
        tmp_path,
        _saved_llm_only("https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    sent = _real_transport_dispatch(
        monkeypatch,
        reply={
            "output": {
                "task_id": "creator-connection-probe",
                "task_status": "PENDING",
            },
        },
    )

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(type="asr"),
        ),
    )

    assert response.ok
    assert sent and sent[0][0].startswith(
        "https://dashscope.aliyuncs.com/api/v1/",
    )
    assert sent[0][1] == "Bearer sk-review-owner-fake"


def test_embedding_falls_back_to_the_origin_that_owns_the_key(
    monkeypatch,
    tmp_path,
) -> None:
    """A keyless VLM host must not inherit trust for the LLM credential."""
    _write_real_config(
        monkeypatch,
        tmp_path,
        {
            **_saved_llm_only(),
            "vlm": {
                "use_llm": False,
                "api_key": "",
                "base_url": "http://127.0.0.1:8765/v1",
                "model_name": "vl",
                "protocol": "OpenAI Chat",
            },
            "embedding": {
                "base_url": "https://embedding.example/v1",
                "api_key": "",
                "reuse_vlm_key": True,
                "model_name": "qwen3-vl-embedding",
            },
        },
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="embedding",
                base_url="http://127.0.0.1:8765/v1",
                model_name="qwen3-vl-embedding",
            ),
        ),
    )

    assert not response.ok
    assert "安全限制" in response.error
    assert not sent


@pytest.mark.parametrize(
    "base_url",
    [
        # UTS-46 would fold this into example.com; HTTPX refuses it outright.
        "https://exaｍple.com/v1",
        "https://example.com/a\tb",
        "https://256.256.256.256/v1",
        "https://[::1",
    ],
)
def test_url_httpx_cannot_build_is_a_config_error_not_a_500(
    monkeypatch,
    tmp_path,
    base_url: str,
) -> None:
    """The guard decides with HTTPX's own parser, so nothing escapes as 500."""
    _write_real_config(
        monkeypatch,
        tmp_path,
        _saved_llm_only("https://example.com/v1"),
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="llm",
                base_url=base_url,
                model_name="glm-5",
                protocol="OpenAI Chat",
                api_key="sk-review-supplied-fake",
            ),
        ),
    )

    assert not response.ok
    assert "配置不完整" in response.error
    assert not sent


def test_invalid_url_raised_while_building_stays_a_structured_failure(
    monkeypatch,
) -> None:
    """httpx.InvalidURL is not an HTTPError, so the handler has to name it."""
    _stub_saved_config(
        monkeypatch,
        llm={"base_url": "https://llm.example/v1", "api_key": "sk-saved"},
    )

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            raise httpx.InvalidURL("rejected while building the request")

        async def get(self, url, headers=None, params=None):
            raise httpx.InvalidURL("rejected while building the request")

    monkeypatch.setattr(
        model_routes.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _Client(),
    )

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="llm",
                base_url="https://llm.example/v1",
                model_name="glm-5",
                protocol="OpenAI Chat",
            ),
        ),
    )

    assert not response.ok
    assert "InvalidURL" in response.error


def test_an_unconfigured_llm_address_is_not_an_authorization_either(
    monkeypatch,
    tmp_path,
) -> None:
    """The reuse branch reads the LLM origin, so it obeys the same rule.

    ``_defaults()`` pre-fills the LLM address too, and a key that arrives from
    the environment lands on a section nobody configured. Trusting the loaded
    LLM origin there would let ``{"type": "asr"}`` steer that key to the
    built-in ASR endpoint, which shares the default origin with it - the leak
    already closed for the section's own default address, reached through the
    reuse switch instead.
    """
    _write_real_config(monkeypatch, tmp_path, {})
    monkeypatch.setenv("TEXT_API_KEY", "sk-review-env-fake")
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(type="asr"),
        ),
    )

    assert not response.ok
    assert "归属地址" in response.error
    assert not sent


def test_a_vlm_reusing_the_llm_config_probes_the_llm_origin(
    monkeypatch,
    tmp_path,
) -> None:
    """The inherited LLM key keeps its own home, so this probe must pass.

    ``use_llm`` copies the LLM credential into the VLM section without its
    provenance, and the operator never wrote a Base URL there.  Reading that
    as "no recorded home" refused the one endpoint the saved key belongs to,
    and told the operator to save an address that was already saved.
    """
    _write_real_config(
        monkeypatch,
        tmp_path,
        {**_saved_llm_only(), "vlm": {"use_llm": True}},
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(type="vlm"),
        ),
    )

    assert response.ok, response.error
    assert sent and sent[0][0].startswith("https://llm.example")
    assert sent[0][1] == "Bearer sk-review-owner-fake"


def test_a_stale_vlm_address_does_not_authorise_the_borrowed_key(
    monkeypatch,
    tmp_path,
) -> None:
    """``use_llm`` overwrites the VLM address, so it proves nothing either.

    A section that borrows the LLM credential can still hold the address saved
    before the switch was flipped. Assembly replaces it and the product never
    sends there, so the guard must not keep it as an extra host the LLM key is
    allowed to reach.
    """
    _write_real_config(
        monkeypatch,
        tmp_path,
        {
            **_saved_llm_only(),
            "vlm": {
                "use_llm": True,
                "base_url": "https://stale-vlm.example/v1",
                "api_key": "",
            },
        },
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="vlm",
                base_url="https://stale-vlm.example/v1",
                model_name="glm-5",
                protocol="OpenAI Chat",
            ),
        ),
    )

    assert not response.ok
    assert "安全限制" in response.error
    assert not sent


def test_embedding_may_probe_the_origin_that_owns_the_inherited_key(
    monkeypatch,
    tmp_path,
) -> None:
    """A transitively borrowed credential is still the LLM's credential.

    Embedding reuses the VLM key while the VLM reuses the LLM config, so the
    key in play was saved for the LLM address.  Naming the VLM as its owner
    left the LLM origin outside the trust set and refused it.
    """
    _write_real_config(
        monkeypatch,
        tmp_path,
        {
            **_saved_llm_only(),
            "vlm": {"use_llm": True},
            "embedding": {
                "base_url": "https://embedding.example/v1",
                "api_key": "",
                "reuse_vlm_key": True,
                "model_name": "qwen3-vl-embedding",
            },
        },
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="embedding",
                base_url="https://llm.example/v1",
                model_name="qwen3-vl-embedding",
            ),
        ),
    )

    assert response.ok, response.error
    assert sent and sent[0][0].startswith("https://llm.example")
    assert sent[0][1] == "Bearer sk-review-owner-fake"


def test_embedding_names_the_llm_as_the_owner_of_an_inherited_key(
    monkeypatch,
    tmp_path,
) -> None:
    """A refusal has to show the hosts the key really was saved for.

    The hint is the only thing an operator reads; listing just the embedding
    address while the LLM credential is the one at risk sends them to fix the
    wrong section.
    """
    _write_real_config(
        monkeypatch,
        tmp_path,
        {
            **_saved_llm_only(),
            "vlm": {"use_llm": True},
            "embedding": {
                "base_url": "https://embedding.example/v1",
                "api_key": "",
                "reuse_vlm_key": True,
                "model_name": "qwen3-vl-embedding",
            },
        },
    )
    sent = _real_transport_dispatch(monkeypatch)

    response = asyncio.run(
        model_routes.test_model_connection(
            ModelConnectionTestRequest(
                type="embedding",
                base_url="https://intruder.example/v1",
                model_name="qwen3-vl-embedding",
            ),
        ),
    )

    assert not response.ok
    assert "安全限制" in response.error
    assert "https://llm.example:443" in response.error
    assert "https://embedding.example:443" in response.error
    assert not sent


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("Authorization", "Bearer sk-review-query-fake"),
        ("Authorization", "Token sk-review-query-fake"),
        ("x-api-key", "sk-review-query-fake"),
        ("x-goog-api-key", "sk-review-query-fake"),
    ],
)
def test_send_probe_keeps_the_credential_out_of_the_query_string(
    header: str,
    value: str,
) -> None:
    """The transport, not one caller, owns the query-string rule.

    The filter used to sit at the two places that dispatched a probe. When
    sending was centralised, both copies disappeared without a test failing:
    ``_non_secret_probe_params`` stayed defined and its direct-call tests
    stayed green while nothing on the request path called it. Driving the one
    sender is what makes the rule survive the next refactor, and reading the
    secret back from the auth header covers every spelling a builder uses
    without threading the credential through each caller.
    """
    client = _FakeClient()

    asyncio.run(
        _send_probe(
            client,
            "https://example.test/v1",
            {header: value, "Content-Type": "application/json"},
            {
                "_get_probe": True,
                "action": "getPolicy",
                "model": "sk-review-query-fake",
            },
        ),
    )

    verb, _url, headers, params, body, _files = client.calls[0]
    assert verb == "GET"
    assert params == {"action": "getPolicy"}
    assert body is None
    # The credential still travels, but only as the header it belongs in.
    assert headers[header] == value
