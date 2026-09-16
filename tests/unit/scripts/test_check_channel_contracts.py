# -*- coding: utf-8 -*-
"""Tests for the static channel contract coverage checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent, indent

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_channel_contracts.py"
SPEC = importlib.util.spec_from_file_location(
    "check_channel_contracts",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def _write(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def _alpha_contract(
    factory_body: str | None = None,
    *,
    module_prefix: str = "",
    class_body: str = "",
    class_name: str = "TestAlphaContract",
    base_name: str = "ChannelContractTest",
) -> str:
    """Build one small Alpha contract module."""
    if factory_body is None:
        factory_body = """
        from qwenpaw.app.channels.alpha import AlphaChannel
        return AlphaChannel()
        """

    sections: list[str] = []
    if module_prefix.strip():
        sections.append(dedent(module_prefix).strip())
    sections.extend(
        [
            "from tests.contract.channels import ChannelContractTest",
            f"class {class_name}({base_name}):",
        ],
    )
    if class_body.strip():
        sections.append(indent(dedent(class_body).strip(), "    "))
    sections.extend(
        [
            "    def create_instance(self):",
            indent(dedent(factory_body).strip(), "        "),
        ],
    )
    return "\n\n".join(sections) + "\n"


def _build_repo(repo_root: Path) -> None:
    _write(
        repo_root,
        "src/qwenpaw/app/channels/registry.py",
        """
        _BUILTIN_SPECS = {
            "alpha": (".alpha", "AlphaChannel"),
            "sip": (".sip", "SIPChannel"),
        }
        """,
    )
    _write(
        repo_root,
        "src/qwenpaw/app/channels/base.py",
        "class BaseChannel: pass\n",
    )
    _write(
        repo_root,
        "src/qwenpaw/app/channels/alpha/__init__.py",
        "from .channel import AlphaChannel\n",
    )
    _write(
        repo_root,
        "src/qwenpaw/app/channels/alpha/channel.py",
        """
        from ..base import BaseChannel

        class Mixin:
            pass

        class Intermediate(BaseChannel):
            pass

        class AlphaChannel(Intermediate, Mixin):
            pass
        """,
    )
    _write(
        repo_root,
        "src/qwenpaw/app/channels/sip/__init__.py",
        """
        # UTF-8 fixture: 中文 — SIP can live in a package initializer.
        from ..base import BaseChannel

        class SIPChannel(BaseChannel):
            pass
        """,
    )
    _write(
        repo_root,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(),
    )
    _write(
        repo_root,
        "tests/contract/channels/test_sip_contract.py",
        """
        from tests.contract.channels import ChannelContractTest

        class TestSIPContract(ChannelContractTest):
            def create_instance(self):
                from qwenpaw.app.channels.sip import SIPChannel
                return SIPChannel()
        """,
    )


def _assert_alpha_missing(
    report,
    message: str,
    registry_key: str = "alpha",
) -> None:
    assert "AlphaChannel" not in report.tested_classes
    assert [spec.key for spec in report.missing_specs] == [registry_key]
    assert any(message in error for error in report.errors)


def test_analyze_repository_uses_registry_and_utf8_ast(
    tmp_path: Path,
) -> None:
    _build_repo(tmp_path)

    report = checker.analyze_repository(tmp_path)

    assert [spec.key for spec in report.specs] == ["alpha", "sip"]
    assert report.tested_classes == {"AlphaChannel", "SIPChannel"}
    assert report.missing_specs == ()
    assert report.errors == ()


def test_registry_key_drives_canonical_test_filename(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    registry = tmp_path / "src/qwenpaw/app/channels/registry.py"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace('"alpha"', '"primary"'),
        encoding="utf-8",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(
        report,
        "test_primary_contract.py",
        registry_key="primary",
    )


@pytest.mark.parametrize(
    "registry_source",
    [
        '_BUILTIN_SPECS = dict(alpha=(".alpha", "AlphaChannel"))',
        """
        _BUILTIN_SPECS = {"alpha": (".alpha", "AlphaChannel")}
        _BUILTIN_SPECS["sip"] = (".sip", "SIPChannel")
        """,
        """
        _BUILTIN_SPECS = {"alpha": (".alpha", "AlphaChannel")}
        alias = _BUILTIN_SPECS
        """,
        """
        _BUILTIN_SPECS = {"alpha": (".alpha", "AlphaChannel")}
        consume(_BUILTIN_SPECS)
        """,
    ],
)
def test_dynamic_registry_fails_closed(
    tmp_path: Path,
    registry_source: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "src/qwenpaw/app/channels/registry.py",
        registry_source,
    )

    with pytest.raises(checker.CoverageCheckError):
        checker.load_builtin_specs(tmp_path)


def test_registry_allows_known_read_only_views(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    registry = tmp_path / "src/qwenpaw/app/channels/registry.py"
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "\nkeys = frozenset(_BUILTIN_SPECS.keys())\n"
        + "for key, value in _BUILTIN_SPECS.items():\n    pass\n",
        encoding="utf-8",
    )

    specs = checker.load_builtin_specs(tmp_path)

    assert [spec.key for spec in specs] == ["alpha", "sip"]


@pytest.mark.parametrize("key", ["Alpha", "../alpha", "alpha\tbeta", "中文"])
def test_registry_key_must_be_runner_safe(tmp_path: Path, key: str) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "src/qwenpaw/app/channels/registry.py",
        f'_BUILTIN_SPECS = {{{key!r}: (".alpha", "AlphaChannel")}}',
    )

    with pytest.raises(checker.CoverageCheckError, match="invalid.*key"):
        checker.load_builtin_specs(tmp_path)


def test_package_must_export_registered_class(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "src/qwenpaw/app/channels/alpha/__init__.py",
        "# AlphaChannel is intentionally not exported.\n",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "does not export AlphaChannel")


@pytest.mark.parametrize(
    "mutation",
    [
        "AlphaChannel = object",
        "del AlphaChannel",
        "if enabled:\n    from .other import AlphaChannel",
    ],
)
def test_source_export_rebinding_is_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    _build_repo(tmp_path)
    package = tmp_path / "src/qwenpaw/app/channels/alpha/__init__.py"
    package.write_text(
        package.read_text(encoding="utf-8") + "\n" + mutation + "\n",
        encoding="utf-8",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "does not export AlphaChannel")


def test_local_fake_base_channel_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "src/qwenpaw/app/channels/alpha/channel.py",
        """
        class BaseChannel:
            pass

        class AlphaChannel(BaseChannel):
            pass
        """,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "canonical BaseChannel")


def test_unbound_dotted_base_channel_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "src/qwenpaw/app/channels/alpha/channel.py",
        """
        class AlphaChannel(qwenpaw.app.channels.base.BaseChannel):
            pass
        """,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "canonical BaseChannel")


def test_unrelated_same_named_import_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            """
            from unrelated import AlphaChannel
            return AlphaChannel()
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "must directly return a registered channel")


