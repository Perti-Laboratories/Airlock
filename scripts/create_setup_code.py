"""Operator-side package creation. Never run with real files in a public CI job."""
import argparse
import json
import os
from pathlib import Path
from airlock_contracts.setup import prepare
from airlock.setup_code import validate_payload


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--google-client', type=Path, required=True)
    p.add_argument('--invitation', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='New private output directory outside this repository')
    p.add_argument('--hours', type=int, default=24, choices=range(1,25))
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=args.output.expanduser().resolve()
    if output.is_relative_to(root):
        p.error('Store setup material outside the source repository.')
    google=json.loads(args.google_client.read_text())
    invite=json.loads(args.invitation.read_text())
    validate_payload({'google_client':google,'invitation':invite},invite['endpoint'])
    code,envelope=prepare(invite['endpoint'],google,invite,ttl=args.hours*3600)
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    (output/'setup-code.txt').write_text(code+'\n')
    (output/'envelope.json').write_text(json.dumps(envelope))
    print('Private setup code and encrypted host envelope created. Install the envelope on the connector, then deliver the code through a trusted private channel. Neither file belongs in Git.')


if __name__=='__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Could not create setup package. Check the supplied files and choose a new private output directory. Configuration contents were not printed.') from None
