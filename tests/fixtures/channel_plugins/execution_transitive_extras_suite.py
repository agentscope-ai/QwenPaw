"""Dependency closure unit evidence; real parser over explicit metadata DTOs."""
import sys

from packaging.markers import default_environment
import pytest

from qwenpaw.plugins.execution.dependencies import (
    DependencySnapshot,
    require_dependencies,
)
from qwenpaw.plugins.execution.errors import ProtocolValidationError


def snapshot(tmp_path, packages, **environment):
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    return DependencySnapshot.from_mapping(
        {
            "executable": sys.executable,
            "prefix": str(tmp_path),
            "sites": [str(site)],
            "marker_environment": {**default_environment(), **environment},
            "supported_tags": ["py3-none-any"],
            "distributions": {
                name: {
                    "version": version,
                    "metadata_path": str(
                        site / (name + "-" + version + ".dist-info")
                    ),
                    "requires_dist": list(requires),
                    "top_level": [name],
                }
                for name, (version, requires) in packages.items()
            },
        }
    )


def require(tmp_path, packages, *, root="msal>=1.20", **environment):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(root + "\n")
    return require_dependencies(
        snapshot(tmp_path, packages, **environment),
        {"requirements_path": str(requirements)},
    )


def msal_crypto(version="48.0.1"):
    return {
        "msal": ("1.39.0", ("PyJWT[crypto]<3,>=1.0.0",)),
        "pyjwt": (
            "2.13.0",
            (
                'cryptography>=3.4.0; extra == "crypto"',
                'unrequested-tests>=1; extra == "test"',
            ),
        ),
        "cryptography": (version, ()),
    }


def test_msal_transitive_crypto_extra_requires_its_installed_dependency(
    tmp_path,
):
    assert require(tmp_path, msal_crypto()) == {
        "msal",
        "pyjwt",
        "cryptography",
    }


@pytest.mark.parametrize("version", [None, "2.0"])
def test_requested_extra_missing_or_wrong_version_stays_rejected(
    tmp_path, version
):
    packages = msal_crypto(version or "48.0.1")
    if version is None:
        del packages["cryptography"]
    with pytest.raises(ProtocolValidationError) as error:
        require(tmp_path, packages)
    assert error.value.reason_code == "DEPENDENCY_UNSATISFIED"


def test_extra_union_revisits_already_seen_distribution_and_terminates_cycle(
    tmp_path,
):
    packages = {
        "msal": ("1.39.0", ("pyjwt[crypto]", "second")),
        "second": ("1.0", ("pyjwt[test]",)),
        "pyjwt": (
            "2.13.0",
            (
                'cryptography>=3; extra == "crypto"',
                'test-helper; extra == "test"',
                'msal>=1.20; extra == "crypto"',
            ),
        ),
        "cryptography": ("48.0.1", ()),
        "test-helper": ("1.0", ()),
    }
    assert require(tmp_path, packages) == set(packages)


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("Linux", {"msal", "pyjwt", "cryptography"}),
        ("Windows", {"msal", "pyjwt"}),
    ],
)
def test_requested_extra_honors_target_platform_marker(
    tmp_path, platform, expected
):
    packages = msal_crypto()
    packages["pyjwt"] = (
        "2.13.0",
        ('cryptography>=3; extra == "crypto" and sys_platform == "linux"',),
    )
    if platform == "Windows":
        del packages["cryptography"]
    assert (
        require(
            tmp_path,
            packages,
            sys_platform="linux" if platform == "Linux" else "win32",
            platform_system=platform,
        )
        == expected
    )


def test_unrequested_extra_does_not_admit_or_require_its_dependency(tmp_path):
    packages = msal_crypto()
    packages["msal"] = ("1.39.0", ("PyJWT>=2",))
    del packages["cryptography"]
    assert require(tmp_path, packages) == {"msal", "pyjwt"}


def test_active_transitive_url_remains_rejected(tmp_path):
    packages = msal_crypto()
    packages["pyjwt"] = (
        "2.13.0",
        (
            'cryptography @ https://example.invalid/package.whl ; extra == "crypto"',
        ),
    )
    with pytest.raises(ProtocolValidationError) as error:
        require(tmp_path, packages)
    assert error.value.reason_code == "DEPENDENCY_UNSATISFIED"


def test_explicit_root_extra_declaration_remains_outside_plain_contract(
    tmp_path,
):
    with pytest.raises(
        ProtocolValidationError,
        match="plain distribution requirements required",
    ):
        require(tmp_path, msal_crypto(), root="msal[broker]>=1.20")


def physical_metadata(tmp_path, *, flaw=None):
    site = tmp_path / "physical-site"
    site.mkdir()
    rows = msal_crypto()
    for name, (version, dependencies) in rows.items():
        if name == "cryptography" and flaw == "missing":
            continue
        info = site / f"{name}-{version}.dist-info"
        info.mkdir()
        extra = (
            "Version: 47.0.0\n"
            if name == "cryptography" and flaw == "malformed"
            else ""
        )
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + extra
            + "".join(f"Requires-Dist: {value}\n" for value in dependencies)
        )
        if name == "cryptography":
            provider = site / "optional_crypto_provider"
            provider.mkdir()
            (provider / "__init__.py").write_text("")
            (info / "RECORD").write_text(
                "optional_crypto_provider/__init__.py,,\n"
            )
    sites = [site]
    if flaw == "duplicate":
        second = tmp_path / "second-site"
        info = second / "cryptography-48.0.1.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text("Name: cryptography\nVersion: 48.0.1\n")
        sites.append(second)
    declaration = tmp_path / "physical-requirements.txt"
    declaration.write_text("msal>=1.20\n")
    code = tmp_path / "candidate"
    code.mkdir()
    return {
        "code_root": str(code),
        "_audit_sites": [str(site) for site in sites],
        "requirements_path": str(declaration),
    }


def test_observe_includes_requested_optional_provider_record_namespace(
    tmp_path,
):
    from qwenpaw.plugins.execution.dependencies import observe_dependencies

    packet = physical_metadata(tmp_path)
    observed = observe_dependencies(packet)
    assert (
        "optional_crypto_provider"
        in observed.distributions["cryptography"]["top_level"]
    )
    assert require_dependencies(observed, packet) == {
        "msal",
        "pyjwt",
        "cryptography",
    }


@pytest.mark.parametrize(
    "flaw,reason",
    [
        ("duplicate", "DEPENDENCY_ENVIRONMENT_AMBIGUOUS"),
        ("malformed", "DEPENDENCY_METADATA_INVALID"),
    ],
)
def test_observe_refuses_invalid_requested_optional_metadata(
    tmp_path, flaw, reason
):
    from qwenpaw.plugins.execution.dependencies import observe_dependencies

    packet = physical_metadata(tmp_path, flaw=flaw)
    with pytest.raises(ProtocolValidationError) as error:
        observe_dependencies(packet)
    assert error.value.reason_code == reason


def test_observe_and_require_do_not_invent_missing_optional_provider(tmp_path):
    from qwenpaw.plugins.execution.dependencies import observe_dependencies

    packet = physical_metadata(tmp_path, flaw="missing")
    observed = observe_dependencies(packet)
    assert "cryptography" not in observed.distributions
    with pytest.raises(ProtocolValidationError) as error:
        require_dependencies(observed, packet)
    assert error.value.reason_code == "DEPENDENCY_UNSATISFIED"
