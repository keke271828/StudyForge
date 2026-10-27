"""Entry point for the bundled backend, including its standalone MCP transport."""
from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> None:
    multiprocessing.freeze_support()
    # Prevent optional libraries writing caches into the installation directory.
    from studyforge.config import data_dir
    os.environ.setdefault("MPLCONFIGDIR", str(data_dir() / "cache" / "matplotlib"))
    if '--asr-probe' in sys.argv:
        from studyforge.asr_backend import child_probe
        position=sys.argv.index('--asr-probe')
        child_probe(sys.argv[position+1])
    elif "--mcp" in sys.argv:
        from studyforge.mcp_server import mcp
        # MCP closes its transport streams on EOF. Give it duplicate handles so
        # Python/PyInstaller can still flush the original streams during exit.
        import io
        original_stdin, original_stdout = sys.stdin, sys.stdout
        sys.stdin = io.TextIOWrapper(os.fdopen(os.dup(original_stdin.fileno()), 'rb', buffering=0), encoding='utf-8')
        sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(original_stdout.fileno()), 'wb', buffering=0),
                                     encoding='utf-8', write_through=True)
        try:
            mcp.run(transport="stdio")
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout
    elif "--self-check" in sys.argv:
        from studyforge.packaging_check import self_check
        self_check()
    else:
        from studyforge.runtime import manage_desktop_lifetime
        manage_desktop_lifetime()
        import uvicorn
        from studyforge.server import app
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("STUDYFORGE_PORT", "8765")),
                    reload=False, log_level="info")


if __name__ == "__main__":
    main()
