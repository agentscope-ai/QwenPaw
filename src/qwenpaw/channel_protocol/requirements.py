# -*- coding: utf-8 -*-
"""Canonicalize PEP 508 requirements used by Channel descriptors."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, Specifier
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .canonical import normalize_string
from .errors import validation_error


_PERCENT_TRIPLET = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~",
)


def _normalize_percent(value: str) -> str:
    for index, character in enumerate(value):
        if character == "%" and _PERCENT_TRIPLET.match(value, index) is None:
            raise validation_error("Requirement URL percent escape is invalid")

    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        if character in _UNRESERVED:
            return character
        return f"%{match.group(1).upper()}"

    return _PERCENT_TRIPLET.sub(replace, value)


# RFC 3986 section 5.2.4 defines this as an ordered branch state machine.
# pylint: disable=too-many-branches
def _remove_dot_segments(path: str) -> str:
    input_path = path
    output: list[str] = []
    while input_path:
        if input_path.startswith("../"):
            input_path = input_path[3:]
        elif input_path.startswith("./"):
            input_path = input_path[2:]
        elif input_path.startswith("/./"):
            input_path = f"/{input_path[3:]}"
        elif input_path == "/.":
            input_path = "/"
        elif input_path.startswith("/../"):
            input_path = f"/{input_path[4:]}"
            if output:
                output.pop()
        elif input_path == "/..":
            input_path = "/"
            if output:
                output.pop()
        elif input_path in {".", ".."}:
            input_path = ""
        else:
            start = 1 if input_path.startswith("/") else 0
            next_slash = input_path.find("/", start)
            if next_slash < 0:
                segment = input_path
                input_path = ""
            else:
                segment = input_path[:next_slash]
                input_path = input_path[next_slash:]
            output.append(segment)
    return "".join(output)


# pylint: enable=too-many-branches


def _canonical_host(parts: SplitResult) -> str:
    hostname = parts.hostname
    if hostname is None:
        return ""
    try:
        parsed_ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            return hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise validation_error("Requirement URL host is invalid") from exc
    if parsed_ip.version == 6:
        return f"[{parsed_ip.compressed}]"
    return parsed_ip.compressed


def _canonical_url(value: str) -> str:
    value = normalize_string(value)
    if not value or any(character.isspace() for character in value):
        raise validation_error(
            "Requirement URL must be non-empty and contain no whitespace",
        )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise validation_error("Requirement URL is invalid") from exc
    scheme = parts.scheme.lower()
    if not scheme:
        raise validation_error("Requirement URL must be absolute")
    if parts.username is not None or parts.password is not None:
        raise validation_error("Requirement URL must not contain user info")
    host = _canonical_host(parts)
    if parts.netloc and not host:
        raise validation_error("Requirement URL host is invalid")
    if scheme in {"http", "https"} and not host:
        raise validation_error("HTTP(S) requirement URL requires a host")

    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host
    if port is not None and not default_port:
        netloc = f"{netloc}:{port}"
    path = _remove_dot_segments(_normalize_percent(parts.path))
    if scheme in {"http", "https"} and not path:
        path = "/"
    query = _normalize_percent(parts.query)
    fragment = _normalize_percent(parts.fragment)
    return urlunsplit((scheme, netloc, path, query, fragment))


def _canonical_specifier(specifier: Specifier) -> str:
    operator = specifier.operator
    version = normalize_string(specifier.version)
    if operator == "===":
        canonical_version = version
    else:
        wildcard = operator in {"==", "!="} and version.endswith(".*")
        candidate = version[:-2] if wildcard else version
        try:
            canonical_version = str(Version(candidate))
        except InvalidVersion as exc:
            raise validation_error(
                "Requirement specifier contains an invalid version",
            ) from exc
        if wildcard:
            canonical_version = f"{canonical_version}.*"
    try:
        Specifier(f"{operator}{version}")
    except InvalidSpecifier as exc:
        raise validation_error("Requirement specifier is invalid") from exc
    return f"{operator}{canonical_version}"


def _marker_operand(value: object) -> tuple[str, bool]:
    raw = normalize_string(str(value))
    class_name = value.__class__.__name__
    if class_name == "Variable":
        return raw.lower(), True
    if class_name == "Value":
        escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"', False
    raise validation_error("Requirement marker operand is invalid")


@dataclass(frozen=True)
class _MarkerNode:
    operator: str | None
    children: tuple["_MarkerNode", ...] = ()
    comparison: str = ""
    references_extra: bool = False

    @property
    def precedence(self) -> int:
        if self.operator == "or":
            return 1
        if self.operator == "and":
            return 2
        return 3

    def render(self, *, parent_precedence: int = 0) -> str:
        if self.operator is None:
            return self.comparison
        rendered = f" {self.operator} ".join(
            child.render(parent_precedence=self.precedence)
            for child in self.children
        )
        if self.precedence < parent_precedence:
            return f"({rendered})"
        return rendered


def _comparison_node(value: tuple[object, object, object]) -> _MarkerNode:
    left, left_is_variable = _marker_operand(value[0])
    right, right_is_variable = _marker_operand(value[2])
    operator = normalize_string(str(value[1])).lower()
    references_extra = (left_is_variable and left == "extra") or (
        right_is_variable and right == "extra"
    )
    return _MarkerNode(
        operator=None,
        comparison=f"{left} {operator} {right}",
        references_extra=references_extra,
    )


def _logical_node(operator: str, children: list[_MarkerNode]) -> _MarkerNode:
    flattened: list[_MarkerNode] = []
    for child in children:
        if child.operator == operator:
            flattened.extend(child.children)
        else:
            flattened.append(child)
    ordered = sorted(flattened, key=lambda child: child.render())
    rendered = [child.render() for child in ordered]
    if len(rendered) != len(set(rendered)):
        raise validation_error(
            "Requirement marker contains a duplicate boolean term",
        )
    return _MarkerNode(
        operator=operator,
        children=tuple(ordered),
        references_extra=any(child.references_extra for child in ordered),
    )


def _split_marker_items(
    items: list[object],
    operator: str,
) -> list[list[object]]:
    groups: list[list[object]] = [[]]
    for item in items:
        if item == operator:
            groups.append([])
        else:
            groups[-1].append(item)
    if any(not group for group in groups):
        raise validation_error("Requirement marker expression is invalid")
    return groups


def _marker_node(items: list[object]) -> _MarkerNode:
    or_groups = _split_marker_items(items, "or")
    if len(or_groups) > 1:
        return _logical_node(
            "or",
            [_marker_node(group) for group in or_groups],
        )
    and_groups = _split_marker_items(items, "and")
    if len(and_groups) > 1:
        return _logical_node(
            "and",
            [_marker_node(group) for group in and_groups],
        )
    item = items[0]
    if isinstance(item, list):
        return _marker_node(item)
    if isinstance(item, tuple) and len(item) == 3:
        return _comparison_node(item)
    raise validation_error("Requirement marker expression is invalid")


def _canonical_marker(requirement: Requirement) -> str:
    marker = requirement.marker
    if marker is None:
        return ""
    raw_items = getattr(marker, "_markers", None)
    if not isinstance(raw_items, list):
        raise validation_error("Requirement marker AST is unavailable")
    node = _marker_node(raw_items)
    if node.references_extra:
        raise validation_error(
            "Requirement markers must not reference extra",
        )
    return node.render()


def canonicalize_requirement(value: str) -> str:
    """Return the unique descriptor representation of one requirement."""
    if not isinstance(value, str):
        raise validation_error("Requirement must be a string")
    try:
        requirement = Requirement(normalize_string(value))
    except InvalidRequirement as exc:
        raise validation_error("Requirement is not valid PEP 508") from exc

    name = str(canonicalize_name(requirement.name))
    extras = sorted(
        {str(canonicalize_name(extra)) for extra in requirement.extras},
    )
    base = name
    if extras:
        base = f"{base}[{','.join(extras)}]"

    if requirement.url:
        if list(requirement.specifier):
            raise validation_error(
                "Requirement cannot contain both URL and specifiers",
            )
        base = f"{base} @ {_canonical_url(requirement.url)}"
    else:
        specifiers = sorted(
            {_canonical_specifier(item) for item in requirement.specifier},
        )
        if specifiers:
            base = f"{base}{','.join(specifiers)}"

    marker = _canonical_marker(requirement)
    if marker:
        return f"{base} ; {marker}"
    return base


def canonicalize_requirements(values: list[str]) -> tuple[str, ...]:
    """Canonicalize, sort, and deduplicate a requirement array."""
    if not isinstance(values, list):
        raise validation_error("Requirement collection must be an array")
    return tuple(sorted({canonicalize_requirement(value) for value in values}))
