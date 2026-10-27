"""Read the locally installed Codex App Server model catalog without changing settings."""

import asyncio

from studyforge.codex_bridge import bridge


async def main():
    try:
        models = await bridge.list_models()
        print("models", len(models))
        print([item.get("id") or item.get("model") for item in models[:8]])
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
