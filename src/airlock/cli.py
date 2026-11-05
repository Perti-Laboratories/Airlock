import argparse
import uuid
from sqlalchemy import select, func
from .config import Settings, USER_ID
from .db import database
from .memory import DOMAIN
from .models import Domain, User, LocalState


def initialize(settings):
    _, sessions = database(settings)
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Domain).where(Domain.id != DOMAIN)):
            raise SystemExit("Refusing to use a database with other domains.")
        if db.get(Domain, DOMAIN) is None:
            db.add(Domain(id=DOMAIN, name=settings.workspace_name))
        if db.get(User, uuid.UUID(USER_ID)) is None:
            db.add(User(id=uuid.UUID(USER_ID)))
        if db.get(LocalState, 1) is None:
            db.add(LocalState(id=1))
        db.commit()


def main():
    parser = argparse.ArgumentParser(description="Airlock local assistant")
    parser.add_argument("command", choices=["init", "serve", "google-configure", "google-provision"])
    parser.add_argument("client_file", nargs="?")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "init":
        initialize(settings)
        print("Initialized the isolated Airlock workspace.")
    elif args.command == "google-provision":
        from .google import GoogleCalendar, GoogleError
        from .provisioning import provision_google
        try:
            result = provision_google(GoogleCalendar(settings), args.client_file)
        except GoogleError as exc:
            raise SystemExit(str(exc)) from None
        print({
            "configured": "Google app configured in Keychain. Open Connections and select Connect Google.",
            "already_configured": "Existing Google app configuration preserved.",
            "not_supplied": "Google app registration is not supplied in this build. Local features are ready; Google sign-in still needs provisioning.",
        }[result])
    elif args.command == "google-configure":
        import json
        from pathlib import Path
        from .google import GoogleCalendar
        if not args.client_file: parser.error("google-configure requires a Desktop OAuth client JSON path")
        document=json.loads(Path(args.client_file).read_text())
        GoogleCalendar(settings).configure(document)
        print("Desktop client stored in macOS Keychain. Open Connections in Airlock to connect Google.")
    else:
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port,
                    proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
