"""Dense fragments must not crowd chapters or displace exact source evidence."""
import hashlib
import math

import numpy as np
import pytest

from studyforge import library, library_semantic as semantic
from studyforge.db import execute, j, now
from test_library_retrieval import book, reading, snapshot


class QueryEncoder:
    def passages(self, row): return [('original',0,len(row['original_text']),row['original_text'])]
    def encode(self, texts, query=False): return np.asarray([[1,0] for _ in texts],dtype='<f4')


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(semantic,'model_ready',lambda:True)
    monkeypatch.setattr(semantic,'encoder',lambda:QueryEncoder())
    semantic.set_enabled(True)


def indexed(rid, page, text, score, fragments=1):
    for ordinal in range(fragments):
        start, end = ordinal*25, ordinal*25+25
        assert end<=len(text)
        vector=np.asarray([score,math.sqrt(1-score*score)],dtype='<f4')
        execute('INSERT INTO library_embeddings VALUES (?,?,?,?,?,?,?,?,?,?)',
            (rid,semantic.MODEL_KEY,page,ordinal,'original',start,end,hashlib.sha256(text[start:end].encode()).hexdigest(),2,vector.tobytes()))
    execute('INSERT INTO library_semantic_pages VALUES (?,?,?,?,?,?,?)',
        (rid,page,semantic.MODEL_KEY,hashlib.sha256(j([text,'']).encode()).hexdigest(),fragments,1,now()))


def test_one_long_page_cannot_fill_the_semantic_candidate_pool(tmp_path,model):
    b=book(tmp_path)
    text='dominant explanatory paragraph. '*80
    dominant,rd=reading(b,'长章节',{1:text})
    useful,ru=reading(b,'另一节的条件',{2:'A separate relevant condition belongs to another chapter.'})
    indexed(rd,1,text,.99,fragments=40)
    indexed(ru,2,'A separate relevant condition belongs to another chapter.',.96)
    hits,state=semantic.matches('query_alias',semantic.eligible(),limit=6)
    assert state=='used' and {h['reading_id'] for h in hits}=={rd,ru}
    assert len({(h['reading_id'],h['page']) for h in hits})==len(hits)
    found=library.search('query_alias',mode='hybrid')
    assert {n['node_id'] for n in found}=={dominant['id'],useful['id']}


def test_secondary_pages_in_same_chapter_survive_duplicate_passages(tmp_path,model):
    b=book(tmp_path)
    text='Repeated source explanation. '*90
    _,rid=reading(b,'章节',{1:text,2:text,3:text})
    for page,score in [(1,.99),(2,.97),(3,.95)]: indexed(rid,page,text,score,fragments=30 if page==1 else 1)
    hits,_=semantic.matches('query_alias',semantic.eligible(),limit=6)
    assert [h['page'] for h in hits]==[1,2,3]


def test_candidate_count_stays_bounded_and_scores_keep_order(tmp_path,model):
    b=book(tmp_path,8)
    pairs=[]
    for i in range(8):
        text='Independent authorized mathematical source. '*5
        _,rid=reading(b,'小节'+str(i),{i+1:text})
        indexed(rid,i+1,text,.99-i*.01,fragments=3)
        pairs.append(rid)
    hits,_=semantic.matches('query_alias',semantic.eligible(),limit=4)
    assert len(hits)==4 and [h['reading_id'] for h in hits]==pairs[:4]


def test_semantic_page_hits_cannot_displace_the_exact_condition_page(tmp_path):
    b=book(tmp_path,9)
    pages={i:'General related background. '+str(i) for i in range(1,10)}
    pages[8]='DEFINITION_CONTEXT: check the domain before using the following theorem.'
    pages[9]='EXACT_DOMAIN_CONDITION: the nonzero denominator assumption must be retained.'
    n,rid=reading(b,'条件与推导',pages)
    hits=[{'reading_id':rid,'page':p,'kind':'original','start_char':0,'end_char':len(pages[p]),
           'text_hash':hashlib.sha256(pages[p].encode()).hexdigest(),'semantic_score':.99-p*.01} for p in (3,4,5)]
    chunks=library.reference_chunks(rid,library.terms('EXACT_DOMAIN_CONDITION'),3,hits,scope=(1,9))
    returned={c['page'] for c in chunks}
    assert 9 in returned and 3 in returned and 8 in returned
    assert len(chunks)==3
    snap=snapshot(b,[n]);snap['references'][0]['semantic_hits']=hits
    result=library.reference_content(snap,'EXACT_DOMAIN_CONDITION',max_chars=5500)
    assert 'EXACT_DOMAIN_CONDITION' in result['text'] and 'DEFINITION_CONTEXT' in result['text']


@pytest.mark.parametrize('limit',[1,2,3])
def test_keyword_evidence_survives_semantic_candidates_at_small_page_budgets(tmp_path,limit):
    b=book(tmp_path)
    pages={1:'semantic related text',2:'semantic adjacent context',3:'exact_criterion required here'}
    _,rid=reading(b,'原文',pages)
    hits=[{'reading_id':rid,'page':p,'kind':'original','start_char':0,'end_char':len(pages[p]),
        'text_hash':hashlib.sha256(pages[p].encode()).hexdigest(),'semantic_score':.98} for p in (1,2)]
    result=library.reference_chunks(rid,library.terms('exact_criterion'),limit,hits,scope=(1,3))
    assert len(result)<=limit and 3 in {c['page'] for c in result}


