import hashlib
import hmac
import secrets
import time


def sign(secret, value):
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_session(secret):
    value = f"{secrets.token_hex(24)}.{int(time.time())}"
    return f"{value}.{sign(secret, value)}"


def valid_session(secret, cookie):
    try:
        nonce, issued, signature = cookie.split(".")
        age = time.time() - int(issued)
        return len(nonce) == 48 and 0 <= age <= 86400 and hmac.compare_digest(signature, sign(secret, f"{nonce}.{issued}"))
    except (ValueError, AttributeError):
        return False


def csrf(secret, cookie):
    return sign(secret, "csrf:" + cookie)
