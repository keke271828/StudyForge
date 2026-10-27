"""Bounded per-chat lookup navigation. Never injected into learner profiles or prompts."""
from . import library
from .db import connect,j,now,uid,unj

LIMIT=30


def owner(db,conversation_id,project_id):
    row=db.execute('SELECT project_id FROM conversations WHERE id=?',(conversation_id,)).fetchone()
    if not row or row['project_id']!=project_id:raise ValueError('对话与项目不匹配')


def record(conversation_id,project_id,query,result):
    evidence=result.get('evidence',[]);candidates=result.get('candidates',[])
    groups={};receipt=library.reference_receipt(result)
    supplied={source['node_id']:source for source in receipt.get('sources',[])}
    omitted=[source for source in supplied.values() if not source['included']]
    if not evidence and not candidates and not omitted:return None
    with connect() as db:
        db.execute('BEGIN IMMEDIATE');owner(db,conversation_id,project_id)
        for kind,items in (('original',evidence),('candidate',candidates),('omitted',omitted)):
            for item in items:
                ident=item.get('node_id')
                if not ident:continue
                if ident not in groups:
                    if len(groups)>=24:continue
                    source=supplied.get(ident)
                    if source:
                        # The receipt is the prepared input, even if the live
                        # node was renamed, resized or deleted in the meantime.
                        metadata={key:source[key] for key in ('node_id','book_id','book_title','title','source_version')}
                    else:
                        n=db.execute('SELECT * FROM library_nodes WHERE id=?',(ident,)).fetchone()
                        if not n:continue
                        b=db.execute('SELECT * FROM library_books WHERE id=?',(n['book_id'],)).fetchone()
                        if not b:continue
                        metadata={'node_id':ident,'book_id':b['id'],'book_title':b['title'],'title':n['title'],
                                  'source_version':library.version(dict(b),dict(n))}
                    groups[ident]={**metadata,'kind':kind,'pages':[]}
                hit=groups[ident]
                if kind=='original':hit['kind']='original'
                if type(item.get('page')) is int and item['page'] not in hit['pages'] and len(hit['pages'])<8:
                    hit['pages'].append(item['page'])
        if not groups:return None
        payload={'nodes':list(groups.values()),'truncated':bool(result.get('truncated'))}
        if receipt:payload['receipt']=receipt
        ident=uid();created=now()
        db.execute('INSERT INTO conversation_library_history VALUES (?,?,?,?,?)',
            (ident,conversation_id,str(query)[:280],j(payload),created))
        db.execute('DELETE FROM conversation_library_history WHERE conversation_id=? AND id NOT IN '
            '(SELECT id FROM conversation_library_history WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?)',
            (conversation_id,conversation_id,LIMIT))
    return {'id':ident,'created_at':created,'query':str(query)[:280],**payload}


def history(conversation_id,project_id):
    with connect() as db:
        owner(db,conversation_id,project_id)
        rows=db.execute('SELECT * FROM conversation_library_history WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?',
            (conversation_id,LIMIT)).fetchall()
        entries=[{'id':r['id'],'created_at':r['created_at'],'query':r['query'],**unj(r['payload_json'],{})} for r in rows]
        # Status-only restoration does not load large notes or original page bodies.
        wanted={hit['node_id'] for entry in entries for hit in entry['nodes']}
        nodes={r['id']:dict(r) for r in db.execute('SELECT * FROM library_nodes WHERE id IN ('+
            ','.join('?' for _ in wanted)+')',tuple(wanted))} if wanted else {}
        book_ids={n['book_id'] for n in nodes.values()}
        books={r['id']:dict(r) for r in db.execute('SELECT id,sha256 FROM library_books WHERE id IN ('+
            ','.join('?' for _ in book_ids)+')',tuple(book_ids))} if book_ids else {}
        for entry in entries:
            for hit in entry['nodes']:
                n=nodes.get(hit['node_id']);hit['available']=bool(n)
                hit['scope_changed']=bool(n and library.version(books[n['book_id']],n)!=hit['source_version'])
        return {'entries':entries,'limit':LIMIT}


def clear(conversation_id,project_id):
    with connect() as db:
        owner(db,conversation_id,project_id)
        db.execute('DELETE FROM conversation_library_history WHERE conversation_id=?',(conversation_id,))
    return {'cleared':True}
