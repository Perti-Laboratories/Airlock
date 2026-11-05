# Optional read-only Google Calendar

No Google account is required for local use. Register an OAuth **Desktop app** in an appropriate
Google Cloud project with Calendar API enabled. Configure its audience, test users and applicable
verification/administrator approval. The source distribution contains no OAuth client or tokens.

Download the client JSON and provision it locally:

```sh
.venv/bin/airlock google-provision /absolute/path/to/desktop-client.json
```

Alternatively use **Settings & Activity → Connections → Advanced · custom Google app**.
Then choose **Connect Google**, complete browser sign-in and select calendars. Airlock uses the
installed-app loopback callback, OAuth state and PKCE; credentials remain in macOS Keychain.
Never put downloaded credentials in a public issue, chat or source commit.

The requested scopes are `calendar.events.readonly` and `calendar.calendarlist.readonly` under
`https://www.googleapis.com/auth/`. These are account scopes: local calendar selection limits
what Airlock ingests, not what Google authorized. Airlock does not write Google Calendar or request
Gmail, Drive or contacts access. It polls selected sources while running. Models process locally.

An organization's SSO may participate in browser sign-in; successful authentication does not override
its OAuth client-access rules. Local installation does not bypass administrator restrictions.
Testing-mode grants can expire; consult Google's current documentation for deployment requirements.

Start with a synthetic calendar. Verify create, move, recurring exceptions, cancellation, all-day
and timezone behavior. A local note should survive a provider refresh. Selecting a source does not
approve external release. Review sharing rules separately before enabling any output.

Disconnect removes local account tokens and pauses sources but retains imported records/notes.
It does not revoke the grant at Google or erase local history. Use Google account settings to revoke
third-party access. Changing accounts requires an explicit disconnect before connecting again.

References: [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Calendar scopes](https://developers.google.com/workspace/calendar/api/auth),
[Workspace OAuth controls](https://developers.google.com/identity/protocols/oauth2/production-readiness/google-workspace).
