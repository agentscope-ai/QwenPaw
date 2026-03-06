# -*- coding: utf-8 -*-
from copaw.app.channels.wecom_common import (
    build_encrypted_xml_response,
    build_text_reply_xml,
    compute_msg_signature,
    decrypt_encrypted_message,
    encrypt_plaintext_message,
    parse_xml_to_dict,
    verify_msg_signature,
)


def test_signature_compute_and_verify() -> None:
    token = "token123"
    timestamp = "1700000000"
    nonce = "nonce123"
    encrypt = "ciphertext"

    sig = compute_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
    )

    assert verify_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
        signature=sig,
    )
    assert not verify_msg_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypt=encrypt,
        signature="bad-signature",
    )


def test_encrypt_decrypt_roundtrip() -> None:
    key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    msg = "hello wecom"

    encrypted = encrypt_plaintext_message(
        encoding_aes_key=key,
        plaintext=msg,
        receive_id="corp-123",
    )
    decrypted = decrypt_encrypted_message(
        encoding_aes_key=key,
        encrypt=encrypted,
        receive_id="corp-123",
    )

    assert decrypted == msg


def test_build_encrypted_xml_response_contains_required_fields() -> None:
    key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    token = "token123"
    nonce = "nonce456"
    timestamp = "1700000001"

    plaintext = build_text_reply_xml(
        to_user="from_user",
        from_user="to_user",
        content="ok",
        create_time=1700000001,
    )
    xml = build_encrypted_xml_response(
        token=token,
        encoding_aes_key=key,
        plaintext_xml=plaintext,
        nonce=nonce,
        timestamp=timestamp,
        receive_id="corp-123",
    )
    payload = parse_xml_to_dict(xml)

    assert payload["Encrypt"]
    assert payload["MsgSignature"]
    assert payload["TimeStamp"] == timestamp
    assert payload["Nonce"] == nonce
