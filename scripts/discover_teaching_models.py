"""Read configured model candidates; never export credentials or learner DB."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time


async def main(folder):
    root = Path(__file__).resolve().parents[1]
    out = root / 'build' / folder
    out.mkdir(parents=True, exist_ok=True)
    original = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'StudyForge'
    settings_path, services_path = original / 'settings.json', original / 'model-services.json'
    config = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
    services = json.loads(services_path.read_text(encoding='utf-8')) if services_path.exists() else []
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge.config import get_secret
    from studyforge.providers import secret_name
    from studyforge.codex_bridge import CodexBridge
    from studyforge.model_catalog import _normalize
    import httpx
    data = {'deepseek_key_present': bool(get_secret('DEEPSEEK_API_KEY')),
            'current': {key: config.get(key) for key in ('chat_provider','codex_model','deepseek_model','chat_model_codex','chat_model_deepseek','chat_effort_codex','chat_effort_deepseek')},
            'services': [{key: row.get(key) for key in ('id','name','protocol','default_model','models','enabled','supports_vision')}
                         | {'key_present': bool(get_secret(secret_name(row['id'])))} for row in services]}
    # Copy only the service registry into the experiment's data. Keyring stays
    # private; no token is serialized, no learner tables or chat are loaded.
    if services:
        (out / 'data').mkdir(exist_ok=True)
        (out / 'data/model-services.json').write_text(json.dumps(services, ensure_ascii=False), encoding='utf-8')
    (out / 'inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=True),flush=True)

    async def codex():
        bridge = CodexBridge()
        try: data['codex_catalog'] = _normalize(await asyncio.wait_for(bridge.list_models(),25))
        except Exception as exc: data['codex_catalog_error'] = type(exc).__name__+': '+str(exc)[:300]
        finally: await bridge.close()
        (out / 'inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'codex_catalog':data.get('codex_catalog'), 'error':data.get('codex_catalog_error')},ensure_ascii=True),flush=True)

    async def deepseek():
        if not data['deepseek_key_present']: return
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25,connect=12)) as client:
                response = await client.get('https://api.deepseek.com/models',headers={'Authorization':'Bearer '+get_secret('DEEPSEEK_API_KEY')})
                response.raise_for_status()
                data['deepseek_catalog'] = [{'id': row['id']} for row in response.json().get('data',[]) if isinstance(row,dict) and isinstance(row.get('id'),str)]
        except Exception as exc: data['deepseek_catalog_error'] = type(exc).__name__
        (out / 'inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'deepseek_catalog':data.get('deepseek_catalog'),'error':data.get('deepseek_catalog_error')},ensure_ascii=True),flush=True)
    await asyncio.gather(codex(),deepseek())


if __name__=='__main__': asyncio.run(main(sys.argv[1]))
