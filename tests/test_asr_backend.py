import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from studyforge import ai,asr_backend,local_compute,media,task_timing
from studyforge.db import create_job,create_project,execute,one,update_job
from studyforge.scheduling import execution_scope,run_local


@pytest.fixture(autouse=True)
def isolated_engine(monkeypatch):
    monkeypatch.setattr(asr_backend,'gpu_count',lambda:0)
    with local_compute._lock:
        if local_compute._timer:local_compute._timer.cancel();local_compute._timer=None
        local_compute._models.clear()
    asr_backend._probes.clear();asr_backend._failures.clear()
    yield
    with local_compute._lock:
        if local_compute._timer:local_compute._timer.cancel();local_compute._timer=None
        local_compute._models.clear()


def test_local_snapshot_never_requests_network():
    calls=[]
    def factory(name,**kwargs):calls.append((name,kwargs));return object()
    assert asr_backend.local_first_model(factory,'small',device='cpu')
    assert len(calls)==1 and calls[0][1]['local_files_only'] is True


def test_only_missing_snapshot_may_download_selected_model():
    from huggingface_hub.errors import LocalEntryNotFoundError
    calls=[]
    def factory(name,**kwargs):
        calls.append((name,kwargs))
        if kwargs['local_files_only']:raise LocalEntryNotFoundError('fixture cache missing')
        return object()
    assert asr_backend.local_first_model(factory,'medium',device='cpu')
    assert [item[0] for item in calls]==['medium','medium']
    assert [item[1]['local_files_only'] for item in calls]==[True,False]


def test_corrupt_or_failed_model_does_not_trigger_another_model_or_network():
    calls=[]
    def factory(name,**kwargs):calls.append(name);raise RuntimeError('fixture invalid model')
    with pytest.raises(RuntimeError):asr_backend.local_first_model(factory,'small',device='cpu')
    assert calls==['small']


def test_cpu_preference_does_not_probe_gpu(monkeypatch):
    monkeypatch.setattr(asr_backend,'gpu_count',lambda:pytest.fail('GPU discovery for CPU'))
    assert asr_backend.choose_device('small','cpu')==('cpu','')


def test_missing_runtime_keeps_cpu_model_and_explains(monkeypatch):
    monkeypatch.setattr(asr_backend,'gpu_count',lambda:1)
    monkeypatch.setattr(asr_backend,'prepare_cuda',lambda:(False,'runtime missing'))
    monkeypatch.setattr(asr_backend,'probe',lambda name:pytest.fail('Missing runtime must not start child'))
    assert asr_backend.choose_device('small','cuda')==('cpu','runtime missing')


def test_checked_gpu_and_failed_probes_are_cached_and_bound_to_model(monkeypatch):
    monkeypatch.setattr(asr_backend,'gpu_count',lambda:1)
    monkeypatch.setattr(asr_backend,'prepare_cuda',lambda:(True,''))
    monkeypatch.setattr(asr_backend,'fingerprint',lambda name:(name,'fixture-runtime'))
    calls=[]
    def probe(name):calls.append(name);return (True,'') if name=='small' else (False,'fixture failure')
    monkeypatch.setattr(asr_backend,'probe',probe)
    assert asr_backend.choose_device('small','auto')==asr_backend.choose_device('small','cuda')==('cuda','')
    assert asr_backend.choose_device('base','auto')==asr_backend.choose_device('base','auto')==('cpu','fixture failure')
    assert calls==['small','base']
    asr_backend.mark_failure('small')
    assert asr_backend.choose_device('small','auto')[0]=='cpu' and calls==['small','base']


@pytest.mark.parametrize('device',['cpu','cuda'])
def test_loading_retains_model_accuracy_and_releases_engine_on_mode_change(monkeypatch,device):
    import faster_whisper
    calls=[]
    def factory(name,**kwargs):
        calls.append((name,kwargs));return SimpleNamespace(model=SimpleNamespace(compute_type='int8_float32'))
    monkeypatch.setattr(faster_whisper,'WhisperModel',factory)
    monkeypatch.setattr(asr_backend,'choose_device',lambda name,pref:(device,''))
    first=asr_backend.load_model('small','auto')
    assert first is asr_backend.load_model('small','auto') and len(calls)==1
    assert calls[0][0]=='small' and calls[0][1]['cpu_threads']<=4 and calls[0][1]['num_workers']==1
    assert calls[0][1]['local_files_only'] is True
    assert first._studyforge_asr['actual_device']==device
    assert first is not asr_backend.load_model('small','cpu') and len(calls)==2


