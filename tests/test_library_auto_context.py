"""Weak pedagogical/book-name hits should not become automatic source context."""
import hashlib

import pytest

from studyforge import library,library_semantic as semantic
from studyforge.db import execute
from test_global_library import chat
from test_library_retrieval import book,reading


GENERIC='这里为什么不成立？请用一个具体情形解释，只讲这个卡点，不布置习题。'


def auto(b):
    p,c=chat();library.set_preferences(c,p['id'],'auto',[])
    return p,c


@pytest.mark.parametrize('query,noise',[
    (GENERIC,'两个条件成立，其他情形也有具体例子。'),
    ('这一步为什么成立？能详细说清楚吗？','下面逐步说清楚这个例子为何成立。'),
    ('Why does this proof work? Explain with concrete examples.','This proof has concrete examples and a detailed explanation.')])
def test_discourse_only_hits_remain_searchable_but_not_automatic_background(tmp_path,query,noise):
    b=book(tmp_path);n,_=reading(b,'普通说明',{1:noise});p,c=auto(b)
    assert library.search(query,mode='keyword')
    snap=library.reference_snapshot(c,p['id'],query)
    assert snap['references']==[] and snap['candidates']==[]


def test_quoted_concept_retains_its_source_without_other_proofs_or_causal_examples(tmp_path):
    b=book(tmp_path)
    target,_=reading(b,'高斯定律',{1:'TARGET_GAUSS：高斯定律约束净电通量，闭合曲面总电荷为零不等于电场处处为零。'})
    reading(b,'极限唯一性',{2:'PROOF_NOISE：两个条件成立时，由此得到矛盾。'})
    reading(b,'因果推断',{3:'CAUSAL_NOISE：要说清楚具体情形，其他条件也很重要。'})
    p,c=auto(b);query=GENERIC+'\n高斯定律中总电荷为零，所以内部电场处处为零。'
    snap=library.reference_snapshot(c,p['id'],GENERIC,retrieval_query=query)
    assert [r['node_id'] for r in snap['references']]==[target['id']]
    context=library.reference_content(snap,query)['text']
    assert 'TARGET_GAUSS' in context and all(x not in context for x in ('PROOF_NOISE','CAUSAL_NOISE'))


def test_book_name_only_does_not_import_every_sibling_or_unread_directory(tmp_path):
    b=book(tmp_path);execute('UPDATE library_books SET title=? WHERE id=?',('高等代数',b['id']))
    target,_=reading(b,'线性相关',{1:'TARGET_LINEAR：线性相关意味着存在不全为零的系数使线性组合为零。'})
    other,_=reading(b,'多项式',{2:'BOOK_ONLY_NOISE：整除的定义。'})
    unread=library.add_node(b['id'],'行列式');p,c=auto(b)
    found=library.search('高等代数 线性相关',mode='keyword')
    assert {r['node_id'] for r in found}>={target['id'],other['id'],unread['id']}
    snap=library.reference_snapshot(c,p['id'],'高等代数 线性相关')
    assert [r['node_id'] for r in snap['references']]==[target['id']] and not snap['candidates']
    assert not library.reference_snapshot(c,p['id'],'高等代数')['references']


def test_filtering_precedes_candidate_limit_so_generic_headings_cannot_crowd_target(tmp_path):
    b=book(tmp_path);target,_=reading(b,'相关小节',{1:'TARGET: 高斯定律约束净通量。'})
    for i in range(9):reading(b,('成立具体情形'*14)+str(i),{2:'一个具体情形，两个条件成立。'})
    p,c=auto(b);query=GENERIC+' 高斯定律'
    assert target['id'] not in {n['node_id'] for n in library.search(query,limit=6,mode='keyword')}
    snap=library.reference_snapshot(c,p['id'],query)
    assert [r['node_id'] for r in snap['references']]==[target['id']]


@pytest.mark.parametrize('layer',['original','visual','notes'])
def test_specific_concept_in_any_existing_search_layer_is_retained(tmp_path,layer):
    b=book(tmp_path);payload={'notes':'','visual':''};raw='Generic background.'
    if layer=='original':raw='TARGET: 规训权力可通过检查与规范化运作。'
    else:payload[layer]='TARGET: 规训权力可通过检查与规范化运作。'
    n,_=reading(b,'概念说明',{1:raw},**payload);p,c=auto(b)
    snap=library.reference_snapshot(c,p['id'],'规训权力是什么意思？')
    assert [r['node_id'] for r in snap['references']]==[n['id']]


def test_specific_lower_page_is_not_lost_when_two_generic_pages_rank_higher(tmp_path):
    b=book(tmp_path);n,_=reading(b,'页内说明',{1:'具体情形成立'*200,2:'具体情形成立'*200,3:'TARGET: 单射映射的定义。'})
    p,c=auto(b);query=GENERIC+' 单射'
    snap=library.reference_snapshot(c,p['id'],query)
    assert [r['node_id'] for r in snap['references']]==[n['id']]
    assert 'TARGET' in library.reference_content(snap,query)['text']


