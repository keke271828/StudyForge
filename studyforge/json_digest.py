"""Hash the same JSON bytes without allocating a whole encoded document."""
import hashlib
import json


def sha256(value, *, ensure_ascii=False, sort_keys=False, default=None):
    encoder = json.JSONEncoder(ensure_ascii=ensure_ascii, sort_keys=sort_keys, default=default)
    digest = hashlib.sha256()
    # Preserve dumps' separators, escaping, float representation and order.
    # Persisted generation and content keys remain valid after upgrading.
    for fragment in encoder.iterencode(value):
        digest.update(fragment.encode('utf-8'))
    return digest.hexdigest()
