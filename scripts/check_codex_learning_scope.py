"""Read effective app-server settings; never start an inference turn."""
import asyncio
import json

from studyforge.codex_bridge import CodexBridge, NATIVE_CONTEXT_OVERRIDES


async def check():
    bridge=CodexBridge()
    try:
        await asyncio.wait_for(bridge.start(),30)
        result=await asyncio.wait_for(bridge.request('config/read',{'includeLayers':False}),15)
        config=result['config'];values={}
        for key,expected in NATIVE_CONTEXT_OVERRIDES.items():
            value=config
            for part in key.split('.'):value=value.get(part,{}) if isinstance(value,dict) else None
            values[key]=value
            if value is not expected:raise RuntimeError('Codex effective context boundary not confirmed: '+key)
        return {'success':True,'actual_app_server_initialized':True,'effective_settings':values,'inference_turns':0,
                'user_config_modified':False}
    finally:await bridge.close()


if __name__=='__main__':print(json.dumps(asyncio.run(check()),ensure_ascii=False,indent=2))
