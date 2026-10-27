"""Reuse exact adjacent video PNGs without altering frame sampling or coverage."""
from pathlib import Path


class ExactFrameOCR:
    def __init__(self, recognize):
        self.recognize = recognize
        self.previous_hash = None
        self.previous_text = None
        self.requests = 0
        self.reused = 0

    def read(self, path: Path):
        from .materials import file_sha256
        try:
            checksum = file_sha256(path)
        except OSError:
            checksum = None
        if checksum is not None and checksum == self.previous_hash and self.previous_text is not None:
            self.reused += 1
            return self.previous_text
        self.requests += 1
        text = self.recognize(path)
        valid = isinstance(text, str) and len(text) <= 32000 and not text.startswith('[OCR 未完成')
        try:
            unchanged = checksum is not None and file_sha256(path) == checksum
        except OSError:
            unchanged = False
        self.previous_hash = checksum if valid and unchanged else None
        self.previous_text = text if valid and unchanged else None
        return text
