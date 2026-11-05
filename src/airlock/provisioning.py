"""Install a distributor-supplied Desktop client without replacing local credentials."""

import json
from importlib.resources import files
from pathlib import Path

from .google import GoogleError


def provision_google(google, client_file=None):
    source = Path(client_file) if client_file else files("airlock").joinpath(
        "google_desktop_client.json"
    )
    if not source.is_file():
        if client_file:
            raise GoogleError("The supplied Google app configuration file is missing.")
        return "not_supplied"
    # Updates must preserve an organization's custom client and account binding.
    if google.status()["configured"]:
        return "already_configured"
    try:
        with source.open("rb") as handle:
            raw = handle.read(20_001)
        if len(raw) > 20_000:
            raise ValueError("oversized")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        raise GoogleError("Could not read a valid Google Desktop app configuration.") from exc
    google.provision(document)
    return "configured"
