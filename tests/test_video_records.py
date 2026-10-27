import asyncio
import json
import shutil

import pytest
from docx import Document
from PIL import Image

from studyforge import agent_tools, media, parsers, server
from studyforge.ai import save_settings
from studyforge.config import files_dir,temp_dir
from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
from studyforge.materials import read_original_sources
from studyforge.video_records import write_record,read_record,recognized_parts,clean_download


def test_recognition_gaps_preserve_location_and_do_not_reconstruct():
    parts=recognized_parts([{'text':'高斯\ufffd定律\x00与\ud800板书','locator':'10秒','meta':{}}])
    assert parts[0]['text']=='高斯[无法辨认]定律[无法辨认]与[无法辨认]板书'
    assert parts[0]['meta']['recognition_issue_count']==3
    assert parts[0]['meta']['recognition_issues'][0]=={'offset':2,'codepoint':'U+FFFD'}
    assert parts[0]['locator']=='10秒'


def test_capsule_reopens_full_text_and_checks_frames_without_video(tmp_path):
    image=tmp_path/'frame.png';Image.new('RGB',(12,12),'white').save(image)
    original=files_dir()/(uid()+'.sfvideo')
    parts=[{'locator':'0-10秒','text':'完整字幕\ufffd尾部重要细节','kind':'transcript','meta':{}},
           {'locator':'约10秒画面','text':'F=ma','kind':'video_frame','meta':{'image_path':str(image),'time':10}}]
    write_record(original,parts,url='https://example.org/lecture')
    reopened=read_record(original)
    assert reopened[0]['text'].endswith('尾部重要细节')
    record=read_original_sources([{'id':'source','name':'视频','original_path':str(original),'segments':[]}])[0]
    assert record['segments'][1]['meta']['time']==10
    assert any('识别异常' in x for x in record['read_manifest']['limitations'])
    save_settings({'agent_web_video_enabled':True})
    runtime=agent_tools.AgentRuntime();runtime.web_paths.add(str(original))
    page=runtime.text_page(record['segments'],agent_tools.ReadFile(path=str(original)),'视频',original)
    assert runtime.checked_path(page['media_frames'][0]['path']).is_file()
    frame=original.with_suffix('.frames')/'00001.png';frame.write_bytes(b'changed')
    with pytest.raises(ValueError,match='画面缺失或已变更'):read_record(original)


def test_url_import_sanitizes_docx_and_removes_both_owned_video_copies(tmp_path,monkeypatch):
    folder=temp_dir()/'downloads'/uid();folder.mkdir(parents=True)
    video=folder/'clip.mp4';video.write_bytes(b'remote video bytes')
    Image.new('RGB',(30,30),'white').save(tmp_path/'frame.png')
    parts=[{'locator':'0-10秒','text':'原文\ufffd重要内容\x00','kind':'transcript','meta':{'start':0,'end':10}},
           {'locator':'10秒画面','text':'F=ma','kind':'video_frame','meta':{'image_path':str(tmp_path/'frame.png'),'time':10}}]
    monkeypatch.setattr(server,'download_public_resource',lambda *a,**kw:video)
    monkeypatch.setattr(server,'parse_file',lambda p:parts)
    project=create_project('完整视频');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,created_at) VALUES (?,?,?,?,?,?)',(sid,project['id'],'视频课程','url','',now()))
    job=create_job(project['id'],'import',{})
    asyncio.run(server._url_job(job,sid,'https://example.org/video'))
    task=one('SELECT * FROM jobs WHERE id=?',(job,));assert task['status']=='completed',task['error']
    row=one('SELECT * FROM sources WHERE id=?',(sid,));assert row['status']=='ready' and row['kind']=='.sfvideo'
    assert not video.exists() and not (files_dir()/(sid+'.mp4')).exists()
    original=many("SELECT * FROM artifacts WHERE kind='original'")[0]
    document=Document(original['path']);text='\n'.join(p.text for p in document.paragraphs)
    assert '[无法辨认]' in text and '重要内容' in text and '\ufffd' not in text and len(document.inline_shapes)==1
    reopened=read_original_sources([dict(row,segments=unj(row['segments_json']))])[0]
    assert reopened['segments'][1]['meta']['time']==10
    assert read_record(files_dir()/(sid+'.sfvideo'))


def test_cleanup_never_removes_user_video_or_sibling_download(tmp_path):
    local=tmp_path/'local.mp4';local.write_bytes(b'user original');clean_download(local);assert local.exists()
    root=temp_dir()/'downloads';a,b=root/uid(),root/uid();a.mkdir(parents=True);b.mkdir();(a/'clip.mp4').write_bytes(b'owned');(b/'clip.mp4').write_bytes(b'other')
    clean_download(a/'clip.mp4');assert not a.exists() and b.exists()


def test_subtitle_first_does_not_download_video(monkeypatch):
    from http.cookiejar import CookieJar
    import httpx,yt_dlp
    save_settings({'video_import_mode':'subtitles_first'})
    monkeypatch.setattr('studyforge.urls.validate_public_url',lambda u:u)
    calls=[]
    class Downloader:
        def __init__(self,opts):self.opts=opts;self.cookiejar=CookieJar()
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def extract_info(self,url,download):
            calls.append(download)
            return {'title':'课堂','duration':10,'requested_subtitles':{'zh':{'url':'https://example.org/caption','ext':'json'}}}
    monkeypatch.setattr(yt_dlp,'YoutubeDL',Downloader)
    native=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:native(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'body':[{'from':0,'to':10,'content':'真实课堂全文'}]})),**kw))
    path=media.download_public_video('https://example.org/lecture')
    assert calls==[False] and path.suffix=='.sfvideo'
    parts=read_record(path);assert parts[0]['text']=='真实课堂全文' and '未分析视频画面' in parts[-1]['text']
    assert not list(path.parent.glob('*.mp4'))


