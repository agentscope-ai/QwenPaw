"""Static scope and known auth custody; real readers/owners, no Agent mocks."""

from importlib import import_module
from pathlib import Path


def auth_api():
    return import_module("qwenpaw.app.channels.wechat_auth_custody")


def test_default_auth_realpaths_equal_explicit_original_global_paths(tmp_path):
    api = auth_api()
    assert api.wechat_auth_scopes({}, working_dir=tmp_path) == (
        api.wechat_auth_scopes(
            {"bot_token_file": str(tmp_path / "wechat_bot_token")},
            working_dir=tmp_path,
        )
    )


def test_custom_token_names_in_one_directory_still_share_context_custody(
    tmp_path,
):
    api = auth_api()
    a = set(
        api.wechat_auth_scopes(
            {"bot_token_file": str(tmp_path / "a-token")}, working_dir=tmp_path
        )
    )
    b = set(
        api.wechat_auth_scopes(
            {"bot_token_file": str(tmp_path / "b-token")}, working_dir=tmp_path
        )
    )
    assert a & b  # The original same-parent context filename collides.
    assert a != b  # Token realpaths must still remain distinct.


def test_known_token_hash_claims_include_domain_and_never_expose_secret(
    tmp_path,
):
    api = auth_api()

    def scopes(name, domain):
        return set(
            api.wechat_auth_scopes(
                {
                    "bot_token_file": str(tmp_path / name / "token"),
                    "bot_token": "local-secret-do-not-expose",
                    "base_url": domain,
                },
                working_dir=tmp_path,
            )
        )

    a = scopes("A", "https://wx.test/")
    b = scopes("B", "https://wx.test")
    c = scopes("C", "https://other.test")
    assert a & b
    assert not a & c
    assert all("local-secret-do-not-expose" not in item for item in a | b | c)


def test_auth_scope_normalization_resolves_symlink_without_reading_files(
    tmp_path, monkeypatch
):
    api = auth_api()
    physical = tmp_path / "physical"
    physical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    token = physical / "token"
    token.write_bytes(b"historical-token")
    context = physical / "wechat_context_tokens.json"
    context.write_bytes(b'{"user":"historical-context"}')
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (token, context)
    }

    def forbidden_read(*args, **kwargs):
        raise AssertionError(
            "HTTP auth custody must not read auth file contents"
        )

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", forbidden_read)
        patch.setattr(Path, "read_bytes", forbidden_read)
        a = api.wechat_auth_scopes(
            {"bot_token_file": str(alias / "token")}, working_dir=tmp_path
        )
        b = api.wechat_auth_scopes(
            {"bot_token_file": str(token)}, working_dir=tmp_path
        )
    assert a == b
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (token, context)
    }
