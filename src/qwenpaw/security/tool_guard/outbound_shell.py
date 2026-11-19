# -*- coding: utf-8 -*-
"""Argument-aware matching for bundled outbound shell signatures."""
from __future__ import annotations

import ntpath
import re
import shlex
import sys
from collections.abc import Iterator
from itertools import chain

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

_BASH = Language(tree_sitter_bash.language())
_WINDOWS = sys.platform == "win32"

# A short option taking a value consumes the rest of its cluster, or the
# following argument. Other short flags can precede it in any order.
_SHORT_VALUES = frozenset("AbcCdDeEFHhKmoPQrTtuUwXxyYz")
_SHORT_OPTIONS = {
    "d": "data",
    "F": "form",
    "G": "get",
    "K": "config",
    "T": "upload-file",
    "X": "request",
    ":": "next",
}
_DATA = {"data", "data-ascii", "data-binary", "data-raw", "data-urlencode"}
_UPLOAD = {"form", "form-string", "upload-file", "json"}
_READ_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _method_needs_approval(method: str) -> bool:
    return method not in _READ_METHODS


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
            if (data and not get) or (
                method and _method_needs_approval(method)
            ):
                return True
            get = data = False
            method = ""
        elif name in {"get", "no-get"}:
            get = name == "get"
        elif name == "request":
            method = value
        elif name == "config" or name in _UPLOAD:
            return True
        elif name in {"data-urlencode", "url-query"}:
            # --url-query +text appends the literal text without encoding.
            if name == "url-query" and value.startswith("+"):
                continue
            if "@" in value and "=" not in value:
                return True
            if name == "data-urlencode":
                data = True
        elif name in _DATA:
            data = True
            if name != "data-raw" and value.startswith("@"):
                return True
    return False


def _wget_sends(args: list[str]) -> bool:
    words = iter(args)
    for word in words:
        if word == "--":
            break
        option, equals, value = word.partition("=")
        if option in {
            "--post-data",
            "--post-file",
            "--body-data",
            "--body-file",
        }:
            return True
        if option == "--method":
            method = value if equals else next(words, "")
            if _method_needs_approval(method):
                return True
    return False


_HTTPIE_VALUE_OPTIONS = frozenset(
    """
    --auth --auth-type --boundary --cert --cert-key --cert-key-pass --ciphers
    --default-scheme --format-options --history-print --max-headers
    --max-redirects --output --pretty --print --proxy --raw --response-charset
    --response-mime --session --session-read-only --ssl --ssl-ciphers --style
    --timeout --verify
    """.split(),
)


def _httpie_sends(args: list[str], stdin: bool) -> bool:
    options: set[str] = set()
    positional: list[str] = []
    words = iter(args)
    for word in words:
        if word == "--":
            positional.extend(words)
            break
        if word.startswith("--"):
            option, equals, _ = word.partition("=")
            options.add(option)
            if not equals and option in _HTTPIE_VALUE_OPTIONS:
                next(words, None)
        elif word.startswith("-") and word != "-":
            for index, flag in enumerate(word[1:], start=2):
                options.add("-" + flag)
                if flag in "aAopPs":
                    if index == len(word):
                        next(words, None)
                    break
        else:
            positional.append(word)
    if "--offline" in options and "--no-offline" not in options:
        return False
    ignore_stdin = options.intersection({"-I", "--ignore-stdin"})
    if stdin and (not ignore_stdin or "--no-ignore-stdin" in options):
        return True
    if options.intersection({"-f", "--form", "--multipart", "--raw"}):
        return True
    # HTTPie accepts an alphabetic METHOD before the URL.
    fields = positional[1:]
    if len(positional) >= 2 and re.fullmatch("[A-Za-z]+", positional[0]):
        if _method_needs_approval(positional[0].upper()):
            return True
        fields = positional[2:]
    for item in fields:
        # The first unescaped separator determines the request item type.
        # Brackets in the key describe nested objects and arrays.
        separator = re.match(r"^(?:\\.|[^\\:=@;])*(==@|==|:=|:@|[:=@;])", item)
        if separator and separator[1] not in {":", ";", "=="}:
            return True
    return False


def _word(node: Node, windows: bool) -> str:
    raw = (node.text or b"").decode("utf-8")
    if windows:
        # Native cmd/PowerShell paths use literal backslashes. POSIX shlex
        # would discard these from an unquoted executable name.
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            return raw[1:-1]
        return raw
    try:
        parts = shlex.split(raw)
    except ValueError:
        return raw
    return parts[0] if len(parts) == 1 else raw


def _redirected_stdin(node: Node) -> bool | None:
    """Return the last redirection of fd 0, or None to inherit stdin."""
    for redirect in reversed(node.children_by_field_name("redirect")):
        descriptor = redirect.child_by_field_name("descriptor")
        if descriptor is not None and descriptor.text != b"0":
            continue
        operators = [
            child.type for child in redirect.children if not child.is_named
        ]
        if "<&-" in operators:
            return False
        if any(operator.startswith("<") for operator in operators):
            return True
    return None


