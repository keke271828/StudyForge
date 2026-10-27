"""Keep tool notifications flowing while the same model turn awaits a decision."""
from __future__ import annotations

import asyncio
import inspect


async def relay_tool_events(stream, runtime, encode):
    """One producer owns the original turn; cancelling the stream cancels its tools."""
    queue = asyncio.Queue(maxsize=32)
    previous = runtime.on_event
    stopped = object()
    closing = False

    async def notify(event):
        if previous:
            result = previous(event)
            if inspect.isawaitable(result):
                await result
        await queue.put(encode(event))

    async def produce():
        try:
            async for item in stream:
                await queue.put(item)
        finally:
            try:
                close = getattr(stream, 'aclose', None)
                if close:
                    await close()
            finally:
                if not closing:
                    await queue.put(stopped)

    runtime.on_event = notify
    producer = asyncio.create_task(produce())
    try:
        while True:
            item = await queue.get()
            if item is stopped:
                await producer
                return
            yield item
    finally:
        closing = True
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        runtime.on_event = previous
