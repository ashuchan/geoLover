"""Simulated KMS envelope encryption for OAuth tokens."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EncryptedBlob:
    ciphertext: bytes    # XOR with DEK (simulated AES-GCM)
    wrapped_dek: bytes   # DEK XOR'd with KMS master key (simulated)
    kms_key_version: str


class TokenVault:
    _KMS_MASTER_KEY = b"citedby-kms-master-key-phase5-ok"  # 32 bytes; in prod, fetched from KMS
    _dek_cache: dict = {}
    _CACHE_TTL_S = 300  # 5 minutes
    _CACHE_MAX = 100

    def _wrap_dek(self, dek: bytes) -> tuple[bytes, str]:
        # Simulate KMS Encrypt: XOR each byte with cycling master key
        wrapped = bytes(b ^ self._KMS_MASTER_KEY[i % 32] for i, b in enumerate(dek))
        version = "v1"
        return wrapped, version

    def _unwrap_dek(self, wrapped_dek: bytes, kms_key_version: str) -> bytes:
        import time
        # Check cache first
        key = wrapped_dek.hex()
        if key in self.__class__._dek_cache:
            dek, exp = self.__class__._dek_cache[key]
            if time.time() < exp:
                return dek
        # Simulate KMS Decrypt: reverse the XOR
        dek = bytes(b ^ self._KMS_MASTER_KEY[i % 32] for i, b in enumerate(wrapped_dek))
        # Cache it
        if len(self.__class__._dek_cache) >= self._CACHE_MAX:
            oldest = next(iter(self.__class__._dek_cache))
            del self.__class__._dek_cache[oldest]
        self.__class__._dek_cache[key] = (dek, time.time() + self._CACHE_TTL_S)
        return dek

    def _encrypt(self, plaintext: str, dek: bytes) -> bytes:
        data = plaintext.encode()
        # Simulate AES-GCM: XOR with cycling DEK
        return bytes(b ^ dek[i % 32] for i, b in enumerate(data))

    def _decrypt(self, ciphertext: bytes, dek: bytes) -> str:
        decrypted = bytes(b ^ dek[i % 32] for i, b in enumerate(ciphertext))
        return decrypted.decode()

    def encrypt_token(self, plaintext: str) -> EncryptedBlob:
        dek = os.urandom(32)
        ciphertext = self._encrypt(plaintext, dek)
        wrapped_dek, version = self._wrap_dek(dek)
        return EncryptedBlob(ciphertext=ciphertext, wrapped_dek=wrapped_dek, kms_key_version=version)

    def decrypt_token(self, blob: EncryptedBlob) -> str:
        dek = self._unwrap_dek(blob.wrapped_dek, blob.kms_key_version)
        return self._decrypt(blob.ciphertext, dek)
