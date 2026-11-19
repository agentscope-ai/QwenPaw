# -*- coding: utf-8 -*-
"""Argument-aware matching for bundled outbound shell signatures."""
from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from itertools import chain

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

_BASH = Language(tree_sitter_bash.language())

# A short option taking a value consumes the rest of its cluster, or the
# following argument. Other short flags can precede it in any order.
_SHORT_VALUES = frozenset("AbcCdDeEFHhKmoPQrTtuUwXxyYz")
_SHORT_OPTIONS = {
    "d": "data",
    "F": "form",
    "G": "get",
    "T": "upload-file",
    "X": "request",
    ":": "next",
}
_DATA = {"data", "data-ascii", "data-binary", "data-raw", "data-urlencode"}
_UPLOAD = {"form", "form-string", "upload-file", "json"}
# Consume operands even if they look like flags (e.g. --header '--get').
_LONG_VALUES = (
    frozenset(
        """
    abstract-unix-socket alt-svc aws-sigv4 cacert capath cert cert-type
    ciphers config connect-timeout connect-to continue-at cookie cookie-jar
    create-file-mode crlfile curves delegation dns-interface dns-ipv4-addr
    dns-ipv6-addr dns-servers doh-url dump-header ech egd-file engine
    etag-compare etag-save expect100-timeout ftp-account ftp-alternative-to-user
    ftp-method ftp-port ftp-ssl-ccc-mode happy-eyeballs-timeout-ms
    haproxy-clientip header hostpubmd5 hostpubsha256 hsts interface ipfs-gateway
    keepalive-cnt keepalive-time key key-type krb libcurl limit-rate local-port
    login-options mail-auth mail-from mail-rcpt max-filesize max-redirs max-time
    netrc-file noproxy oauth2-bearer output output-dir parallel-max pass
    pinnedpubkey proto proto-default proto-redir proxy proxy-cacert proxy-capath
    proxy-cert proxy-cert-type proxy-ciphers proxy-crlfile proxy-header
    proxy-key proxy-key-type proxy-pass proxy-pinnedpubkey proxy-service-name
    proxy-tls13-ciphers proxy-tlsauthtype proxy-tlspassword proxy-tlsuser
    proxy-user proxy1.0 pubkey quote random-file range rate referer request
    request-target resolve retry retry-delay retry-max-time sasl-authzid
    service-name socks4 socks4a socks5 socks5-gssapi-service socks5-hostname
    speed-limit speed-time stderr telnet-option tftp-blksize time-cond tls-max
    tls13-ciphers tlsauthtype tlspassword tlsuser trace trace-ascii trace-config
    unix-socket url url-query user user-agent variable write-out
    """.split(),
    )
    | _DATA
    | _UPLOAD
)


def _curl_options(args: list[str]) -> Iterator[tuple[str, str]]:
    words = iter(args)
    for word in words:
        if word == "--":
            break
        if word.startswith("--"):
            name, equals, value = word[2:].partition("=")
            if not equals and name in _LONG_VALUES:
                value = next(words, "")
            yield name, value
        elif word.startswith("-"):
            for index, flag in enumerate(word[1:], start=2):
                name = _SHORT_OPTIONS.get(flag, flag)
                if flag in _SHORT_VALUES:
                    yield name, word[index:] or next(words, "")
                    break
                yield name, ""


def _curl_sends(args: list[str]) -> bool:
    get = data = False
    method = ""
    # A synthetic final --next evaluates the last transfer the same way.
    for name, value in chain(_curl_options(args), [("next", "")]):
        if name == "next":
            if (data and not get) or method in {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            }:
                return True
            get = data = False
            method = ""
        elif name in {"get", "no-get"}:
            get = name == "get"
        elif name == "request":
            method = value.upper()
        elif name in _UPLOAD:
            return True
        elif name in _DATA:
            data = True
            # GET can still send a local file in its query string.
            if name == "data-urlencode":
                if "@" in value.split("=", 1)[0]:
                    return True
            elif name != "data-raw" and value.startswith("@"):
                return True
    return False


def _word(node: Node) -> str:
    raw = (node.text or b"").decode("utf-8")
    try:
        parts = shlex.split(raw)
    except ValueError:
        return raw
    return parts[0] if len(parts) == 1 else raw


_WRAPPER_VALUES: dict[str, set[str]] = {
    "command": set(),
    "env": {"-u", "--unset", "-C", "--chdir"},
    "exec": {"-a"},
    "sudo": {"-u", "--user", "-g", "--group", "-D", "--chdir"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
    "xargs": {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"},
}


def _command_index(args: list[str]) -> int:
    """Locate the executable through common shell command wrappers."""
    index = 0
    while index < len(args):
        wrapper = args[index].rsplit("/", 1)[-1]
        if wrapper not in _WRAPPER_VALUES:
            break
        index += 1
        while index < len(args) and args[index].startswith("-"):
            flag = args[index]
            if wrapper == "command" and ("v" in flag or "V" in flag):
                return len(args)
            index += 1
            if flag == "--":
                break
            if flag in _WRAPPER_VALUES[wrapper]:
                index += 1
        if wrapper == "env":
            while index < len(args) and "=" in args[index]:
                index += 1
        if wrapper == "timeout":
            index += 1  # duration
    return index


def _matching_command(
    pattern: re.Pattern[str],
    command: Node,
    value: str,
    source: bytes,
    depth: int,
) -> re.Match[str] | None:
    name = command.child_by_field_name("name")
    if name is None:
        return None
    nodes = [name, *command.children_by_field_name("argument")]
    args = [_word(node) for node in nodes]
    index = _command_index(args)
    if index >= len(args):
        return None
    executable = args[index].rsplit("/", 1)[-1].lower().removesuffix(".exe")
    rest = args[index + 1 :]
    node = nodes[index]
    if executable in {"bash", "sh", "zsh", "dash", "ksh"}:
        for position, flag in enumerate(rest[:-1]):
            if flag.startswith("-") and "c" in flag[1:]:
                script = rest[position + 1]
                if depth < 8 and not search_rule_pattern(
                    pattern,
                    script,
                    depth + 1,
                ):
                    return None
                node = nodes[index + position + 2]
                break
        else:
            return None
    elif not pattern.fullmatch(executable):
        return None
    elif executable == "curl" and not _curl_sends(rest):
        return None
    elif executable == "himalaya" and not any(
        pair == ("message", "send") for pair in zip(rest, rest[1:])
    ):
        return None
    start = len(source[: node.start_byte].decode("utf-8"))
    return pattern.search(
        value,
        start,
        start + len((node.text or b"").decode()),
    )


def search_rule_pattern(
    pattern: re.Pattern[str],
    value: str,
    depth: int = 0,
) -> re.Match[str] | None:
    """Resolve outbound executable captures in their shell command context."""
    match = pattern.search(value)
    if not match or "outbound_executable" not in pattern.groupindex:
        return match
    source = value.encode("utf-8")
    root = Parser(_BASH).parse(source).root_node
    if root.has_error:
        return match
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type == "command":
            hit = _matching_command(pattern, node, value, source, depth)
            if hit:
                return hit
        pending.extend(reversed(node.named_children))
    return None