def write_wav(*args,**kwargs):
    with wave.open(str(args[-1]),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\x00\x00'*16000)


def test_model_load_failure_never_silently_downgrades_to_tiny(tmp_path,monkeypatch):
    path=tmp_path/'original.mp4';path.write_bytes(b'original video');calls=[]
    monkeypatch.setattr(media,'run_ffmpeg',write_wav)
    def fail(name):calls.append(name);raise RuntimeError('fixture unavailable')
    monkeypatch.setattr(media,'_whisper_model',fail)
    with pytest.raises(RuntimeError,match='small'):media.transcribe(path)
    assert calls==['small'] and path.read_bytes()==b'original video'
    assert not list((tmp_path/'data/tmp').rglob('*.wav'))


def test_gpu_failure_discards_partial_output_and_retries_full_same_model(tmp_path,monkeypatch):
    path=tmp_path/'source.mp4';path.write_bytes(b'original');calls=[]
    monkeypatch.setattr(media,'run_ffmpeg',write_wav)
    class Engine:
        def __init__(self,device):self._studyforge_asr=dict(actual_device=device,actual_model='small',compute_type='int8_float32')
        def transcribe(self,audio,**options):
            calls.append((self._studyforge_asr['actual_device'],audio,options))
            def parts():
                if self._studyforge_asr['actual_device']=='cuda':
                    yield SimpleNamespace(start=0,end=.5,text='禁止交付的部分 GPU 转录')
                    raise RuntimeError('fixture CUDA interrupted')
                yield SimpleNamespace(start=0,end=1,text='完整同模型 CPU 转录')
            return parts(),None
    def factory(name):assert name=='small';return Engine('cpu' if media._asr_device.get()=='cpu' else 'cuda')
    monkeypatch.setattr(media,'_whisper_model',factory)
    project=create_project('GPU recovery');job=create_job(project['id'],'import',{})
    async def run():
        async with execution_scope(job_id=job,project_id=project['id']):
            return await run_local('media',media.transcribe,path,label='test speech')
    result=asyncio.run(run())
    assert result==[dict(start=0,end=1,text='完整同模型 CPU 转录')]
    assert len(calls)==2 and calls[0][1]==calls[1][1]
    assert all(item[2]==dict(language=None,vad_filter=True,beam_size=5) for item in calls)
    assert not Path(calls[0][1]).exists()
    update_job(job,'completed',100,{'separate':'final result'})
    info=task_timing.detail(job)['asr_execution']
    assert info['actual_model']=='small' and info['actual_device']=='cpu' and info['beam_size']==5
    assert 'GPU' in info['fallback_reason'] and info['audio_seconds']==1
    assert all(row['resource']!='asr_info' for row in task_timing.detail(job)['resources'])


def test_explicit_chinese_keeps_initial_prompt_and_no_new_vad_policy(tmp_path,monkeypatch):
    path=tmp_path/'voice.wav';path.write_bytes(b'voice');values=[]
    monkeypatch.setattr(media,'run_ffmpeg',write_wav)
    class Engine:
        def transcribe(self,audio,**options):values.append(options);return iter([]),None
    monkeypatch.setattr(media,'_whisper_model',lambda name:Engine())
    assert media.transcribe(path,'zh')==[]
    assert values[0]['beam_size']==5 and values[0]['vad_filter'] is False and values[0]['language']=='zh'
    assert '专有名词' in values[0]['initial_prompt']


def test_execution_receipt_survives_result_replace_and_never_resurrects_job():
    project=create_project('speech evidence');job=create_job(project['id'],'read',{})
    async def run():
        async with execution_scope(job_id=job,project_id=project['id']):
            task_timing.record_info('asr_execution',dict(actual_device='cpu',actual_model='small',text='PRIVATE_AUDIO',path='PRIVATE_PATH'))
            update_job(job,'completed',100,{'ordinary':'result'})
            value=task_timing.detail(job)
            assert value['asr_execution']==dict(actual_device='cpu',actual_model='small')
            assert 'PRIVATE' not in json.dumps(value)
            execute('DELETE FROM jobs WHERE id=?',(job,))
            before=one('SELECT COUNT(*) AS n FROM execution_spans')['n']
            task_timing.record_info('asr_execution',dict(actual_device='cuda'))
            assert one('SELECT COUNT(*) AS n FROM execution_spans')['n']==before
    asyncio.run(run())


def test_device_settings_and_check_use_current_unsaved_form_without_saving(monkeypatch):
    from fastapi.testclient import TestClient
    from studyforge import server
    api=TestClient(server.app)
    assert api.put('/api/settings',json={'whisper_device':'cpu'}).status_code==200
    assert api.put('/api/settings',json={'whisper_device':[]}).status_code==400
    calls=[]
    def choose(name,preference):calls.append((name,preference));return 'cpu','fixture unavailable'
    monkeypatch.setattr(asr_backend,'choose_device',choose)
    result=api.post('/api/asr/check',json={'model':'base','device':'cuda'}).json()
    assert calls==[('base','cuda')] and result['selected_model']=='base' and result['actual_device']=='cpu'
    assert ai.settings()['whisper_device']=='cpu' and ai.settings()['whisper_model']=='small'
    assert api.post('/api/asr/check',json={'model':'unknown','device':'cuda'}).status_code==422
