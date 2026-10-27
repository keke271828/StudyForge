import asyncio
import json
import shutil
import socket
from http.cookiejar import CookieJar
from pathlib import Path

import httpx
import pytest

from studyforge import media, parsers, server, urls
from studyforge.config import temp_dir, files_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.video_links import canonical_video_url, embedded_video_url


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(urls.socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, 0, 0, '', ('93.184.215.14', 443))])


@pytest.mark.parametrize('value,result', [
    ('https://www.bilibili.com/video/BV13x41117TL?share_source=copy_web&p=3', 'https://www.bilibili.com/video/BV13x41117TL?p=3'),
    ('https://m.bilibili.com/video/av123', 'https://www.bilibili.com/video/av123?p=1'),
    ('https://player.bilibili.com/player.html?bvid=BV13x41117TL&page=2', 'https://www.bilibili.com/video/BV13x41117TL?p=2'),
    ('https://player.bilibili.com/player.html?aid=123&page=4', 'https://www.bilibili.com/video/av123?p=4'),
    ('https://b23.tv/test', 'https://b23.tv/test'),
    ('https://www.bilibili.com/read/cv123', None),
    ('https://bilibili.com.example.org/lesson', None),
    ('https://www.youtube.com/embed/exampleId', 'https://www.youtube.com/watch?v=exampleId'),
])
def test_video_identity_preserves_selected_part_and_excludes_articles(value, result):
    assert canonical_video_url(value) == result