def _has_stdin(command: Node, inherited: bool) -> bool:
    node: Node | None = command
    while node is not None:
        redirected = _redirected_stdin(node)
        if redirected is not None:
            return redirected
        parent = node.parent
        if parent is not None and parent.type == "pipeline":
            # Bash grammar can attach the last stage's trailing redirects
            # to a redirected_statement wrapping the entire pipeline.
            wrapper = parent.parent
            if wrapper is not None and wrapper.type == "redirected_statement":
                if node == parent.named_children[-1]:
                    redirected = _redirected_stdin(wrapper)
                    if redirected is not None:
                        return redirected
                wrapper = wrapper.parent
            if node != parent.named_children[0]:
                return True
            node = wrapper
        else:
            node = parent
    return inherited


def _trailing_args(command: Node) -> list[Node]:
    parent = command.parent
    if parent is not None and parent.type == "pipeline":
        if command != parent.named_children[-1]:
            return []
        parent = parent.parent
    if parent is None or parent.type != "redirected_statement":
        return []
    # The grammar groups words following a redirect with its destination.
    return [
        word
        for redirect in parent.children_by_field_name("redirect")
        for word in redirect.children_by_field_name("destination")[1:]
    ]


_WRAPPER_VALUES: dict[str, set[str]] = {
    "command": set(),
    "env": {"-u", "--unset", "-C", "--chdir"},
    "exec": {"-a"},
    "sudo": {"-u", "--user", "-g", "--group", "-D", "--chdir"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
    "xargs": {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"},
}


def _basename(word: str, windows: bool) -> str:
    return (
        ntpath.basename(word).lower() if windows else word.rsplit("/", 1)[-1]
    )


def _command_index(args: list[str], windows: bool) -> int:
    """Locate the executable through common shell command wrappers."""
    index = 0
    while index < len(args):
        wrapper = _basename(args[index], windows)
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


def _shell_script_index(args: list[str]) -> int | None:
    """Locate the command string selected by a shell's short -c option."""
    command_string = False
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--":
            index += 1
            break
        if flag in {"--rcfile", "--init-file"}:
            index += 2
            continue
        if flag.startswith("--"):
            index += 1
            continue
        if len(flag) < 2 or flag[0] not in "-+":
            break
        if flag.startswith("-") and "c" in flag[1:]:
            command_string = True
        # -o / -O consume the following option name, including in -co.
        index += 2 if "o" in flag[1:] or "O" in flag[1:] else 1
    return index if command_string and index < len(args) else None


def _matching_command(
    pattern: re.Pattern[str],
    command: Node,
    value: str,
    source: bytes,
    depth: int,
    inherited_stdin: bool,
    windows: bool,
) -> re.Match[str] | None:
    name = command.child_by_field_name("name")
    if name is None:
        return None
    nodes = [
        name,
        *command.children_by_field_name("argument"),
        *_trailing_args(command),
    ]
    args = [_word(node, windows) for node in nodes]
    index = _command_index(args, windows)
    if index >= len(args):
        return None
    executable = _basename(args[index], windows).lower().removesuffix(".exe")
    rest = args[index + 1 :]
    node = nodes[index]
    if executable in {"bash", "sh", "zsh", "dash", "ksh"}:
        position = _shell_script_index(rest)
        if position is None:
            return None
        if depth < 8 and not search_rule_pattern(
            pattern,
            rest[position],
            depth + 1,
            _has_stdin(command, inherited_stdin),
            windows=False,
        ):
            return None
        node = nodes[index + 1 + position]
    elif windows and executable in {"cmd", "powershell", "pwsh"}:
        # Native shells accept the rest of the command line as the script.
        switches = {"/c", "/k"} if executable == "cmd" else {"-command", "-c"}
        for position, flag in enumerate(rest[:-1]):
            if flag.lower() not in switches:
                continue
            script_node = nodes[index + position + 2]
            start = len(source[: script_node.start_byte].decode("utf-8"))
            end = len(source[: nodes[-1].end_byte].decode("utf-8"))
            script = value[start:end] if position + 2 < len(rest) else rest[-1]
            if depth < 8 and not search_rule_pattern(
                pattern,
                script,
                depth + 1,
                _has_stdin(command, inherited_stdin),
                windows=True,
            ):
                return None
            return pattern.search(value, start, end)
        return None
    elif not pattern.fullmatch(executable):
        return None
    elif executable == "curl" and not _curl_sends(rest):
        return None
    elif executable == "wget" and not _wget_sends(rest):
        return None
    elif executable in {"http", "https"} and not _httpie_sends(
        rest,
        _has_stdin(command, inherited_stdin),
    ):
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
    inherited_stdin: bool = False,
    *,
    windows: bool | None = None,
) -> re.Match[str] | None:
    """Resolve outbound executable captures in their shell command context."""
    match = pattern.search(value)
    if not match or "outbound_executable" not in pattern.groupindex:
        return match
    source = value.encode("utf-8")
    if windows is None:
        windows = _WINDOWS
    # A leading PowerShell invocation operator is outside the Bash grammar.
    # Preserve byte offsets for the match returned against the original text.
    syntax = (
        re.sub(rb"^([ \t]*)&(?=[ \t\"'])", rb"\1 ", source)
        if windows
        else source
    )
    root = Parser(_BASH).parse(syntax).root_node
    if root.has_error:
        return match
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type == "command":
            hit = _matching_command(
                pattern,
                node,
                value,
                source,
                depth,
                inherited_stdin,
                windows,
            )
            if hit:
                return hit
        pending.extend(reversed(node.named_children))
    return None
