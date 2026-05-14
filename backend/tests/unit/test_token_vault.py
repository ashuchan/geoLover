"""Unit tests for TokenVault KMS envelope encryption."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.modules.publishing.token_vault import EncryptedBlob, TokenVault


class TestEncryptedBlob:
    def test_dataclass_fields(self):
        blob = EncryptedBlob(
            ciphertext=b"cipher",
            wrapped_dek=b"dek",
            kms_key_version="v1",
        )
        assert blob.ciphertext == b"cipher"
        assert blob.wrapped_dek == b"dek"
        assert blob.kms_key_version == "v1"


class TestTokenVaultEncryptDecrypt:
    def setup_method(self):
        # Clear the class-level cache before each test
        TokenVault._dek_cache.clear()

    def test_encrypt_returns_blob(self):
        vault = TokenVault()
        blob = vault.encrypt_token("access_token_value")
        assert isinstance(blob, EncryptedBlob)
        assert isinstance(blob.ciphertext, bytes)
        assert isinstance(blob.wrapped_dek, bytes)
        assert blob.kms_key_version == "v1"

    def test_decrypt_round_trip(self):
        vault = TokenVault()
        plaintext = "my_secret_token_12345"
        blob = vault.encrypt_token(plaintext)
        recovered = vault.decrypt_token(blob)
        assert recovered == plaintext

    def test_ciphertext_differs_from_plaintext(self):
        vault = TokenVault()
        plaintext = "access_token_abc"
        blob = vault.encrypt_token(plaintext)
        assert blob.ciphertext != plaintext.encode()

    def test_multiple_round_trips(self):
        vault = TokenVault()
        tokens = ["token_1", "token_2_longer_value", "short"]
        for token in tokens:
            blob = vault.encrypt_token(token)
            assert vault.decrypt_token(blob) == token

    def test_different_encryptions_for_same_plaintext(self):
        """Each call uses a fresh DEK so ciphertexts differ."""
        vault = TokenVault()
        plaintext = "same_token"
        blob1 = vault.encrypt_token(plaintext)
        blob2 = vault.encrypt_token(plaintext)
        # Different DEKs → different ciphertexts
        assert blob1.ciphertext != blob2.ciphertext

    def test_dek_cache_used_on_second_decrypt(self):
        vault = TokenVault()
        TokenVault._dek_cache.clear()
        blob = vault.encrypt_token("cache_test_token")

        # First decrypt populates cache
        result1 = vault.decrypt_token(blob)
        cache_key = blob.wrapped_dek.hex()
        assert cache_key in TokenVault._dek_cache

        # Second decrypt should hit cache
        result2 = vault.decrypt_token(blob)
        assert result1 == result2 == "cache_test_token"

    def test_cache_entry_has_expiry(self):
        vault = TokenVault()
        TokenVault._dek_cache.clear()
        blob = vault.encrypt_token("cache_expiry_test")
        vault.decrypt_token(blob)

        cache_key = blob.wrapped_dek.hex()
        _, exp = TokenVault._dek_cache[cache_key]
        assert exp > time.time()
        assert exp <= time.time() + TokenVault._CACHE_TTL_S + 1

    def test_expired_cache_entry_is_replaced(self):
        vault = TokenVault()
        TokenVault._dek_cache.clear()
        blob = vault.encrypt_token("expiry_check")
        cache_key = blob.wrapped_dek.hex()

        # Manually inject an expired entry
        TokenVault._dek_cache[cache_key] = (b"stale_dek", time.time() - 1)

        # Should re-derive correct DEK even though cache is stale
        result = vault.decrypt_token(blob)
        assert result == "expiry_check"

    def test_cache_eviction_when_full(self):
        vault = TokenVault()
        TokenVault._dek_cache.clear()

        # Fill cache to CACHE_MAX
        old_tokens = []
        for i in range(TokenVault._CACHE_MAX):
            b = vault.encrypt_token(f"token_{i}")
            vault.decrypt_token(b)  # populates cache
            old_tokens.append(b)

        assert len(TokenVault._dek_cache) == TokenVault._CACHE_MAX

        # One more should evict oldest
        new_blob = vault.encrypt_token("overflow_token")
        result = vault.decrypt_token(new_blob)
        assert result == "overflow_token"
        assert len(TokenVault._dek_cache) == TokenVault._CACHE_MAX

    def test_wrap_unwrap_dek(self):
        vault = TokenVault()
        import os
        dek = os.urandom(32)
        wrapped, version = vault._wrap_dek(dek)
        assert version == "v1"
        assert wrapped != dek
        recovered = vault._unwrap_dek(wrapped, version)
        assert recovered == dek
