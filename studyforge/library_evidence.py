"""Small receipts for supplied library excerpts; never save original/note bodies."""
import hashlib

SCHEMA='library-reference-receipt-v1'
DOCUMENT_REFERENCE_LIMIT=6000
READING_KEYS=('id','provider','model','effort','vision_model','depth','focus','updated_at')
CANDIDATE_KEYS=('node_id','book_id','title','start_page','end_page','state')


def source(book,node,reading,reference,source_version):
    return {'node_id':node['id'],'book_id':book['id'],'book_title':book['title'],'title':node['title'],
        'purpose':reference['purpose'],'source_version':source_version,
        'scope':{key:node[key] for key in ('start_page','end_page','start_y','end_y')},
        'library_reading':{key:reading.get(key) for key in READING_KEYS},
        'included':False,'pages':[]}


def receipt(result):
    # Legacy/tool lookup results lack exact context metadata. Do not pretend
    # their current book state describes what a former request received.
    if 'sources' not in result:return {}
    text=result.get('text','')
    saved = {'schema':SCHEMA,'mode':result.get('mode'),'context_characters':len(text),
        'context_sha256':hashlib.sha256(text.encode()).hexdigest(),'context_limit':result.get('context_limit'),
        'truncated':bool(result.get('truncated')),'sources':result['sources'],
        'omitted_references':result.get('omitted_references',[]),
        'unread_candidates':[{key:row.get(key) for key in CANDIDATE_KEYS} for row in result.get('candidates',[])[:4]]}
    if result.get('input_kind')=='agent_library_read':
        saved.update(input_kind='agent_library_read',read_window={key:result.get('read_window',{}).get(key)
            for key in ('page','offset','limit','next_offset','total_characters')},
            image_rechecked=bool(result.get('image_rechecked')))
    return saved


def for_read_window(book,node,reading,reference,source_version,window,request,mode,image_rechecked=False):
    """Record prepared tool input, never relabel it from a later live directory."""
    item=source(book,node,reading,reference,source_version)
    pages=window.get('provided_pages',[])
    item.update(included=bool(pages),pages=pages,provided_context_characters=len(window['text']))
    evidence=[dict(page,node_id=node['id'],book_id=book['id'],book_title=book['title'],title=node['title']) for page in pages]
    return {'text':window['text'],'evidence':evidence,'candidates':[],'sources':[item],
        'mode':mode,'context_limit':request.limit,'truncated':bool(window.get('truncated')),
        'omitted_references':[] if pages else [node['id']],'input_kind':'agent_library_read',
        'read_window':{'page':request.page,'offset':request.offset,'limit':request.limit,
                       'next_offset':window['next_offset'],'total_characters':window.get('total_characters')},
        'image_rechecked':bool(image_rechecked)}


def validate(saved,text):
    if saved and (saved.get('schema')!=SCHEMA or saved.get('context_characters')!=len(text) or
                  saved.get('context_sha256')!=hashlib.sha256(text.encode()).hexdigest()):
        raise ValueError('书库参考记录与输入不一致，已停止生成；请重新发起任务')


def for_document(job_id,snapshot,query,text,saved,chapter_count):
    """Bound multi-chapter auxiliary context separately from reading-note cuts.

    The same frozen excerpt is sent to every chapter. Original chapter input
    stays complete; retry/resume reuses this local step without another lookup.
    """
    validate(saved,text)
    if chapter_count<2 or not saved or not (snapshot.get('references') or snapshot.get('candidates')):
        return {'text':text,'receipt':saved}
    from .db import execute,j,now,one,unj
    step=one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='library_document_reference'",(job_id,))
    if step:
        prepared=unj(step['response'])
        if prepared['prepared_context_sha256']!=saved['context_sha256']:
            raise ValueError('书库参考记录与输入不一致，已停止生成；请重新发起任务')
        validate(prepared['receipt'],prepared['text'])
        return prepared
    from .library import reference_content
    result=reference_content(snapshot,query,max_chars=DOCUMENT_REFERENCE_LIMIT)
    effective=receipt(result);effective['shared_chapter_count']=chapter_count
    prepared={'text':result['text'],'receipt':effective,'prepared_context_sha256':saved['context_sha256']}
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(job_id,'library_document_reference',j(prepared),now()))
    return prepared
