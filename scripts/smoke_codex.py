"""Optional real Codex App Server smoke test."""

import asyncio

from studyforge.codex_bridge import bridge


async def main():
    try:
        await bridge.start()
        print("App Server initialized", flush=True)
        pieces = []
        async for kind, value in bridge.stream_turn("Reply with exactly: Codex connected."):
            if kind == "thread":
                print("Thread:", value, flush=True)
            if kind == "delta":
                pieces.append(value)
        print("".join(pieces))
        if not pieces:
            raise SystemExit("No Codex response")
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