def test_forged_semantic_hit_cannot_displace_source_or_broaden_scope(tmp_path):
    b=book(tmp_path)
    _,rid=reading(b,'已授权范围',{1:'keep_condition in scope',2:'outside the selected scope'})
    outside={'reading_id':rid,'page':2,'kind':'original','start_char':0,'end_char':len('outside the selected scope'),
        'text_hash':hashlib.sha256(b'outside the selected scope').hexdigest(),'semantic_score':1}
    wrong=dict(outside,page=1,text_hash='forged')
    result=library.reference_chunks(rid,library.terms('keep_condition'),3,[outside,wrong],scope=(1,1))
    assert [r['page'] for r in result]==[1] and result[0]['semantic_hits']==[]


def test_semantic_anchor_on_same_page_cannot_hide_an_exact_condition_near_its_end(tmp_path):
    b=book(tmp_path)
    text=('SEMANTIC_BACKGROUND: related general discussion.\n'*100)+'\nEXACT_BOUNDARY_ASSUMPTION: this theorem requires a nonzero divisor.\n'
    n,rid=reading(b,'长原页',{1:text})
    hit={'reading_id':rid,'page':1,'kind':'original','start_char':0,'end_char':45,
         'text_hash':hashlib.sha256(text[:45].encode()).hexdigest(),'semantic_score':.99}
    snap=snapshot(b,[n]);snap['references'][0]['semantic_hits']=[hit]
    result=library.reference_content(snap,'EXACT_BOUNDARY_ASSUMPTION',max_chars=1600)
    assert 'EXACT_BOUNDARY_ASSUMPTION' in result['text']
    span=result['evidence'][0]['original_excerpt']
    assert span['start_char']>3000 and 'EXACT_BOUNDARY_ASSUMPTION' in text[span['start_char']:span['end_char']]


def test_english_substring_does_not_override_a_valid_semantic_excerpt_location():
    text=('repeatedly rereading earlier material.\n'*200)+'\nSOURCE_TARGET: the actual relevant paragraph is here.\n'
    excerpt,meta=library.text_window(text,library.terms('eat'),600,anchor=text.index('SOURCE_TARGET'))
    assert 'SOURCE_TARGET' in excerpt and meta['start_char']>5000


@pytest.mark.parametrize('operation',['chat','generate'])
def test_native_tutor_and_docx_writer_receive_the_exact_condition_with_semantic_context(tmp_path,model,monkeypatch,operation):
    import asyncio
    import json
    import httpx
    from fastapi.testclient import TestClient
    from studyforge import conversations, server
    from studyforge.ai import save_settings
    from studyforge.db import create_job,create_project,many,one
    save_settings({'chat_provider':'deepseek','agent_tools_enabled':False,'agent_network_enabled':False,'background_learning_enabled':False})
    b=book(tmp_path,9)
    pages={i:'General source material for this definition. '*2 for i in range(1,10)}
    pages[8]='DEFINITION_CONTEXT: specify the domain first.'
    pages[9]='EXACT_DOMAIN_CONDITION: the denominator must be nonzero in this argument.'
    n,rid=reading(b,'适用条件',pages)
    for p in (3,4,5): indexed(rid,p,pages[p],.99-p*.01)
    other,_=reading(b,'不能混入的节',{2:'UNSELECTED_CHAPTER_BODY: another private topic.'})
    project=create_project('原生请求验证')
    chat=conversations.create(project['id'],'deepseek','fixture-model','none')
    library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    captured=[];native=httpx.AsyncClient
    def respond(request):
        captured.append(json.loads(request.content))
        answer='# 原文条件\n\n本次讲解除法要求除数非零。\n\n## 系统性总结\n\n条件应与结论一起使用。'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(respond)))
    if operation=='chat':
        response=TestClient(server.app).post('/api/chat/stream',json={'project_id':project['id'],
            'conversation_id':chat['id'],'source_ids':[],'provider':'deepseek','model':'fixture-model',
            'text':'EXACT_DOMAIN_CONDITION 是什么意思？只讲解，不出题。'})
        assert response.status_code==200 and '"error"' not in response.text,response.text
    else:
        library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
        # Generate a short project source, with this chapter as reference only.
        source=tmp_path/'lecture.txt';source.write_text('Explain EXACT_DOMAIN_CONDITION using the selected library reference.',encoding='utf-8')
        from studyforge.db import uid
        sid=uid();execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,project['id'],source.name,'.txt',str(source),'ready',now()))
        library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
        snap=library.reference_snapshot(chat['id'],project['id'],'EXACT_DOMAIN_CONDITION')
        context=library.reference_content(snap,'EXACT_DOMAIN_CONDITION')
        value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',
            model='fixture-model',reasoning_effort='none',generation_quality='custom',review_mode='express',format='docx',exercises=False,
            library_snapshot=snap,library_context=context['text'],library_evidence=library.reference_receipt(context))
        job=create_job(project['id'],'generate',value.model_dump())
        asyncio.run(server._generate_job(job,value))
        result=one('SELECT * FROM jobs WHERE id=?',(job,))
        assert result['status']=='completed',result['error']
        import zipfile
        artifact=many("SELECT * FROM artifacts WHERE kind='explanation'")[0]
        assert artifact['format']=='docx' and zipfile.is_zipfile(artifact['path'])
    assert len(captured)==1
    body=j(captured[0])
    assert 'the denominator must be nonzero in this argument' in body and 'DEFINITION_CONTEXT' in body
    assert 'UNSELECTED_CHAPTER_BODY' not in body and not many('SELECT * FROM exercise_sets')
