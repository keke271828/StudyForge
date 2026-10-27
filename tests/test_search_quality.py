import asyncio
from urllib.parse import parse_qs

import httpx

from studyforge.agent_tools import search_learning_web


def test_search_discards_irrelevant_and_prefers_learning_platform(monkeypatch):
    original=httpx.AsyncClient; queries=[]
    def response(request):
        query=parse_qs(request.url.query.decode())['q'][0];queries.append(query)
        preferred='site:zhihu.com' in query
        entries=[('Anime shop','https://example.org/anime','Watch anime'),('Noether theorem','https://www.zhihu.com/question/123','Noether symmetry and conservation')] if preferred else [('Noether paper','https://example.edu/paper','Noether theorem')]
        xml='<rss><channel>'+''.join(f'<item><title>{title}</title><link>{url}</link><description>{text}</description></item>' for title,url,text in entries)+'</channel></rss>'
        return httpx.Response(200,text=xml)
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(response)))
    result=asyncio.run(search_learning_web('Noether theorem',3))
    assert result['results'][0]['url'].startswith('https://www.zhihu.com/')
    assert len(result['results'])==2 and not any('Anime' in row['title'] for row in result['results'])
    assert len(queries)==3 and 'site:bilibili.com' in queries[1]


def test_irrelevant_feed_never_becomes_successful_verification(monkeypatch):
    original=httpx.AsyncClient
    xml='<rss><channel><item><title>Cars and movies</title><link>https://example.org/a</link><description>Unrelated text</description></item></channel></rss>'
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=xml))))
    result=asyncio.run(search_learning_web('相关与因果 共同原因',3))
    assert result['results']==[] and '不能声称已查证' in result['message']


def test_bilibili_course_search_runs_before_broad_search(monkeypatch):
    original = httpx.AsyncClient; queries = []
    def response(request):
        query = parse_qs(request.url.query.decode())['q'][0]; queries.append(query)
        entry = '<item><title>矩阵课程</title><link>https://www.bilibili.com/video/BV1xx411c7mD</link><description>矩阵线性代数</description></item>' if 'site:bilibili.com' in query else ''
        return httpx.Response(200, text='<rss><channel>' + entry + '</channel></rss>')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(response)))
    result = asyncio.run(search_learning_web('矩阵线性代数', 1))
    assert len(queries) == 2 and result['results'][0]['url'].startswith('https://www.bilibili.com/')


def test_exercise_search_obeys_disabled_network_before_any_request(monkeypatch):
    from studyforge.ai import save_settings
    from studyforge.exercises import search_exercises
    save_settings({'agent_network_enabled': False})
    def forbidden(*a, **kw): raise AssertionError('关闭联网后不得发出题源检索请求')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    assert asyncio.run(search_exercises('矩阵')) == []


def test_exercises_read_original_pages_instead_of_search_snippets(monkeypatch, tmp_path):
    from studyforge import agent_tools
    from studyforge.exercises import search_exercises
    calls = []; path = tmp_path / 'exercises.txt'; path.write_text('原网页题意：写出两种等价的论证。', encoding='utf-8')
    async def search(query, limit):
        return {'results': [{'title': '论证习题', 'url': 'https://www.zhihu.com/question/123', 'snippet': '未经核实的搜索片段'}]}
    def download(url, stem, **kwargs): calls.append((url, kwargs)); return path
    monkeypatch.setattr(agent_tools, 'search_learning_web', search)
    monkeypatch.setattr(agent_tools, 'validate_public_url', lambda url: url)
    monkeypatch.setattr(agent_tools, 'download_public_resource', download)
    result = asyncio.run(search_exercises('论证'))
    assert calls == [('https://www.zhihu.com/question/123', {'allow_video': False})]
    assert result[0]['body_read'] and '原网页题意' in result[0]['excerpt'] and '未经核实' not in result[0]['excerpt']
