"""Exercise the real transport wrapper, without credentials or provider traffic."""
import pytest
from airlock.google import GoogleError, request_google


@pytest.mark.parametrize('status', [400, 401, 403, 410, 429, 503])
def test_http_status_survives_value_error_handler(monkeypatch, status):
    class Connection:
        closed = False
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return self
        def read(self, limit): return b'{"error":"PRIVATE_PROVIDER_DETAIL"}'
        def close(self): self.closed = True
    connection = Connection()
    connection.status = status
    monkeypatch.setattr('airlock.google.http.client.HTTPSConnection', lambda *a, **k: connection)
    with pytest.raises(GoogleError) as error:
        request_google('oauth2.googleapis.com', '/token', form={'refresh_token': 'PRIVATE_TOKEN'})
    assert error.value.status == status
    assert 'PRIVATE' not in str(error.value)
    assert connection.closed


def test_network_error_remains_generic(monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise OSError('PRIVATE_NETWORK_DETAIL')
        def close(self): pass
    monkeypatch.setattr('airlock.google.http.client.HTTPSConnection', Connection)
    with pytest.raises(GoogleError, match='Google is unavailable') as error:
        request_google('www.googleapis.com', '/calendar/v3/users/me/calendarList')
    assert error.value.status == 0
    assert 'PRIVATE' not in str(error.value)
