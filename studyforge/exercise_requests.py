"""Route explicit requests for new practice to the answer-gated workflow."""
import re


def wants_exercises(text):
    if re.search(r'(?:不|别|不要|无需).{0,5}(?:出题|布置习题|生成习题)', text): return False
    if re.search(r'^(?:如何|为什么|怎么).{0,10}(?:出题|布置习题)', text.strip()): return False
    return bool(re.search(r'(?:布置|生成|安排).{0,20}(?:习题|练习题|题目|作业|题单)|(?:给我|帮我|请).{0,15}出题|^出题|'
                         r'(?:给|出|来).{0,12}(?:\d+|[一二两三四五六七八九十几]).{0,4}(?:道|个)?题|'
                         r'(?:give|create|generate|assign).{0,30}(?:exercises|questions|problems|quiz|homework)|quiz me|test me', text, re.I))


def asks_for_answers(text):
    if re.search(r'(?:不|别|不要|无需).{0,5}(?:答案|解析|解答|参考代码)', text): return False
    return bool(re.search(r'答案|参考(?:代码|实现)|第.{0,4}题.{0,10}(?:怎么|如何|求解)|'
                          r'(?:习题|题目|题单|这道|刚才|这些).{0,15}(?:解析|解答)|'
                          r'(?:解析|解答).{0,15}(?:习题|题目|题单|这道|刚才|这些)|^\s*(?:解析|解答)\s*[。！!]?\s*$|'
                          r'(?:solve|solution|answer).{0,15}(?:question|problem|exercise)|show.{0,15}(?:answers|solutions)', text, re.I))


def pending_sets(conversation_id, source_ids=()):
    from .db import many, unj
    # Guard this chat's assignments and explicitly selected exercise files,
    # including when that file is discussed in another chat.
    placeholders=','.join('?' for _ in source_ids)
    scope="json_extract(a.metadata_json,'$.conversation_id')=?"
    if source_ids:
        scope+=f' OR a.id IN (SELECT artifact_id FROM artifact_sources WHERE source_id IN ({placeholders}))'
    rows = many("SELECT e.id,e.title,e.questions_json FROM exercise_sets e JOIN artifacts a "
                "ON json_extract(a.metadata_json,'$.exercise_set_id')=e.id "
                "WHERE e.status='assigned' AND ("+scope+")", (conversation_id,*source_ids))
    from .homework import answers_released
    from .db import one
    return {row['id']:dict(id=row['id'], title=row['title'], questions=unj(row['questions_json'],[])) for row in rows
            if not answers_released(one('SELECT * FROM exercise_sets WHERE id=?',(row['id'],)))}