def mock_page(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(urls.httpx, 'Client', lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def test_short_link_redirect_routes_to_video_not_page_text(tmp_path, monkeypatch, public_dns):
    calls = []
    downloaded = tmp_path / 'lesson.mp4'
    downloaded.write_bytes(b'fixture')
    def download(value, **kwargs):
        calls.append(value)
        return downloaded
    monkeypatch.setattr(urls, 'download_public_video', download)
    mock_page(monkeypatch, lambda request: httpx.Response(302, headers={'location': 'https://www.bilibili.com/video/BV13x41117TL?p=2'}))
    assert urls.download_public_resource('https://b23.tv/test', 'source') == downloaded
    assert calls == ['https://www.bilibili.com/video/BV13x41117TL?p=2']


def test_embedded_video_replaces_html_and_excludes_comments(tmp_path, monkeypatch, public_dns):
    markup = '<main><video><source src="/lecture.mp4"></video><p>简介非讲课内容</p></main><aside>推荐</aside><div id="comments">评论</div>'
    mock_page(monkeypatch, lambda request: httpx.Response(200, text=markup, headers={'content-type': 'text/html'}))
    calls = []
    downloaded = tmp_path / 'only-video.mp4'
    downloaded.write_bytes(b'fixture')
    def download(value, **kwargs): calls.append(value); return downloaded
    monkeypatch.setattr(urls, 'download_public_video', download)
    assert urls.download_public_resource('https://example.org/lesson', 'source') == downloaded
    assert calls == ['https://example.org/lecture.mp4']
    assert not list(temp_dir().glob('*.html'))


def test_failed_video_never_falls_back_to_webpage(monkeypatch, public_dns):
    def unavailable(*a, **k): raise RuntimeError('403')
    monkeypatch.setattr(urls, 'download_public_video', unavailable)
    with pytest.raises(urls.BrowserImportRequired, match='不会改用评论'):
        urls.download_public_resource('https://www.bilibili.com/video/BV13x41117TL', 'blocked')
    assert not list(temp_dir().glob('*.html'))


def test_dynamic_video_requires_browser_instead_of_importing_prose(monkeypatch, public_dns):
    mock_page(monkeypatch, lambda request: httpx.Response(200, text='<main><video src="blob:https://example.org/123"></video><p>无关文字</p></main>', headers={'content-type':'text/html'}))
    with pytest.raises(urls.BrowserImportRequired, match='动态视频'):
        urls.download_public_resource('https://example.org/lesson', 'blob')
    assert not list(temp_dir().glob('*.html'))


def test_video_in_recommendations_does_not_replace_the_main_article():
    present, target = embedded_video_url('<article>正文</article><aside><video src="/ad.mp4"></video></aside>', 'https://example.org/lesson')
    assert not present and target is None
    assert embedded_video_url('<article><iframe src="https://player.bilibili.com/player.html?bvid=BV13x41117TL"></iframe></article>', 'https://example.org/lesson')[1].endswith('?p=1')


def test_private_embedded_target_is_rejected(monkeypatch, public_dns):
    mock_page(monkeypatch, lambda request: httpx.Response(200, text='<video src="http://127.0.0.1/private.mp4"></video>', headers={'content-type':'text/html'}))
    with pytest.raises(ValueError, match='内网'):
        urls.download_public_resource('https://example.org/lesson', 'private')


@pytest.mark.parametrize('mime,body',[('text/html','<video src="/lecture.mp4"></video><p>无关文字</p>'),('video/mp4','video-data')])
def test_disabled_autonomous_video_permission_blocks_embedded_and_mime(monkeypatch,public_dns,mime,body):
    mock_page(monkeypatch,lambda request:httpx.Response(200,text=body,headers={'content-type':mime}))
    def forbidden(*a,**kw): pytest.fail('Permission was bypassed')
    monkeypatch.setattr(urls,'download_public_video',forbidden)
    with pytest.raises(PermissionError,match='未勾选'):
        urls.download_public_resource('https://example.org/lesson','blocked',allow_video=False)


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / 'clip.mp4'
    media.run_ffmpeg('-f', 'lavfi', '-i', 'color=c=white:s=320x180:d=1', '-f', 'lavfi', '-i',
                     'sine=frequency=440:duration=1', '-shortest', '-c:v', 'mpeg4', '-c:a', 'aac', str(path))
    return path


def test_download_uses_audio_merge_and_scoped_cookies_then_keeps_only_video_subtitles(clip, monkeypatch, public_dns):
    captured = {}
    class Downloader:
        def __init__(self, opts): self.opts=opts; self.cookiejar=CookieJar(); captured['options']=opts
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def extract_info(self, url, download):
            captured['cookies']=list(self.cookiejar)
            self.path=Path(self.opts['outtmpl']).parent / 'id.mp4'
            shutil.copyfile(clip, self.path)
            captions=self.path.with_suffix('.zh.json')
            captions.write_text(json.dumps({'body':[{'from':0,'to':1,'content':'真实视频知识点'}]}), encoding='utf-8')
            self.opts['postprocessor_hooks'][0]({'status':'finished','info_dict':{'filepath':str(self.path)}})
            return {'id':'id','title':'视频课程','acodec':'aac','duration':1,
                    'requested_subtitles':{'zh-CN':{'filepath':str(captions)}}}
        def prepare_filename(self, info): return str(self.path.with_suffix('.webm'))
    import yt_dlp
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', Downloader)
    path = media.download_public_video('https://www.bilibili.com/video/BV13x41117TL?p=1',
          cookies=[{'domain':'.bilibili.com','name':'SESSDATA','value':'private-login'},
                   {'domain':'.example.org','name':'unrelated','value':'another-private-login'}])
    assert '+' in captured['options']['format'] and Path(captured['options']['ffmpeg_location']).is_file()
    assert captured['options']['getcomments'] is False
    assert [cookie.name for cookie in captured['cookies']] == ['SESSDATA']
    assert 'private-login' not in media.video_metadata_path(path).read_text(encoding='utf-8')
    monkeypatch.setattr(parsers, 'parse_audio', lambda *_: pytest.fail('有效字幕无需重复语音识别'))
    monkeypatch.setattr(parsers, 'video_frames', lambda *_: [])
    parts=parsers.parse_video(path)
    assert parts[0]['text']=='真实视频知识点' and parts[0]['meta']['method']=='video_subtitle'


@pytest.mark.parametrize('extension,body', [
    ('srt', '1\n00:00:01,000 --> 00:00:03,500\n<b>视频内容</b>\n\n'),
    ('vtt', 'WEBVTT\n\n00:01.000 --> 00:03.500\n视频内容\n\n'),
    ('json3', json.dumps({'events':[{'tStartMs':1000,'dDurationMs':2500,'segs':[{'utf8':'视频内容'}]}]})),
])
def test_timed_caption_formats(tmp_path, extension, body):
    path=tmp_path / ('subtitle.'+extension)
    path.write_text(body, encoding='utf-8')
    assert media._caption_segments(path)==[dict(start=1,end=3.5,text='视频内容')]


def test_browser_video_import_ignores_html_and_never_persists_credentials(clip, monkeypatch, public_dns):
    calls=[]
    def download(url, stem, **kwargs): calls.append(kwargs); return clip
    monkeypatch.setattr(server, 'download_public_resource', download)
    monkeypatch.setattr(server, 'parse_file', lambda *_:[dict(locator='0-1 秒',text='视频课堂',kind='transcript',meta={})])
    project=create_project('视频学习')
    value=server.BrowserPageIn(project_id=project['id'],url='https://www.bilibili.com/video/BV13x41117TL',
                              html='<article>评论和推荐不得进入学习资料</article>',cookies=[{'domain':'.bilibili.com','name':'SESSDATA','value':'credential'}])
    async def run():
        result=await server.import_browser_page(value)
        await asyncio.gather(*(task for task in asyncio.all_tasks() if task is not asyncio.current_task()))
        return result
    result=asyncio.run(run())
    row=one('SELECT * FROM sources WHERE id=?',(result['source_id'],))
    assert result['kind']=='video' and row['status']=='ready' and row['kind']=='.sfvideo'
    assert '评论' not in row['segments_json']
    assert calls[0]['cookies'][0]['value']=='credential'
    assert 'credential' not in json.dumps(many('SELECT * FROM jobs'))
    assert not list(files_dir().glob('*.html'))
