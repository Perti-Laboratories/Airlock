"""Maintainer tool: rebuild reviewed wheel hashes; never run during installation.

Edit exact versions in requirements.lock, then run this script with the development environment.
It rejects known advisories, missing dependencies, or unsatisfied version constraints.
"""
import json
from pathlib import Path
import re
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def pins(path):
    return {canonicalize_name(n): v for n,v in re.findall(r'^([\w.-]+)==([^\s\\]+)', path.read_text(), re.M)}


def metadata(pair):
    name, version = pair
    with urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
        data=json.load(response)
    if data.get('vulnerabilities'):
        raise ValueError(f'{name} has published advisories; review before locking.')
    return name,data


def closure(roots, versions, documents, platform):
    env={**default_environment(), 'python_version':'3.13', 'python_full_version':'3.13.5',
         'sys_platform':platform, 'platform_system':'Darwin' if platform=='darwin' else 'Linux',
         'os_name':'posix', 'extra':''}
    found=set()
    def visit(name):
        name=canonicalize_name(name)
        if name in found:return
        found.add(name)
        for value in documents[name]['info'].get('requires_dist') or []:
            r=Requirement(value)
            if r.marker and not r.marker.evaluate(env):continue
            key=canonicalize_name(r.name)
            if key not in versions or versions[key] not in r.specifier:
                raise ValueError(f'Pin a compatible dependency: {name} requires {r}')
            visit(key)
    for root in roots:visit(root)
    return found


def render(selected, versions, documents):
    lines=['# Reviewed wheel hashes from PyPI. CPython 3.13 is the tested target.',
           '# Regenerate with scripts/lock_dependencies.py after reviewing version changes.']
    for name in sorted(selected):
        hashes=sorted({x['digests']['sha256'] for x in documents[name]['urls']
                       if x['packagetype']=='bdist_wheel' and not x.get('yanked')})
        if not hashes:raise ValueError(f'No supported wheels for {name}')
        lines.append(name+'=='+versions[name]+' \\')
        lines.extend('    --hash=sha256:'+h+(' \\' if i<len(hashes)-1 else '') for i,h in enumerate(hashes))
    return '\n'.join(lines)+'\n'


def main():
    versions=pins(ROOT/'requirements.lock')
    with ThreadPoolExecutor(max_workers=8) as pool:
        docs=dict(pool.map(metadata,versions.items()))
    closure(versions,versions,docs,'darwin')
    connector=closure(['fastapi','uvicorn','pydantic','cryptography','httpx','setuptools','wheel'],versions,docs,'linux')
    (ROOT/'requirements.lock').write_text(render(versions,versions,docs))
    (ROOT/'connector/requirements.lock').write_text(render(connector,versions,docs))
    print(f'Locked {len(versions)} local packages and {len(connector)} connector packages; no listed advisories.')


if __name__=='__main__':main()
