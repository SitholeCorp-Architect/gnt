from functools import lru_cache

from cryptography.fernet import Fernet

from gnt.config import get_settings
from gnt.gitlab.oauth import GitlabNotConfiguredError


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().gitlab_token_encryption_key
    if not key:
        # Same fail-loud-at-call-time discipline as oauth.py's own
        # _require_configured -- GITLAB_TOKEN_ENCRYPTION_KEY is optional
        # (config.py), so this is the guard that keeps an unset key from
        # surfacing as a confusing AttributeError instead of a clear one.
        raise GitlabNotConfiguredError("GITLAB_TOKEN_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode("utf-8"))


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