def test_non_returned_constructor_does_not_count(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            AlphaChannel()
            return object()
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "must directly return a registered channel")


def test_factory_import_rebinding_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            AlphaChannel = object
            return AlphaChannel()
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "must directly return a registered channel")


@pytest.mark.parametrize("factory_name", ["from_config", "from_env"])
def test_direct_registered_class_factory_counts(
    tmp_path: Path,
    factory_name: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            f"""
            from qwenpaw.app.channels.alpha import AlphaChannel
            return AlphaChannel.{factory_name}({{}})
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    assert report.errors == ()
    assert report.missing_specs == ()


@pytest.mark.parametrize(
    ("factory_body", "node_name"),
    [
        (
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            if enabled:
                return AlphaChannel()
            return AlphaChannel()
            """,
            "If",
        ),
        (
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            try:
                value = AlphaChannel()
            except Exception:
                value = AlphaChannel()
            return value
            """,
            "Try",
        ),
        (
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            for _ in range(1):
                value = AlphaChannel()
            return value
            """,
            "For",
        ),
        (
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            while ready:
                break
            return AlphaChannel()
            """,
            "While",
        ),
        (
            """
            from qwenpaw.app.channels.alpha import AlphaChannel
            def build():
                return AlphaChannel()
            return build()
            """,
            "FunctionDef",
        ),
    ],
)
def test_factory_control_flow_fails_closed(
    tmp_path: Path,
    factory_body: str,
    node_name: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(factory_body),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, f"straight-line code; found {node_name}")


@pytest.mark.parametrize(
    ("factory_source", "message"),
    [
        (
            """
            async def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
            """,
            "must be synchronous",
        ),
        (
            """
            @staticmethod
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
            """,
            "must not use decorators",
        ),
        (
            """
            def create_instance(self, AlphaChannel):
                return AlphaChannel()
            """,
            "signature create_instance(self)",
        ),
        (
            """
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
            create_instance = lambda self: object()
            """,
            "exactly one class-level binding",
        ),
        (
            """
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
            def create_instance(self):
                return object()
            """,
            "exactly one class-level binding",
        ),
    ],
)
def test_factory_shape_fails_closed(
    tmp_path: Path,
    factory_source: str,
    message: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        dedent(
            """
            from tests.contract.channels import ChannelContractTest

            class TestAlphaContract(ChannelContractTest):
            """,
        ).lstrip()
        + indent(dedent(factory_source).strip(), "    ")
        + "\n",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, message)


def test_explicit_abstract_contract_helper_is_ignored(
    tmp_path: Path,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        """
        from abc import abstractmethod
        from tests.contract.channels import ChannelContractTest

        class AbstractAlphaContract(ChannelContractTest):
            @abstractmethod
            def create_instance(self):
                raise NotImplementedError

        class TestAlphaContract(AbstractAlphaContract):
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
        """,
    )

    report = checker.analyze_repository(tmp_path)

    assert report.errors == ()
    assert report.missing_specs == ()


def test_contract_class_name_must_be_collectable(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(class_name="AlphaContract"),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "name must start with Test")


@pytest.mark.parametrize("method_name", ["__init__", "__new__"])
def test_collection_constructor_is_rejected(
    tmp_path: Path,
    method_name: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            class_body=f"def {method_name}(self):\n    pass",
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, f"defines {method_name}")


def test_external_contract_mixin_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    source = _alpha_contract(
        module_prefix="from external import CollectionMixin",
    ).replace(
        "class TestAlphaContract(ChannelContractTest)",
        "class TestAlphaContract(ChannelContractTest, CollectionMixin)",
    )
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        source,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "uses external contract base")


@pytest.mark.parametrize(
    "mutation",
    [
        "TestAlphaContract.__test__ = False",
        "TestAlphaContract = object",
        "del TestAlphaContract",
        "Alias = TestAlphaContract\nAlias.__test__ = False",
        'Alias = TestAlphaContract\nsetattr(Alias, "__test__", False)',
    ],
)
def test_post_declaration_contract_mutation_is_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    _build_repo(tmp_path)
    path = tmp_path / "tests/contract/channels/test_alpha_contract.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n" + mutation + "\n",
        encoding="utf-8",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "contract class TestAlphaContract")


@pytest.mark.parametrize("scope", ["module", "class"])
def test_pytest_generate_tests_fails_closed(
    tmp_path: Path,
    scope: str,
) -> None:
    _build_repo(tmp_path)
    hook = """
    def pytest_generate_tests(metafunc):
        metafunc.parametrize("instance", [])
    """
    kwargs = (
        {"module_prefix": hook} if scope == "module" else {"class_body": hook}
    )
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(**kwargs),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, f"{scope}-level pytest_generate_tests")


def test_contract_factory_must_use_canonical_path(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    original = tmp_path / "tests/contract/channels/test_alpha_contract.py"
    original.unlink()
    _write(
        tmp_path,
        "tests/contract/channels/test_wrong_contract.py",
        _alpha_contract(),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "test_alpha_contract.py")


def test_duplicate_contract_factories_are_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    path = tmp_path / "tests/contract/channels/test_alpha_contract.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + _alpha_contract(class_name="TestSecondAlphaContract"),
        encoding="utf-8",
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "duplicate contract factories")


@pytest.mark.parametrize(
    "module_prefix",
    [
        'import pytest\npytest.importorskip("optional_dependency")',
        'import pytest\npytest.skip("disabled", allow_module_level=True)',
        'import pytest\npytest.xfail("disabled")',
        'from pytest import skip as stop\nstop("disabled")',
        'import pytest\npytestmark = pytest.mark.skip(reason="disabled")',
        'import pytest\npytestmark = [pytest.mark.xfail(reason="disabled")]',
    ],
)
def test_module_collection_gates_are_rejected(
    tmp_path: Path,
    module_prefix: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(module_prefix=module_prefix),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "pytest")


def test_module_pytestmark_fails_closed(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest\npytestmark = pytest.mark.contract",
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "uses module-level pytestmark")


def test_dynamic_module_pytestmark_is_rejected(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="""
            import pytest
            pytestmark = pytest.mark.contract
            marks = pytestmark
            marks.append(pytest.mark.skip(reason="disabled"))
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "uses module-level pytestmark")


