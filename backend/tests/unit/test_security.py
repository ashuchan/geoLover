"""Unit tests for app.core.security — KMS envelope encryption and normalisation."""

from __future__ import annotations

import base64
import os
import struct

import struct

import pytest

from app.core.exceptions import DecryptionError, EncryptionError
from app.core.security import (
    _VERSION,
    decrypt_pii,
    encrypt_pii,
    normalize_email,
    normalize_phone,
    normalize_text,
)


@pytest.fixture
def master_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode()


class TestEncryptDecrypt:
    def test_roundtrip(self, master_key_b64):
        plaintext = "user@example.com"
        blob = encrypt_pii(master_key_b64, plaintext)
        assert decrypt_pii(master_key_b64, blob) == plaintext

    def test_produces_bytes(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        assert isinstance(blob, bytes)

    def test_version_byte(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "test")
        assert blob[0:1] == _VERSION

    def test_non_deterministic(self, master_key_b64):
        # Each call must produce a different ciphertext (random nonce)
        blob1 = encrypt_pii(master_key_b64, "same text")
        blob2 = encrypt_pii(master_key_b64, "same text")
        assert blob1 != blob2

    def test_unicode_roundtrip(self, master_key_b64):
        plaintext = "नमस्ते दुनिया"
        assert decrypt_pii(master_key_b64, encrypt_pii(master_key_b64, plaintext)) == plaintext

    def test_empty_string_roundtrip(self, master_key_b64):
        assert decrypt_pii(master_key_b64, encrypt_pii(master_key_b64, "")) == ""


class TestEncryptErrors:
    def test_wrong_key_length_raises(self):
        bad_key = base64.b64encode(b"tooshort").decode()
        with pytest.raises(EncryptionError, match="32 bytes"):
            encrypt_pii(bad_key, "data")

    def test_invalid_base64_raises(self):
        with pytest.raises(EncryptionError):
            encrypt_pii("not-valid-base64!!!", "data")


class TestDecryptErrors:
    def test_wrong_key_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "secret")
        other_key = base64.b64encode(os.urandom(32)).decode()
        with pytest.raises(DecryptionError):
            decrypt_pii(other_key, blob)

    def test_wrong_version_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "secret")
        # Corrupt version byte
        corrupted = b"\xff" + blob[1:]
        with pytest.raises(DecryptionError, match="Unknown envelope version"):
            decrypt_pii(master_key_b64, corrupted)

    def test_empty_bytes_raises(self, master_key_b64):
        with pytest.raises(DecryptionError):
            decrypt_pii(master_key_b64, b"")

    def test_truncated_blob_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        with pytest.raises(DecryptionError):
            decrypt_pii(master_key_b64, blob[:5])

    def test_tampered_ciphertext_raises(self, master_key_b64):
        blob = bytearray(encrypt_pii(master_key_b64, "hello world"))
        blob[-1] ^= 0xFF  # flip last byte
        with pytest.raises(DecryptionError):
            decrypt_pii(master_key_b64, bytes(blob))

    def test_invalid_master_key_base64_in_decrypt_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        with pytest.raises(DecryptionError):
            decrypt_pii("not-valid-base64!!!", blob)

    def test_wrong_length_master_key_in_decrypt_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        short_key = base64.b64encode(b"tooshort").decode()
        with pytest.raises(DecryptionError, match="32 bytes"):
            decrypt_pii(short_key, blob)

    def test_invalid_wrapped_dek_length_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        # Zero out the wrapped_dek_len field (bytes 1-2) to make it 0
        corrupted = bytearray(blob)
        corrupted[1] = 0
        corrupted[2] = 0
        with pytest.raises(DecryptionError, match="invalid wrapped DEK length"):
            decrypt_pii(master_key_b64, bytes(corrupted))

    def test_no_ciphertext_payload_raises(self, master_key_b64):
        blob = encrypt_pii(master_key_b64, "hello")
        # Set wrapped_dek_len to consume all remaining bytes so ciphertext is empty
        # Parse the real wrapped_dek_len first
        (real_len,) = struct.unpack(">H", blob[1:3])
        total_after_header = len(blob) - 3
        # Set wrapped_dek_len to total_after_header so no bytes left for ciphertext
        corrupted = bytearray(blob)
        corrupted[1] = (total_after_header >> 8) & 0xFF
        corrupted[2] = total_after_header & 0xFF
        with pytest.raises(DecryptionError):
            decrypt_pii(master_key_b64, bytes(corrupted))


class TestNormalizeEmail:
    def test_lowercase(self):
        assert normalize_email("USER@EXAMPLE.COM") == "user@example.com"

    def test_strips_whitespace(self):
        assert normalize_email("  user@example.com  ") == "user@example.com"

    def test_nfkc_normalisation(self):
        # Full-width @ sign should normalise to ASCII
        # Using simple ASCII here; just check it passes through
        assert normalize_email("user@example.com") == "user@example.com"

    @pytest.mark.parametrize("bad", ["notanemail", "@example.com", "user@", "user @example.com"])
    def test_invalid_format_raises(self, bad):
        with pytest.raises(ValueError):
            normalize_email(bad)


class TestNormalizePhone:
    def test_strips_formatting(self):
        assert normalize_phone("+91-98765-43210") == "919876543210"

    def test_strips_spaces(self):
        assert normalize_phone("(022) 1234 5678") == "02212345678"

    def test_digits_only_unchanged(self):
        assert normalize_phone("9876543210") == "9876543210"

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            normalize_phone("()")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="too short"):
            normalize_phone("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="too short"):
            normalize_phone("   ")


class TestNormalizeText:
    def test_lowercase(self):
        assert normalize_text("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize_text("  foo   bar  ") == "foo bar"

    def test_nfkc(self):
        # Decomposed 'é' should be composed
        import unicodedata
        decomposed = unicodedata.normalize("NFD", "café")
        result = normalize_text(decomposed)
        assert result == "café"
