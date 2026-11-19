"""Encrypted, expiring setup envelopes. A code is a secret, never a URL query."""
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import re
import time
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_SETUP = 32768
AAD = b'airlock-setup-v1'


def origin(value, allow_loopback=False):
    if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
        raise ValueError('Invalid setup origin.')
    u = urlsplit(value)
    if (not u.hostname or u.username or u.password or u.query or u.fragment
            or u.path not in ('', '/') or len(value) > 500):
        raise ValueError('Invalid setup origin.')
    if allow_loopback and u.scheme == 'http' and u.hostname == '127.0.0.1':
        return value.rstrip('/')
    if u.scheme != 'https' or u.port not in (None, 443):
        raise ValueError('Setup requires HTTPS on port 443.')
    try:
        ipaddress.ip_address(u.hostname)
    except ValueError:
        if re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', u.hostname) and not u.hostname.endswith(('.local', '.localhost')):
            return value.rstrip('/')
    raise ValueError('Use a public HTTPS connector hostname.')


def encode(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def proof(secret):
    return hmac.new(secret, b'airlock-setup-download-v1', hashlib.sha256).hexdigest()


def parse_code(code, allow_loopback=False):
    if len(code) > 1500:
        raise ValueError('Invalid setup code.')
    version, address, key = code.strip().split('.')
    endpoint = origin(decode(address).decode(), allow_loopback)
    secret = decode(key)
    if version != 'airlock1' or len(secret) != 32:
        raise ValueError('Invalid setup code.')
    return endpoint, secret


def prepare(endpoint, google, invitation, ttl=86400, *, allow_loopback=False):
    endpoint = origin(endpoint, allow_loopback)
    if not 60 <= ttl <= 86400:
        raise ValueError('Setup lifetime must be between one minute and 24 hours.')
    expires = int(time.time()) + ttl
    payload = {'version': 1, 'endpoint': endpoint, 'expires_at': expires,
               'google_client': google, 'invitation': invitation}
    if len(json.dumps(payload).encode()) > MAX_SETUP // 2:
        raise ValueError('Setup configuration is too large.')
    if invitation['endpoint'].rstrip('/') != endpoint:
        raise ValueError('Invitation must belong to the setup connector.')
    secret, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    cipher = AESGCM(secret).encrypt(nonce, json.dumps(payload).encode(), AAD)
    envelope = {'id': secrets.token_hex(16), 'expires_at': expires,
                'token_hash': hashlib.sha256(proof(secret).encode()).hexdigest(),
                'ciphertext': encode(nonce + cipher)}
    return 'airlock1.' + encode(endpoint.encode()) + '.' + encode(secret), envelope


def decrypt(secret, ciphertext, endpoint):
    raw = decode(ciphertext)
    payload = json.loads(AESGCM(secret).decrypt(raw[:12], raw[12:], AAD))
    if (set(payload) != {'version', 'endpoint', 'expires_at', 'google_client', 'invitation'}
            or payload['version'] != 1 or payload['endpoint'] != endpoint
            or not time.time() < payload['expires_at'] <= time.time() + 86401):
        raise ValueError('Expired or invalid setup package.')
    return payload
