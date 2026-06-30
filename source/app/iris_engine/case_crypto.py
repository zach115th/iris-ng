"""AES-256-GCM encryption for portable case export files.

Wire format (.iris-case):
  JSON envelope  {"enc":"aes256gcm","v":1,"salt":"<b64>","nonce":"<b64>","ct":"<b64>"}

Key derivation: PBKDF2-HMAC-SHA256, 260 000 iterations, 32-byte key.
salt  — 16 bytes random per export
nonce — 12 bytes random per export (GCM standard)
"""

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_ITERATIONS = 260_000
_KEY_LEN = 32
_ENC_TAG = 'aes256gcm'
_VERSION = 1


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(password.encode('utf-8'))


def encrypt_case_export(payload: dict, password: str) -> bytes:
    """Encrypt a case-export dict and return the .iris-case envelope as bytes."""
    plaintext = json.dumps(payload, default=str, indent=2).encode('utf-8')
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    envelope = {
        'enc': _ENC_TAG,
        'v': _VERSION,
        'salt': base64.b64encode(salt).decode(),
        'nonce': base64.b64encode(nonce).decode(),
        'ct': base64.b64encode(ciphertext).decode(),
    }
    return json.dumps(envelope).encode('utf-8')


def decrypt_case_export(raw: bytes, password: str) -> dict:
    """Decrypt a .iris-case envelope and return the inner case-export dict.

    Raises ValueError on bad password / tampered data / unrecognised format.
    """
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f'Not a valid .iris-case file: {e}') from e

    if not isinstance(envelope, dict) or envelope.get('enc') != _ENC_TAG:
        raise ValueError('File is not an encrypted iris-case export')

    try:
        salt = base64.b64decode(envelope['salt'])
        nonce = base64.b64decode(envelope['nonce'])
        ciphertext = base64.b64decode(envelope['ct'])
    except (KeyError, Exception) as e:
        raise ValueError(f'Malformed .iris-case envelope: {e}') from e

    key = _derive_key(password, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError('Decryption failed — wrong password or corrupted file')

    try:
        return json.loads(plaintext.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f'Decrypted content is not valid JSON: {e}') from e


def is_encrypted_case_file(raw: bytes) -> bool:
    """Return True if raw bytes look like a .iris-case encrypted envelope.

    Checks for the literal tag in the first 256 bytes rather than parsing the
    full JSON (which is large — the encrypted ciphertext is the bulk of it).
    """
    # The envelope always starts with {"enc":"aes256gcm"...} so the tag string
    # appears in the first ~30 bytes.
    return f'"enc": "{_ENC_TAG}"'.encode() in raw[:256] or f'"enc":"{_ENC_TAG}"'.encode() in raw[:256]