def test_agent_reopens_timed_video_record_after_new_runtime_without_downloading(monkeypatch):
    from studyforge import conversations
    from studyforge.config import derived_dir
    folder=temp_dir()/'downloads'/uid();folder.mkdir(parents=True)
    video=folder/'clip.mp4';video.write_bytes(b'owned remote video')
    derived=derived_dir(video,'frames');frame=derived/'00000.png';Image.new('RGB',(30,30),'green').save(frame)
    save_settings({'agent_web_video_enabled':True})
    parts=[{'locator':'0-10秒','text':'完整字幕尾部重要论据','kind':'transcript','meta':{}},
           {'locator':'10秒画面','text':'板书','kind':'video_frame','meta':{'image_path':str(frame),'time':10}}]
    monkeypatch.setattr(agent_tools,'download_public_resource',lambda *a,**kw:video)
    monkeypatch.setattr(agent_tools,'validate_public_url',lambda u:u)
    monkeypatch.setattr(agent_tools,'parse_file',lambda p:parsers.parse_file(p) if p.suffix=='.sfvideo' else parts)
    project=create_project('重开视频对话');chat=conversations.create(project['id'],'deepseek')
    first=agent_tools.AgentRuntime(project['id'],conversation_id=chat['id'])
    url='https://www.bilibili.com/video/BV1xx411c7mD'
    result=asyncio.run(first.execute('sf_read_url',{'url':url}))
    assert 'error' not in result and not video.exists() and not folder.exists() and not derived.exists()
    def never_download(*a,**kw):raise AssertionError('Must reuse persisted video record')
    monkeypatch.setattr(agent_tools,'download_public_resource',never_download)
    reopened=agent_tools.AgentRuntime(project['id'],conversation_id=chat['id'])
    result=asyncio.run(reopened.execute('sf_read_url',{'url':url}))
    assert result['media_frames'][0]['time']==10 and '尾部重要论据' in result['text']


def test_subtitle_record_import_copies_frames_title_and_removes_download(monkeypatch):
    folder=temp_dir()/'downloads'/uid();folder.mkdir(parents=True)
    record=write_record(folder/'transcript.sfvideo',[{'text':'原字幕全文','locator':'0-10秒','kind':'transcript','meta':{}}],title='真正的课程标题',metadata={'mode':'subtitles_only','limitation':'未读取画面'})
    monkeypatch.setattr(server,'download_public_resource',lambda *a,**kw:record)
    project=create_project('字幕免下载');sid=uid();execute('INSERT INTO sources(id,project_id,name,kind,original_path,created_at) VALUES (?,?,?,?,?,?)',(sid,project['id'],'网址','url','',now()))
    job=create_job(project['id'],'import',{});asyncio.run(server._url_job(job,sid,'https://example.org/lecture'))
    row=one('SELECT * FROM sources WHERE id=?',(sid,));assert row['status']=='ready' and row['name']=='真正的课程标题'
    assert not folder.exists() and read_record(files_dir()/(sid+'.sfvideo'))[0]['text']=='原字幕全文'


def test_failed_video_import_removes_unused_remote_copies(monkeypatch):
    folder=temp_dir()/'downloads'/uid();folder.mkdir(parents=True);video=folder/'clip.mp4';video.write_bytes(b'owned')
    monkeypatch.setattr(server,'download_public_resource',lambda *a,**kw:video)
    def failed(path):raise RuntimeError('识别失败')
    monkeypatch.setattr(server,'parse_file',failed)
    project=create_project('失败清理');sid=uid();execute('INSERT INTO sources(id,project_id,name,kind,original_path,created_at) VALUES (?,?,?,?,?,?)',(sid,project['id'],'网址','url','',now()))
    job=create_job(project['id'],'import',{});asyncio.run(server._url_job(job,sid,'https://example.org/video'))
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='failed'
    assert not folder.exists() and not (files_dir()/(sid+'.mp4')).exists()


def test_web_read_can_explicitly_refresh_or_recover_deleted_cache(monkeypatch):
    calls=[]
    def download(*a,**kw):
        path=temp_dir()/(uid()+'.txt');path.write_text('网页内容版本'+str(len(calls)),encoding='utf-8');calls.append(path);return path
    monkeypatch.setattr(agent_tools,'download_public_resource',download)
    monkeypatch.setattr(agent_tools,'validate_public_url',lambda u:u)
    r=agent_tools.AgentRuntime();url='https://example.org/lesson'
    first=asyncio.run(r.execute('sf_read_url',{'url':url}));assert '版本0' in first['text']
    assert '版本0' in asyncio.run(r.execute('sf_read_url',{'url':url}))['text'] and len(calls)==1
    assert '版本1' in asyncio.run(r.execute('sf_read_url',{'url':url,'refresh':True}))['text'] and len(calls)==2
    calls[-1].unlink()
    assert '版本2' in asyncio.run(r.execute('sf_read_url',{'url':url}))['text'] and len(calls)==3
