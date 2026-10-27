"""Check a public URL using the same importer as the application."""
import os
import sys
import tempfile

os.environ['STUDYFORGE_DATA_DIR'] = tempfile.mkdtemp(prefix='studyforge-url-smoke-')
from studyforge.urls import BrowserImportRequired, download_public_resource
from studyforge.parsers import parse_file

try:
    original = download_public_resource(sys.argv[1], 'public-page')
    parts = parse_file(original)
    print('Downloaded:', original)
    print('Segments:', len(parts), 'characters:', sum(len(part['text']) for part in parts))
except BrowserImportRequired as exc:
    print('Browser import required:', str(exc))
