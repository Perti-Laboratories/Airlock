"""Minimal harness adapter; imports no Airlock runtime or private domain services."""
import json
from urllib.parse import urlsplit
import httpx


class ConnectorClient:
    def __init__(self, endpoint, token):
        origin=urlsplit(endpoint)
        if origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"} or not origin.hostname:
            raise ValueError("Use a plain connector origin.")
        if origin.scheme != "https" and not (origin.scheme=="http" and origin.hostname=="127.0.0.1"):
            raise ValueError("HTTPS is required except for a loopback test.")
        self.client=httpx.Client(base_url=endpoint,headers={'Authorization':'Bearer '+token},
            timeout=10,follow_redirects=False,trust_env=False)

    def _request(self, method, path, **kwargs):
        # Bound decoded streaming bytes too, including compressed/chunked responses.
        with self.client.stream(method, path, **kwargs) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(body) + len(chunk) > 1_000_000:
                    raise ValueError('Connector response too large.')
                body.extend(chunk)
            return json.loads(body)

    def signed_release(self):
        return self._request('GET', '/v1/harness/release')

    def projections(self):
        """Reconcile the complete returned set, including empty/expired sets; never append blindly."""
        return self._request('GET', '/v1/harness/projections')

    def availability_status(self):
        return self._request('GET', '/v1/harness/availability')

    def replace_availability(self, items, expected_revision):
        return self._request('PUT', '/v1/harness/availability',
                             json={'items': items, 'expected_revision': expected_revision})

    def records_status(self):
        return self._request('GET', '/v2/harness/records')

    def replace_records(self, items, expected_revision, policy_message_id):
        return self._request('PUT', '/v2/harness/records', json={'items': items,
            'expected_revision': expected_revision, 'policy_message_id': str(policy_message_id)})

    def close(self):
        self.client.close()
