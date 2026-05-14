"""KMS-style envelope encryption for PII (email, phone).

Design:
  - A 32-byte master key (AES-256) is held in application config (in prod: injected
    via Cloud Run secret manager, never persisted to disk).
  - Per-record Data Encryption Keys (DEK) are generated with os.urandom(32).
  - DEK is wrapped (encrypted) with the master key using AES-GCM.
  - The plaintext is encrypted with the DEK using AES-GCM.
  - Wire format stored in Postgres BYTEA:
      version(1) | wrapped_dek_len(2, big-endian) | wrapped_dek | nonce(12) | ciphertext+tag

  Normalisation helpers produce a consistent lowercase representation for indexed
  equality look-ups (email_normalized, phone_normalized) without revealing the
  plaintext in the clear — callers are responsible for hashing if needed.
"""

from __future__ import annotations

import base64
import os
import struct
import unicodedata
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.exceptions import DecryptionError, EncryptionError

_VERSION = b"\x01"
_NONCE_BYTES = 12
_DEK_BYTES = 32
_GCM_TAG_BYTES = 16

# Minimum valid blob: version(1) + wrapped_dek_len(2) + min_wrapped_dek(nonce+dek+tag) + min_ct(nonce+tag)
_MIN_BLOB_LEN = 1 + 2 + (_NONCE_BYTES + _DEK_BYTES + _GCM_TAG_BYTES) + (_NONCE_BYTES + _GCM_TAG_BYTES)


# ── low-level AES-GCM helpers ─────────────────────────────────────────────────


def _aesgcm_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce + ct


def _aesgcm_decrypt(key: bytes, payload: bytes, aad: bytes | None = None) -> bytes:
    nonce, ct = payload[:_NONCE_BYTES], payload[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ct, aad)
    except Exception as exc:
        raise DecryptionError("AES-GCM decryption failed") from exc


# ── public API ────────────────────────────────────────────────────────────────


def encrypt_pii(master_key_b64: str, plaintext: str) -> bytes:
    """Encrypt *plaintext* using envelope encryption.

    Returns raw bytes suitable for storage in a Postgres BYTEA column.
    Raises EncryptionError on failure.
    """
    try:
        master_key = base64.b64decode(master_key_b64)
        if len(master_key) != _DEK_BYTES:
            raise EncryptionError(f"Master key must be {_DEK_BYTES} bytes (base64-encoded)")

        dek = os.urandom(_DEK_BYTES)
        wrapped_dek = _aesgcm_encrypt(master_key, dek)
        ciphertext = _aesgcm_encrypt(dek, plaintext.encode())

        wrapped_dek_len = struct.pack(">H", len(wrapped_dek))
        return _VERSION + wrapped_dek_len + wrapped_dek + ciphertext
    except EncryptionError:
        raise
    except Exception as exc:
        raise EncryptionError("Encryption failed") from exc


def decrypt_pii(master_key_b64: str, cipherblob: bytes) -> str:
    """Decrypt a blob produced by :func:`encrypt_pii`.

    Raises DecryptionError on failure (bad key, truncated data, tampered ciphertext).
    """
    try:
        if not cipherblob or cipherblob[0:1] != _VERSION:
            raise DecryptionError("Unknown envelope version")

        if len(cipherblob) < _MIN_BLOB_LEN:
            raise DecryptionError("Cipherblob is too short to be valid")

        master_key = base64.b64decode(master_key_b64)
        if len(master_key) != _DEK_BYTES:
            raise DecryptionError(f"Master key must be {_DEK_BYTES} bytes (base64-encoded)")

        offset = 1
        (wrapped_dek_len,) = struct.unpack(">H", cipherblob[offset : offset + 2])
        offset += 2

        if wrapped_dek_len == 0 or offset + wrapped_dek_len > len(cipherblob):
            raise DecryptionError("Cipherblob has invalid wrapped DEK length")

        wrapped_dek = cipherblob[offset : offset + wrapped_dek_len]
        offset += wrapped_dek_len
        ciphertext = cipherblob[offset:]

        if not ciphertext:
            raise DecryptionError("Cipherblob has no ciphertext payload")

        dek = _aesgcm_decrypt(master_key, wrapped_dek)
        plaintext_bytes = _aesgcm_decrypt(dek, ciphertext)
        return plaintext_bytes.decode()
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError("Decryption failed") from exc


# ── normalisation helpers ─────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_STRIP_RE = re.compile(r"[\s\-().+]")
_MIN_PHONE_DIGITS = 7


def normalize_email(email: str) -> str:
    """Return lowercased, stripped email.  Raises ValueError for obviously invalid format."""
    normalised = unicodedata.normalize("NFKC", email).strip().lower()
    if not _EMAIL_RE.match(normalised):
        raise ValueError(f"Invalid email format: {email!r}")
    return normalised


def normalize_phone(phone: str) -> str:
    """Strip formatting characters and return digits-only string.

    Raises ValueError if fewer than 7 digits remain after normalisation
    (the minimum meaningful E.164 length).
    """
    digits = _PHONE_STRIP_RE.sub("", phone)
    if len(digits) < _MIN_PHONE_DIGITS:
        raise ValueError(f"Phone number too short after normalization: {phone!r}")
    return digits


def normalize_text(text: str) -> str:
    """General text normalisation: NFKC → lowercase → collapse whitespace."""
    normalised = unicodedata.normalize("NFKC", text).lower()
    return " ".join(normalised.split())