def test_literal_false_module_gate_still_fails_closed(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="""
            import pytest
            if False:
                pytest.importorskip("optional_dependency")
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "pytest.importorskip")


@pytest.mark.parametrize(
    ("class_body", "message"),
    [
        (
            '@pytest.mark.skip(reason="disabled")',
            "class decorator pytest.mark.skip",
        ),
        (
            'pytestmark = pytest.mark.skipif(True, reason="disabled")',
            "uses class-level pytestmark",
        ),
        ("__test__ = False", "uses class-level __test__"),
        ("__test__ = True", "uses class-level __test__"),
    ],
)
def test_class_collection_gates_are_rejected(
    tmp_path: Path,
    class_body: str,
    message: str,
) -> None:
    _build_repo(tmp_path)
    if class_body.startswith("@"):
        source = _alpha_contract(module_prefix="import pytest").replace(
            "class TestAlphaContract",
            f"{class_body}\nclass TestAlphaContract",
        )
    else:
        source = _alpha_contract(
            module_prefix="import pytest",
            class_body=class_body,
        )
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        source,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, message)


def test_class_pytestmark_fails_closed(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest",
            class_body="pytestmark = pytest.mark.contract",
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "uses class-level pytestmark")


def test_disabled_marker_is_inherited_from_local_contract_base(
    tmp_path: Path,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        """
        import pytest
        from tests.contract.channels import ChannelContractTest

        @pytest.mark.skip(reason="disabled")
        class AlphaContractBase(ChannelContractTest):
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()

        class TestAlphaContract(AlphaContractBase):
            pass
        """,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "inherits disabled contract base")


@pytest.mark.parametrize(
    "factory_body",
    [
        """
        import pytest
        from qwenpaw.app.channels.alpha import AlphaChannel
        pytest.skip("disabled")
        return AlphaChannel()
        """,
        """
        from pytest import importorskip as require
        from qwenpaw.app.channels.alpha import AlphaChannel
        require("optional_dependency")
        return AlphaChannel()
        """,
        """
        import pytest
        from qwenpaw.app.channels.alpha import AlphaChannel
        pytest.xfail("disabled")
        return AlphaChannel()
        """,
    ],
)
def test_factory_pytest_gates_are_rejected(
    tmp_path: Path,
    factory_body: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(factory_body),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "references pytest")


def test_autouse_fixture_cannot_skip_contract(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest",
            class_body="""
            @pytest.fixture(autouse=True)
            def require_dependency(self):
                pytest.importorskip("optional_dependency")
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "autouse fixture")


