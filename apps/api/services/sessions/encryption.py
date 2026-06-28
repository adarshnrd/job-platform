"""Fernet-based encryption for session cookie storage.

Uses AES-128-CBC + HMAC-SHA256 via the cryptography library's Fernet
implementation. Supports key versioning for rotation.
"""

import json
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from services.sessions.exceptions import EncryptionError


class EncryptionService:
    """Encrypts/decrypts session payloads with versioned key rotation.

    The master key comes from SESSION_ENCRYPTION_KEY env var. It's derived
    into a valid Fernet key via SHA-256 + base64 (so users can use any
    passphrase length, not just 32-byte url-safe base64).
    """

    def __init__(self, master_key: str, version: int = 1, previous_keys: list[str] | None = None):
        if not master_key:
            raise EncryptionError("SESSION_ENCRYPTION_KEY is required")
        self._version = version
        self._fernet = self._make_fernet(master_key)
        self._previous: list[tuple[Fernet, int]] = []
        for i, old_key in enumerate(previous_keys or [], start=1):
            self._previous.append((self._make_fernet(old_key), version - i))

    @staticmethod
    def _make_fernet(key_material: str) -> Fernet:
        derived = hashlib.sha256(key_material.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        return Fernet(fernet_key)

    @staticmethod
    def generate_key() -> str:
        """Generate a random Fernet-compatible key for .env setup."""
        return Fernet.generate_key().decode()

    @property
    def version(self) -> int:
        return self._version

    def encrypt(self, plaintext: str) -> tuple[str, int]:
        """Encrypt plaintext. Returns (ciphertext_b64, key_version)."""
        try:
            token = self._fernet.encrypt(plaintext.encode())
            return token.decode(), self._version
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")

    def decrypt(self, ciphertext: str, version: int | None = None) -> str:
        """Decrypt ciphertext. Tries current key first, then previous versions."""
        ct_bytes = ciphertext.encode()

        if version is None or version == self._version:
            try:
                return self._fernet.decrypt(ct_bytes).decode()
            except InvalidToken:
                pass

        for prev_fernet, prev_version in self._previous:
            if version is not None and version != prev_version:
                continue
            try:
                return prev_fernet.decrypt(ct_bytes).decode()
            except InvalidToken:
                continue

        if version is None:
            try:
                return self._fernet.decrypt(ct_bytes).decode()
            except InvalidToken:
                pass

        raise EncryptionError("Decryption failed: no matching key for ciphertext")

    def rotate(self, ciphertext: str, old_version: int) -> tuple[str, int]:
        """Re-encrypt with current key."""
        plaintext = self.decrypt(ciphertext, old_version)
        return self.encrypt(plaintext)

    def encrypt_json(self, data: dict | list) -> tuple[str, int]:
        """Encrypt a JSON-serializable object."""
        return self.encrypt(json.dumps(data, separators=(",", ":")))

    def decrypt_json(self, ciphertext: str, version: int | None = None) -> dict | list:
        """Decrypt to a JSON object."""
        plaintext = self.decrypt(ciphertext, version)
        try:
            return json.loads(plaintext)
        except json.JSONDecodeError as e:
            raise EncryptionError(f"Decrypted data is not valid JSON: {e}")
