"""Check that StudyForge can produce text through the selected Codex model."""

import asyncio
import os
import sys
import tempfile

from studyforge.ai import CodexClient, save_settings
from studyforge.codex_bridge import bridge


async def main() -> None:
    if len(sys.argv) > 1:
        os.environ["STUDYFORGE_DATA_DIR"] = tempfile.mkdtemp(prefix="studyforge-model-smoke-")
        save_settings({"codex_model": sys.argv[1]})
    try:
        reply = await CodexClient().complete("只用中文回答。", "用一句话说明牛顿第二定律。")
        print(reply)
        if not reply.strip():
            raise RuntimeError("Codex 返回空内容")
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
