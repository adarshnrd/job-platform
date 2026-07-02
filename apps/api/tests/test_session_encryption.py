"""
Tests for the session encryption service.
Covers: encrypt/decrypt, JSON round-trip, key rotation, error handling.

Imports modules directly to avoid __init__.py pulling in heavy deps (loguru, supabase).
"""
import sys
import os
import pytest
from unittest.mock import MagicMock

mock_config = MagicMock()
mock_config.settings = MagicMock(
    SESSION_ENCRYPTION_KEY="test-key",
    SESSION_ENCRYPTION_KEY_VERSION=1,
    PLAYWRIGHT_HEADLESS=True,
)
sys.modules.setdefault("loguru", MagicMock())
sys.modules.setdefault("database", MagicMock())
sys.modules.setdefault("config", mock_config)
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.sessions.encryption import EncryptionService


class TestEncryptionService:
    """Tests that run without Supabase or external deps — pure crypto logic."""

    def _make(self, master_key="test-master-key-123", version=1, previous_keys=None):
        return EncryptionService(master_key, version=version, previous_keys=previous_keys)

    def test_encrypt_decrypt_round_trip(self):
        svc = self._make()
        plaintext = "hello world session cookies"
        ciphertext, version = svc.encrypt(plaintext)

        assert version == 1
        assert ciphertext != plaintext
        assert len(ciphertext) > 0

        decrypted = svc.decrypt(ciphertext, version)
        assert decrypted == plaintext

    def test_encrypt_decrypt_json(self):
        svc = self._make()
        cookies = [
            {"name": "li_at", "value": "AQ...", "domain": ".linkedin.com", "path": "/"},
            {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com", "path": "/"},
        ]

        ciphertext, version = svc.encrypt_json(cookies)
        assert isinstance(ciphertext, str)
        assert version == 1

        decrypted = svc.decrypt_json(ciphertext, version)
        assert decrypted == cookies
        assert len(decrypted) == 2
        assert decrypted[0]["name"] == "li_at"

    def test_different_keys_cannot_decrypt(self):
        svc1 = self._make(master_key="key-one")
        svc2 = self._make(master_key="key-two")

        ciphertext, version = svc1.encrypt("secret")
        with pytest.raises(Exception):
            svc2.decrypt(ciphertext, version)

    def test_key_rotation(self):
        old_key = "old-master-key"
        new_key = "new-master-key"

        old_svc = self._make(master_key=old_key, version=1)
        ciphertext_v1, v1 = old_svc.encrypt("my session data")
        assert v1 == 1

        new_svc = self._make(master_key=new_key, version=2, previous_keys=[old_key])

        decrypted = new_svc.decrypt(ciphertext_v1, version=1)
        assert decrypted == "my session data"

        ciphertext_v2, v2 = new_svc.rotate(ciphertext_v1, old_version=1)
        assert v2 == 2

        decrypted_v2 = new_svc.decrypt(ciphertext_v2, version=2)
        assert decrypted_v2 == "my session data"

    def test_encrypt_empty_string(self):
        svc = self._make()
        ciphertext, version = svc.encrypt("")
        decrypted = svc.decrypt(ciphertext, version)
        assert decrypted == ""

    def test_encrypt_json_complex_structure(self):
        svc = self._make()
        data = {
            "user_agent": "Mozilla/5.0",
            "viewport": {"width": 1920, "height": 1080},
            "nested": [1, 2, {"a": True}],
        }
        ct, v = svc.encrypt_json(data)
        result = svc.decrypt_json(ct, v)
        assert result == data

    def test_generate_key_returns_valid_string(self):
        key = EncryptionService.generate_key()
        assert isinstance(key, str)
        assert len(key) > 20

    def test_ciphertext_is_different_each_time(self):
        svc = self._make()
        ct1, _ = svc.encrypt("same input")
        ct2, _ = svc.encrypt("same input")
        assert ct1 != ct2

    def test_unicode_content(self):
        svc = self._make()
        text = "日本語テスト 🎯 café résumé"
        ct, v = svc.encrypt(text)
        assert svc.decrypt(ct, v) == text

    def test_large_cookie_payload(self):
        svc = self._make()
        cookies = [{"name": f"cookie_{i}", "value": "x" * 500, "domain": ".example.com"} for i in range(50)]
        ct, v = svc.encrypt_json(cookies)
        result = svc.decrypt_json(ct, v)
        assert len(result) == 50
        assert result[49]["name"] == "cookie_49"
