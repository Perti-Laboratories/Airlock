"""Interactive setup; secrets stay out of arguments, files, URLs and reports."""
import getpass
import json
import sys
import httpx
from airlock_contracts.setup import parse_code, proof, decrypt, MAX_SETUP
from .exchange import Invitation, validate_endpoint
from .google import GoogleCalendar, Keychain


class SetupKeys(Keychain):
    service = 'Airlock.Setup.v1'


def validate_payload(payload, endpoint):
    invite = Invitation.model_validate(payload['invitation'])
    if validate_endpoint(invite.endpoint) != endpoint:
        raise ValueError('Setup invitation origin mismatch.')
    doc = payload['google_client']
    if not isinstance(doc, dict) or set(doc) != {'installed'}:
        raise ValueError('Desktop app configuration required.')
    client = doc['installed']
    if (not isinstance(client, dict) or not isinstance(client.get('client_id'), str)
            or not client['client_id'].endswith('.apps.googleusercontent.com')
            or not isinstance(client.get('client_secret'), str)
            or not 1 <= len(client['client_secret']) <= 500
            or len(client['client_id']) > 500
            or {'access_token','refresh_token','id_token'} & set(client)):
        raise ValueError('Invalid Desktop app configuration.')
    return invite


def retrieve(code, *, transport=None):
    endpoint, secret = parse_code(code)
    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False, transport=transport) as client:
        with client.stream('POST', endpoint+'/v1/setup/redeem', json={},
                           headers={'Authorization':'Bearer '+proof(secret)}) as response:
            if response.status_code != 200:
                raise ValueError('Setup code expired, used, or unavailable. Ask for a fresh code.')
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=4096):
                raw.extend(chunk)
                if len(raw) > MAX_SETUP:
                    raise ValueError('Setup response is too large.')
    payload = decrypt(secret, json.loads(raw)['ciphertext'], endpoint)
    validate_payload(payload, endpoint)
    return payload


def apply(settings, payload, *, google=None, transport=None):
    """Use the running app's session/mutation boundary for pairing, not a second DB writer."""
    invite = validate_payload(payload, payload['endpoint'])
    google = google or GoogleCalendar(settings)
    current = google.vault.get('client')
    expected = {k: payload['google_client']['installed'][k] for k in ('client_id','client_secret')}
    if current and current != expected:
        raise ValueError('This Mac already has another Google app registration. Existing settings were preserved.')
    with httpx.Client(base_url=settings.origin, timeout=30, trust_env=False, follow_redirects=False,
                      transport=transport) as client:
        client.get('/').raise_for_status()
        session = client.get('/api/session'); session.raise_for_status()
        client.headers.update({'Origin':settings.origin,'X-Airlock-CSRF':session.json()['csrf']})
        state = client.get('/api/exchange'); state.raise_for_status()
        # No silent identity replacement or changes to an already paired workspace.
        if state.json()['paired']:
            # A retry after successful pairing is allowed only for the same pinned identity.
            from .db import database
            from .models import ExchangeState
            from .memory import DOMAIN
            engine, sessions = database(settings)
            try:
                with sessions() as db:
                    row = db.get(ExchangeState, DOMAIN)
                    if (not row or row.pairing_id != invite.pairing_id
                            or row.endpoint != invite.endpoint or row.public_key != invite.public_key):
                        raise ValueError('Workspace is already paired to a different connector.')
            finally:
                engine.dispose()
        else:
            google.provision(payload['google_client'])
            response = client.post('/api/exchange/pair', json={'invitation':invite.model_dump(mode='json')})
            if response.status_code != 200:
                raise ValueError('Pairing did not finish. Keep this installation and retry airlock setup.')
    google.provision(payload['google_client'])


def interactive(settings):
    if not sys.stdin.isatty():
        raise SystemExit('Run setup in an interactive terminal; codes must not be passed in shell arguments.')
    vault = SetupKeys()
    try:
        payload = vault.get(settings.origin)
        if not payload:
            code = getpass.getpass('Setup code (hidden): ')
            endpoint, _ = parse_code(code)
            print('Setup destination: '+endpoint)
            if input('Retrieve configuration and pair with this connector? [y/N] ').strip().lower() != 'y':
                print('Setup cancelled.'); return
            payload = retrieve(code)
            # Preserve a locally retrieved package across later pairing/network failures.
            vault.set(settings.origin, payload)
        apply(settings, payload)
        vault.delete(settings.origin)
    except (Exception, KeyboardInterrupt):
        raise SystemExit('Setup did not finish. Check network/Keychain, then run .venv/bin/airlock setup again. If the code was consumed before it could be stored, request a new code. No sharing was enabled.') from None
    print('Google app configured and connector paired. Sharing remains unchanged (paused/off on a fresh workspace). Sign into Google locally, then review Sharing before enabling it.')
