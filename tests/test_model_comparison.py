"""Experiment instrumentation must not break native calls or export reasoning."""
import asyncio
import json

from scripts.compare_teaching_models import Metered


def test_native_recorder_accepts_positional_timeout_and_only_keeps_public_metadata():
    class Client:
        async def _post(self, body, timeout, retry=True):
            assert timeout==240 and retry is False
            return {'model':'actual-model','usage':{'total_tokens':42},
                    'choices':[{'message':{'content':'最终正文','reasoning_content':'PRIVATE_REASONING'}}]}
        async def complete(self, system, user):
            return (await self._post({'model':'requested'},240,retry=False))['choices'][0]['message']['content']
        async def close(self): self.closed=True
    async def run():
        base=Client();client=Metered(base)
        assert await client.complete(system='要求',user='资料')=='最终正文'
        assert client.partial=='最终正文'
        assert client.observed==[{'model':'actual-model','usage':{'total_tokens':42}}]
        assert 'PRIVATE_REASONING' not in json.dumps(client.observed)
        await client.close();assert base.closed
    asyncio.run(run())