def test_dynamic_autouse_fixture_fails_closed(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest\nAUTO = True",
            class_body="""
            @pytest.fixture(autouse=AUTO)
            def require_dependency(self):
                pytest.skip("disabled")
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "uses dynamic autouse")


@pytest.mark.parametrize(
    "module_gate",
    [
        """
        @pytest.fixture(autouse=True)
        def require_dependency():
            pytest.skip("disabled")
        """,
        """
        def setup_module():
            pytest.importorskip("optional_dependency")
        """,
    ],
)
def test_module_runtime_gate_is_rejected(
    tmp_path: Path,
    module_gate: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest\n" + dedent(module_gate),
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "references pytest")


@pytest.mark.parametrize("hook_name", ["setup_class", "setup_method"])
def test_inherited_setup_gate_is_rejected(
    tmp_path: Path,
    hook_name: str,
) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        f"""
        import pytest
        from tests.contract.channels import ChannelContractTest

        class AlphaContractBase(ChannelContractTest):
            def {hook_name}(self):
                pytest.skip("disabled")

            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()

        class TestAlphaContract(AlphaContractBase):
            def create_instance(self):
                from qwenpaw.app.channels.alpha import AlphaChannel
                return AlphaChannel()
        """,
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "inherits contract base with setup hook")


def test_contract_cannot_override_instance_fixture(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    _write(
        tmp_path,
        "tests/contract/channels/test_alpha_contract.py",
        _alpha_contract(
            module_prefix="import pytest",
            class_body="""
            @pytest.fixture
            def instance(self):
                pytest.skip("disabled")
            """,
        ),
    )

    report = checker.analyze_repository(tmp_path)

    _assert_alpha_missing(report, "overrides the contract instance fixture")


def test_skip_in_unrelated_test_method_is_allowed(tmp_path: Path) -> None:
    _build_repo(tmp_path)
    path = tmp_path / "tests/contract/channels/test_alpha_contract.py"
    path.write_text(
        "import pytest\n"
        + path.read_text(encoding="utf-8")
        + "\ndef test_optional_behavior():\n"
        + '    pytest.skip("optional behavior")\n',
        encoding="utf-8",
    )

    report = checker.analyze_repository(tmp_path)

    assert report.errors == ()
    assert report.missing_specs == ()


def test_repository_has_complete_contract_coverage() -> None:
    report = checker.analyze_repository(REPO_ROOT)

    assert len(report.specs) == 18
    assert len(report.tested_classes) == 18
    assert report.missing_specs == ()
    assert report.errors == ()
