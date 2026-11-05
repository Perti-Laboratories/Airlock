"""Bounded local text extraction; no macros, network fetches, or OCR."""
import io
import sys
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from .knowledge import MAX_TEXT
from .memory import ActionError

MAX_FILE = 2 * 1024 * 1024


def extract(filename, raw):
    if not 0 < len(raw) <= MAX_FILE:
        raise ActionError('Choose a document smaller than 2 MB.')
    ext = Path(filename).suffix.lower()
    if ext in {'.txt', '.md', '.csv'}:
        text = raw.decode('utf-8-sig')
    elif ext == '.eml':
        from email import policy
        from email.parser import BytesParser
        mail = BytesParser(policy=policy.default).parsebytes(raw)
        part = mail.get_body(preferencelist=('plain',))
        if part is None:
            raise ValueError('A plain-text email body is required.')
        text = '\n'.join(f'{k}: {mail.get(k, "")}' for k in ('Subject','From','To','Date')) + '\n\n' + part.get_content()
    elif ext == '.docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 4 * 1024 * 1024:
                raise ValueError('Document XML is too large.')
            xml = archive.read(info)
            if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                raise ValueError('Unsupported document XML.')
            root = ElementTree.fromstring(xml)
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            text = '\n'.join(''.join(p.itertext()) for p in root.iter(ns+'p'))
    elif ext == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError('Use an unencrypted PDF with at most 100 pages.')
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or '')
            if sum(map(len, parts)) > MAX_TEXT:
                raise ValueError('Too much extracted text.')
        text = '\n\n'.join(parts)
    else:
        raise ValueError('Use TXT, Markdown, CSV, DOCX, text PDF or plain-text EML.')
    text = text.replace('\x00', '').strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError('Use 1–60,000 text characters. Scans need OCR before uploading.')
    return text


def extract_isolated(filename, raw):
    # Parsers run in a short-lived child with CPU/address-space limits. No document paths
    # are accepted, raw bytes travel over stdin, and stderr never contains source content.
    import subprocess
    try:
        result = subprocess.run([sys.executable, '-m', 'airlock.document_parser', Path(filename).suffix.lower()],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
        data = json.loads(result.stdout)
        if not data.get('ok'):
            raise ValueError()
        return data['text']
    except (subprocess.SubprocessError, ValueError, KeyError):
        raise ActionError('Could not read this document. Use TXT, MD, CSV, DOCX, text PDF or plain-text EML; maximum 2 MB and 60,000 text characters. Scanned PDFs need OCR first.') from None


if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1536*1024*1024, 1536*1024*1024))
    except (ValueError, OSError):
        pass  # Some macOS Python runtimes do not support address-space limits.
    try:
        result = {'ok': True, 'text': extract('upload'+sys.argv[1], sys.stdin.buffer.read(MAX_FILE+1))}
    except Exception:
        result = {'ok': False}
    print(json.dumps(result))