def test_multiple_fields_share_real_mechanism_without_forced_single_topic(tmp_path):
    b=book(tmp_path)
    physics,_=reading(b,'楞次定律',{1:'负反馈：楞次定律的感应电流效应阻碍引起感应的磁通变化。'})
    biology,_=reading(b,'稳态调节',{2:'负反馈：反馈作用减小受控量相对设定状态的偏差。'})
    reading(b,'证明写法',{3:'请看具体例子，两个条件成立。'});p,c=auto(b)
    snap=library.reference_snapshot(c,p['id'],'负反馈中，楞次定律与生物稳态调节有哪些结构关联？')
    assert {r['node_id'] for r in snap['references']}=={physics['id'],biology['id']}


@pytest.mark.parametrize('mode',['auto','manual'])
def test_explicit_references_remain_even_when_match_is_only_generic(tmp_path,mode):
    b=book(tmp_path);n,_=reading(b,'我明确选择的章节',{1:'MANUAL_SOURCE：两个条件成立。'})
    p,c=chat();library.set_preferences(c,p['id'],mode,[{'node_id':n['id'],'purpose':'primary'}])
    snap=library.reference_snapshot(c,p['id'],GENERIC)
    assert [r['node_id'] for r in snap['references']]==[n['id']]
    assert 'MANUAL_SOURCE' in library.reference_content(snap,GENERIC)['text']


def test_unread_specific_title_is_still_a_candidate_without_body(tmp_path):
    b=book(tmp_path);n=library.add_node(b['id'],'单射与满射');p,c=auto(b)
    snap=library.reference_snapshot(c,p['id'],'单射是什么意思？')
    assert not snap['references'] and [r['node_id'] for r in snap['candidates']]==[n['id']]


@pytest.mark.parametrize('query,score,expected',[
    ('different inputs never produce the same output',.92,True),
    ('different inputs never produce the same output',.85,False),
    ('这里为什么成立？请解释',.98,False)])
def test_semantic_paraphrase_keeps_threshold_but_discourse_is_not_a_topic(tmp_path,monkeypatch,query,score,expected):
    b=book(tmp_path);raw='两个条件成立。';n,rid=reading(b,'单射',{1:raw});p,c=auto(b)
    hit={'reading_id':rid,'page':1,'ordinal':0,'kind':'original','start_char':0,'end_char':len(raw),
         'text_hash':hashlib.sha256(raw.encode()).hexdigest(),'semantic_score':score}
    semantic.set_enabled(True);monkeypatch.setattr(semantic,'matches',lambda *a:([hit],'used'))
    snap=library.reference_snapshot(c,p['id'],query)
    assert bool(snap['references']) is expected


def test_suspect_navigation_note_cannot_create_specific_auto_match(tmp_path):
    from studyforge.library_annotations import save
    b=book(tmp_path);n,rid=reading(b,'普通小节',{1:'成立。'},notes='规训权力')
    save(n['id'],rid,True,'',0)
    p,c=auto(b);assert not library.reference_snapshot(c,p['id'],'规训权力为什么成立？')['references']


@pytest.mark.parametrize('concept',['机器学习','证明论','条件概率','控制论','形而上学','范畴论'])
def test_named_concepts_are_not_stripped_as_teaching_language(tmp_path,concept):
    b=book(tmp_path);n,_=reading(b,'专有概念',{1:'TARGET: '+concept+'的定义与适用范围。'});p,c=auto(b)
    snap=library.reference_snapshot(c,p['id'],concept+'是什么？请用具体例子说明。')
    assert [ref['node_id'] for ref in snap['references']]==[n['id']]


@pytest.mark.parametrize('mode',['auto','manual'])
def test_discourse_does_not_displace_late_definition_page_within_selected_node(tmp_path,mode):
    b=book(tmp_path,9)
    pages={page:'具体情形成立。'*300 for page in range(1,10)}
    pages[8]='PREREQUISITE: the exact original hypothesis.'
    pages[9]='TARGET_INJECTIVE: 单射是不同输入不会产生相同输出。'
    n,_=reading(b,'九页讨论',pages);p,c=chat()
    library.set_preferences(c,p['id'],mode,[{'node_id':n['id'],'purpose':'reference'}] if mode=='manual' else [])
    query=GENERIC+' 单射'
    snap=library.reference_snapshot(c,p['id'],query)
    value=library.reference_content(snap,query,max_chars=2200)
    assert 'TARGET_INJECTIVE' in value['text'] and 'PREREQUISITE' in value['text']
    assert len(value['text'])<=2200 and {e['page'] for e in value['evidence']}>={8,9}


@pytest.mark.parametrize('query',['这里为什么成立？请解释。','Why does this proof work? Explain with concrete examples.'])
def test_generic_automatic_lookup_skips_note_corpus_and_local_model(tmp_path,monkeypatch,query):
    b=book(tmp_path);reading(b,'普通章节',{1:'成立。'},notes='large note '*10000);p,c=auto(b)
    monkeypatch.setattr(library,'eligible_readings',lambda *a,**kw:pytest.fail('generic auto query must not walk stored notes'))
    monkeypatch.setattr(semantic,'matches',lambda *a,**kw:pytest.fail('generic auto query must not load the semantic model'))
    assert not library.reference_snapshot(c,p['id'],query)['references']
