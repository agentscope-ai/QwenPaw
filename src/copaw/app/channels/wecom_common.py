# -*- coding: utf-8 -*-
"""Shared WeCom protocol helpers (signature, crypto, XML)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict
from urllib.parse import parse_qs, urlparse

from Crypto.Cipher import AES


WECOM_PKCS7_BLOCK_SIZE = 32


@dataclass
class WeComCallbackQuery:
    """Normalized callback query params."""

    timestamp: str
    nonce: str
    signature: str
    echostr: str

    @classmethod
    def from_url(cls, url: str) -> "WeComCallbackQuery":
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        def _get(*keys: str) -> str:
            for k in keys:
                arr = params.get(k)
                if arr and arr[0]:
                    return str(arr[0])
            return ""

        return cls(
            timestamp=_get("timestamp", "timeStamp"),
            nonce=_get("nonce"),
            signature=_get("msg_signature", "msgsignature", "signature"),
            echostr=_get("echostr"),
        )


def _decode_encoding_aes_key(encoding_aes_key: str) -> bytes:
    key = (encoding_aes_key or "").strip()
    if not key:
        raise ValueError("encoding_aes_key is empty")
    key_padded = key if key.endswith("=") else f"{key}="
    raw = base64.b64decode(key_padded)
    if len(raw) != 32:
        raise ValueError(
            "invalid encoding_aes_key: expected 32-byte key "
            "after base64 decode",
        )
    return raw


def _pkcs7_pad(raw: bytes, block_size: int = WECOM_PKCS7_BLOCK_SIZE) -> bytes:
    mod = len(raw) % block_size
    pad_len = block_size if mod == 0 else block_size - mod
    return raw + bytes([pad_len] * pad_len)


def _pkcs7_unpad(
    raw: bytes,
    block_size: int = WECOM_PKCS7_BLOCK_SIZE,
) -> bytes:
    if not raw:
        raise ValueError("invalid pkcs7 payload")
    pad_len = raw[-1]
    if pad_len < 1 or pad_len > block_size or pad_len > len(raw):
        raise ValueError("invalid pkcs7 padding")
    if raw[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("invalid pkcs7 padding")
    return raw[:-pad_len]


def compute_msg_signature(
    *,
    token: str,
    timestamp: str,
    nonce: str,
    encrypt: str,
) -> str:
    parts = [
        str(token or ""),
        str(timestamp or ""),
        str(nonce or ""),
        str(encrypt or ""),
    ]
    parts.sort()
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def verify_msg_signature(
    *,
    token: str,
    timestamp: str,
    nonce: str,
    encrypt: str,
    signature: str,
) -> bool:
    expected = compute_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
    )
    return expected == (signature or "")


def decrypt_encrypted_message(
    *,
    encoding_aes_key: str,
    encrypt: str,
    receive_id: str = "",
) -> str:
    aes_key = _decode_encoding_aes_key(encoding_aes_key)
    iv = aes_key[:16]
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_padded = cipher.decrypt(base64.b64decode(encrypt))
    decrypted = _pkcs7_unpad(decrypted_padded)

    if len(decrypted) < 20:
        raise ValueError("invalid decrypted payload")

    msg_len = int.from_bytes(decrypted[16:20], "big")
    msg_start = 20
    msg_end = msg_start + msg_len
    if msg_end > len(decrypted):
        raise ValueError("invalid decrypted message length")

    msg = decrypted[msg_start:msg_end].decode("utf-8")

    expected_receive_id = (receive_id or "").strip()
    if expected_receive_id:
        trailing = decrypted[msg_end:].decode("utf-8")
        if trailing != expected_receive_id:
            raise ValueError("receive_id mismatch")

    return msg


def encrypt_plaintext_message(
    *,
    encoding_aes_key: str,
    plaintext: str,
    receive_id: str = "",
) -> str:
    aes_key = _decode_encoding_aes_key(encoding_aes_key)
    iv = aes_key[:16]
    random_16 = os.urandom(16)
    msg = (plaintext or "").encode("utf-8")
    msg_len = len(msg).to_bytes(4, "big")
    rid = (receive_id or "").encode("utf-8")
    raw = random_16 + msg_len + msg + rid
    raw_padded = _pkcs7_pad(raw)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(raw_padded)
    return base64.b64encode(encrypted).decode("utf-8")


def parse_xml_to_dict(xml_text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not (xml_text or "").strip():
        return out
    root = ET.fromstring(xml_text)
    for child in root:
        if child.tag:
            if list(child):
                out[str(child.tag)] = ET.tostring(
                    child,
                    encoding="unicode",
                )
            else:
                out[str(child.tag)] = (child.text or "").strip()
    return out


def _xml_cdata(value: str) -> str:
    # Preserve raw data even when it contains "]]>".
    safe = (value or "").replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def build_text_reply_xml(
    *,
    to_user: str,
    from_user: str,
    content: str,
    create_time: int | None = None,
) -> str:
    ts = int(create_time or time.time())
    return (
        "<xml>"
        f"<ToUserName>{_xml_cdata(to_user)}</ToUserName>"
        f"<FromUserName>{_xml_cdata(from_user)}</FromUserName>"
        f"<CreateTime>{ts}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content>{_xml_cdata(content)}</Content>"
        "</xml>"
    )


def build_encrypted_xml_response(
    *,
    token: str,
    encoding_aes_key: str,
    plaintext_xml: str,
    nonce: str,
    timestamp: str,
    receive_id: str = "",
) -> str:
    encrypt = encrypt_plaintext_message(
        encoding_aes_key=encoding_aes_key,
        plaintext=plaintext_xml,
        receive_id=receive_id,
    )
    sig = compute_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
    )
    return (
        "<xml>"
        f"<Encrypt>{_xml_cdata(encrypt)}</Encrypt>"
        f"<MsgSignature>{_xml_cdata(sig)}</MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce>{_xml_cdata(nonce)}</Nonce>"
        "</xml>"
    )


def build_encrypted_json_response(
    *,
    token: str,
    encoding_aes_key: str,
    plaintext_json: object,
    nonce: str,
    timestamp: str,
    receive_id: str = "",
) -> dict[str, str]:
    plaintext = json.dumps(
        plaintext_json if plaintext_json is not None else {},
        ensure_ascii=False,
    )
    encrypt = encrypt_plaintext_message(
        encoding_aes_key=encoding_aes_key,
        plaintext=plaintext,
        receive_id=receive_id,
    )
    sig = compute_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
    )
    return {
        "encrypt": encrypt,
        "msgsignature": sig,
        "timestamp": str(timestamp),
        "nonce": nonce,
    }
