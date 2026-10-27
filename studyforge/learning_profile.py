"""User-controlled teaching memory. Source evidence and actual grades stay immutable."""
from __future__ import annotations

import math
import re
from datetime import datetime,timezone

from .db import connect, execute, j, many, now, one, unj


class ProfileConflict(ValueError):
    pass


DELETED = '(CASE WHEN (f.eligible=0 OR v.eligible=0) AND COALESCE(c.version,0)=0 THEN 1 ELSE COALESCE(c.deleted,0) END)'
PROFILE_SELECT = f'''SELECT i.*,i.observation AS original_observation,i.confidence AS original_confidence,
    c.correction,{DELETED} AS deleted,COALESCE(c.version,0) AS version,
    CASE WHEN v.eligible=0 THEN 1 ELSE 0 END AS external_evidence,
    COALESCE(c.updated_at,i.created_at) AS updated_at,
    e.project_id,e.conversation_id,e.kind AS evidence_kind,e.created_at AS evidence_recorded_at,e.payload_json,p.name AS project_name
    FROM learning_insights i JOIN learning_events e ON e.id=i.event_id
    LEFT JOIN learning_insight_controls c ON c.insight_id=i.id
    LEFT JOIN learning_event_filters f ON f.event_id=e.id
    LEFT JOIN learning_insight_evidence_filters v ON v.insight_id=i.id
    LEFT JOIN projects p ON p.id=e.project_id'''

CATEGORY = '''CASE WHEN e.kind IN ('做题','费曼讲解','编程作业') THEN 'assessment'
    WHEN i.kind='self_report' OR e.kind='自评' THEN 'self_report'
    WHEN i.kind='exposure' THEN 'exposure'
    WHEN i.kind IN ('preference','strategy') THEN 'preference' ELSE 'chat' END'''


def public_insight(row: dict) -> dict:
    row = dict(row)
    payload = unj(row.pop('payload_json'), {})
    row['anchors'] = unj(row.pop('anchors_json'), [])
    for key in ('message_id', 'reading_id', 'questionnaire_id'):
        row[key] = payload.get(key)
    row['source_ids'] = payload.get('source_ids', [])
    row['deleted'] = bool(row['deleted'])
    row['external_evidence'] = bool(row['external_evidence'])
    if row['correction'] is not None:
        row['observation'] = row['correction']
        row['confidence'] = '用户纠正（未验证）'
    row['category'] = ('assessment' if row['evidence_kind'] in ('做题', '费曼讲解', '编程作业') else
                       'self_report' if row['kind'] == 'self_report' or row['evidence_kind'] == '自评' else
                       'exposure' if row['kind'] == 'exposure' else
                       'preference' if row['kind'] in ('preference', 'strategy') else 'chat')
    return row


def list_insights(search='', category='all', status='active', offset=0, limit=100) -> dict:
    from .learning_memory import filter_existing_events
    filter_existing_events()
    clauses = [DELETED+'=?']
    args = [int(status == 'removed')]
    if search:
        clauses.append("instr(lower(i.topic||' '||COALESCE(c.correction,i.observation)||' '||i.quote),lower(?))>0")
        args.append(search)
    if category != 'all':
        clauses.append(CATEGORY + '=?')
        args.append(category)
    sql = PROFILE_SELECT + ' WHERE ' + ' AND '.join(clauses)
    count = one('SELECT COUNT(*) AS n FROM (' + sql + ')', tuple(args))['n']
    rows = many(sql + ' ORDER BY COALESCE(c.updated_at,i.created_at) DESC,i.id DESC LIMIT ? OFFSET ?',
                tuple(args + [limit, offset]))
    return {'insights': [public_insight(row) for row in rows], 'filtered_count': count,
            'offset': offset, 'limit': limit, 'status': status,
            'total_insights': one('SELECT COUNT(*) AS n FROM ('+PROFILE_SELECT+') WHERE deleted=0')['n']}


def insight_evidence(insight_id: int) -> dict:
    from .learning_memory import filter_existing_events
    filter_existing_events()
    row = one(PROFILE_SELECT + ' WHERE i.id=?', (insight_id,))
    if not row:
        raise LookupError('画像记录不存在')
    payload = unj(row['payload_json'], {})
    item = public_insight(row)
    # Whitelist student evidence. Do not expose an event's arbitrary payload,
    # mentor_context, tool history, private reference solution or rubric.
    basis = str(payload.get('student_text') or payload.get('reading_text') or payload.get('source_name') or '')
    if item['message_id'] and item['conversation_id']:
        message = one("SELECT content FROM messages WHERE id=? AND conversation_id=? AND role='user'",
                      (item['message_id'], item['conversation_id']))
        if message:
            basis = message['content']
    exclusion=('这条判断引用的文字位于题干、原文或其他明确引用中，已暂时移出教学画像；原消息和判断保留，可核对后恢复。'
               if item['external_evidence'] and item['deleted'] and item['version']==0 else '')
    return {'insight': item, 'evidence_text': basis[:24000], 'truncated': len(basis) > 24000,
            'feedback': str(payload.get('feedback') or '')[:600], 'recorded_score': _score(payload.get('score')),
            'sources': [source for sid in item['source_ids']
                        if (source := one('SELECT id,name FROM sources WHERE id=?', (sid,)))],
            'notice': exclusion+'原话和原评估保留不变。用户纠正是当前自述，不自动验证能力；聊天片段、通读或一次评分不能证明稳定掌握。'}


def change_insight(insight_id: int, expected_version: int, *, correction=..., deleted=None) -> dict:
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        stored = database.execute(PROFILE_SELECT + ' WHERE i.id=?', (insight_id,)).fetchone()
        if not stored:
            raise LookupError('画像记录不存在')
        row = dict(stored)
        if row['version'] != expected_version:
            raise ProfileConflict('这条记录已在其他操作中更新，请重新查看后再保存；你的填写内容仍保留。')
        if row['deleted'] and deleted is not False:
            raise ProfileConflict('这条记录已移出画像，请先恢复再纠正。')
        replacement = row['correction'] if correction is ... else correction
        if replacement is not None:
            replacement = replacement.strip()
            if not replacement or len(replacement) > 1000:
                raise ValueError('纠正内容需为 1—1000 个字符')
        removed = bool(row['deleted']) if deleted is None else deleted
        timestamp = now()
        database.execute('INSERT INTO learning_insight_controls VALUES (?,?,?,?,?) ON CONFLICT(insight_id) DO UPDATE SET '
                         'correction=excluded.correction,deleted=excluded.deleted,version=excluded.version,updated_at=excluded.updated_at',
                         (insight_id, replacement, int(removed), row['version'] + 1, timestamp))
        # Do not let a retry/inflight background result reinterpret the same evidence.
        # Other existing insights on that event remain independently editable.
        database.execute('INSERT OR IGNORE INTO learning_event_profile_blocks VALUES (?,?)', (row['event_id'], timestamp))
        database.execute("UPDATE learning_events SET status='completed',updated_at=? WHERE id=? AND status IN ('pending','running')",
                         (timestamp, row['event_id']))
        result = dict(database.execute(PROFILE_SELECT + ' WHERE i.id=?', (insight_id,)).fetchone())
    return public_insight(result)


def relevant_insights(relevance: str, removed=False) -> list[dict]:
    return [public_insight(row) for row in many(PROFILE_SELECT + ' WHERE '+DELETED+'''=? AND (
        (i.kind='preference' AND json_array_length(i.anchors_json)=0) OR instr(?,i.topic)>0 OR EXISTS
        (SELECT 1 FROM json_each(i.anchors_json) WHERE instr(?,value)>0))
        ORDER BY COALESCE(c.updated_at,i.created_at) DESC,i.id DESC LIMIT 100''', (int(removed), relevance, relevance))]


def exclusions_context(relevance: str) -> str:
    removed = relevant_insights(relevance, removed=True)
    labels = list(dict.fromkeys(f"{row['topic']}（{row['evidence_kind']}，{row['created_at'][:10]}）" for row in removed))[:8]
    legacy = many('SELECT topic FROM legacy_profile_exclusions WHERE instr(?,topic)>0 LIMIT 8', (relevance,))
    labels += [row['topic'] + '（早期汇总）' for row in legacy]
    return ('\n当前不采用的画像记录（用户移出或证据归属不符）：' + '、'.join(labels) + '。这些记录不再用于当前教学评估；'
            '历史对话或既有文档中的相应判断、评分不作为当前画像，不因旧证据重建；新的作答可产生新证据。'
            '这不限制读取当前选中资料或解释其知识。\n') if labels else ''


def profile_revision() -> str:
    from .learning_voice import VERSION
    row = one('SELECT COALESCE(SUM(version),0) AS revision FROM learning_insight_controls')
    # Both removing and restoring a legacy summary must invalidate paused snapshots.
    exclusions = many('SELECT topic,created_at FROM legacy_profile_exclusions ORDER BY topic')
    epoch = one("SELECT value FROM workspace_state WHERE key='profile_epoch'")
    return str(row['revision']) + ':' + repr(exclusions) + ':' + repr(scoring_settings()) + ':' + str(epoch) + ':evidence-'+str(VERSION)


def generation_profile(job_id: str) -> list[dict]:
    """Reuse a job's score snapshot until the student changes profile controls."""
    revision = profile_revision()
    saved = one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='mastery_snapshot'", (job_id,))
    version = one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='profile_revision'", (job_id,))
    if saved and version and version['response'] == revision:
        return unj(saved['response'])
    result = effective_profile()
    with connect() as database:
        for key, response in [('mastery_snapshot', j(result)), ('profile_revision', revision)]:
            database.execute('INSERT INTO generation_steps VALUES (?,?,?,?) ON CONFLICT(job_id,step_key) '
                             'DO UPDATE SET response=excluded.response,created_at=excluded.created_at', (job_id, key, response, now()))
    return result


def removed_legacy_profiles() -> list[dict]:
    return many('SELECT m.topic,m.quiz_score,m.feynman_score,m.self_rating,x.created_at '
                'FROM legacy_profile_exclusions x JOIN mastery m ON m.topic=x.topic ORDER BY x.created_at DESC')


def change_legacy_profile(topic: str, removed: bool) -> dict:
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        if not database.execute('SELECT 1 FROM mastery WHERE topic=?', (topic,)).fetchone():
            raise LookupError('早期汇总不存在')
        if removed:
            database.execute('INSERT OR IGNORE INTO legacy_profile_exclusions VALUES (?,?)', (topic, now()))
        else:
            database.execute('DELETE FROM legacy_profile_exclusions WHERE topic=?', (topic,))
    return {'topic': topic, 'removed': removed}


def _score(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None


AID_LABELS={'assisted':'记录到软件提示或学生自报参考笔记',
            'reported_no_aids':'未记录软件提示、学生自报未查笔记（非独立性验证）','unknown':'帮助条件未完整记录'}


def _event_time(value):
    try:
        result=datetime.fromisoformat(value)
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError,OverflowError):return None


def _recent_assessment(event,payload,score):
    """Only numeric evidence and conditions may cross conversation boundaries."""
    context=payload.get('practice_context');aid='unknown';delay=None;version_verified=None
    if isinstance(context,dict):
        levels=context.get('hint_levels');index=str(context.get('question_index',0))
        level=levels.get(index,0) if isinstance(levels,dict) else None
        if level or context.get('used_notes') is True:aid='assisted'
        elif isinstance(levels,dict) and context.get('used_notes') is False and context.get('recording_status') not in ('partial','not_recorded'):
            aid='reported_no_aids'
        if context.get('is_review') is True and isinstance(context.get('timing'),list):
            timing=next((x for x in context['timing'] if isinstance(x,dict) and str(x.get('question_index'))==index),{})
            value=timing.get('delay_hours')
            if type(value) in (int,float) and math.isfinite(value) and value>=0:delay=value
            version_verified=timing.get('same_question_verified') is True
        elif context.get('is_review') is True:version_verified=False
    return {'kind':event['kind'],'score':score,'recorded_at':event['created_at'] if _event_time(event['created_at']) else None,
            'aid_status':aid,'is_review':isinstance(context,dict) and context.get('is_review') is True,'delay_hours':delay,
            'same_question_verified':version_verified}


def recent_assessment_text(row):
    records=row.get('recent_assessments',[])[:3]
    if not records:return ''
    return '；近期评估（新→旧）：'+'；'.join(
        f"{item['kind']} {item['score']:g}/100 [{_event_time(item['recorded_at']).strftime('%Y-%m-%d %H:%M UTC') if item['recorded_at'] else '日期未知'}，{AID_LABELS[item['aid_status']]}"
        +('，复习作答，'+('同题版本已核实' if item.get('same_question_verified') is True else '同题版本未核实') if item['is_review'] else '')
        +(f"，间隔{item['delay_hours']:g}小时" if item['delay_hours'] is not None else '')+']' for item in records)


def _reference_score(q, f):
    parts = [(q, .6), (f, .25)]
    total = sum(weight for value, weight in parts if value is not None)
    return round(sum(value * weight for value, weight in parts if value is not None) / total, 1) if total else None


def scoring_settings() -> dict:
    row = one("SELECT value FROM workspace_state WHERE key='profile_scoring'")
    weight = unj(row['value'], {}).get('self_report_weight', 20) if row else 20
    if type(weight) is not int or not 0 <= weight <= 50: weight = 20
    return {'self_report_weight': weight, 'assessment_weight': 100 - weight}


def save_scoring_settings(value: dict) -> dict:
    weight = value.get('self_report_weight')
    if type(weight) is not int or not 0 <= weight <= 50:
        raise ValueError('自评权重须为 0 到 50 的整数百分比')
    execute("INSERT INTO workspace_state VALUES ('profile_scoring',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (j({'self_report_weight': weight}),))
    return scoring_settings()


def _learning_score(row, weight):
    assessment, self_rating = row.get('score'), _score(row.get('self_rating'))
    combined = round(assessment * (1 - weight / 100) + self_rating * weight / 100, 1) if assessment is not None and self_rating is not None else assessment
    # A self-only reference is displayed as untested, never as an assessment grade.
    if assessment is None and self_rating is not None: combined = self_rating
    row.update(assessment_score=assessment, learning_score=combined, self_report_weight=weight,
               learning_score_basis='assessment_and_self_report' if assessment is not None and self_rating is not None and weight else
                                    'assessment_only' if assessment is not None else 'self_report_only' if self_rating is not None else 'unscored',
               self_rating_gap=round(self_rating-assessment, 1) if assessment is not None and self_rating is not None else None)
    return row


def effective_profile() -> list[dict]:
    """Recompute from active evidence, never blend perceived mastery into assessment.

    Legacy summaries lack an event ledger: expose their uncertainty. For a topic
    with a ledger, use that ledger only; removed records cannot leak back through
    the old aggregate. This intentionally does not rewrite actual exam grades.
    """
    legacy = {r['topic']: r for r in many('SELECT * FROM mastery')}
    events = many("SELECT e.*,i.id AS insight_id,COALESCE(c.deleted,0) AS deleted FROM learning_events e "
                  "LEFT JOIN learning_insights i ON i.event_id=e.id AND i.kind='assessment' "
                  "LEFT JOIN learning_insight_controls c ON c.insight_id=i.id "
                  "WHERE e.kind IN ('做题','费曼讲解','编程作业','自评') ORDER BY e.id")
    buckets, ledger_topics = {}, set()
    seen = set()
    for event in events:
        payload = unj(event['payload_json'], {})
        topic = payload.get('topic')
        if not isinstance(topic, str) or not topic.strip():
            continue
        ledger_topics.add(topic)
        if event['deleted'] or event['id'] in seen or event['insight_id'] is None:
            continue
        seen.add(event['id'])
        item = buckets.setdefault(topic, dict(topic=topic, quiz_score=None, feynman_score=None, self_rating=None,
                                             difficulty_rating=None, evidence_count=0, assessment_count=0, self_report_count=0,
                                             assisted_count=0, review_count=0, delayed_count=0, unaided_quiz_score=None, has_practice_context=False,
                                             recent_assessments=[]))
        item['updated_at'] = event['created_at']
        item['evidence_count'] += 1
        score = _score(payload.get('score'))
        if event['kind'] == '自评':
            item['self_report_count'] += 1
            item['self_rating'] = score
            difficulty = _score(payload.get('difficulty_rating'))
            if difficulty is None:  # Existing versions stored this only in the self-report text.
                match = re.search(r'主观难度\s+(\d{1,3})(?!\d)', str(payload.get('student_text', '')))
                difficulty = _score(int(match[1])) if match else None
            item['difficulty_rating'] = difficulty
        elif score is not None:
            item['assessment_count'] += 1
            recent=item['recent_assessments']
            recent.append((_event_time(event['created_at']) or datetime.min.replace(tzinfo=timezone.utc),event['id'],_recent_assessment(event,payload,score)))
            recent.sort(key=lambda entry:entry[:2],reverse=True)
            del recent[3:]
            column = 'feynman_score' if event['kind'] == '费曼讲解' else 'quiz_score'
            old = item[column]
            item[column] = round(.7 * old + .3 * score, 1) if old is not None else score
            context = payload.get('practice_context')
            if isinstance(context, dict):
                item['has_practice_context'] = True
                index = str(context.get('question_index', 0))
                level = context.get('hint_levels', {}).get(index, 0)
                assisted = bool(level) or context.get('used_notes') is True
                conditions_known=context.get('recording_status') not in ('partial','not_recorded')
                if assisted: item['assisted_count'] += 1
                if context.get('is_review'): item['review_count'] += 1
                timing = next((x for x in context.get('timing', []) if str(x['question_index']) == index), None)
                if conditions_known and timing and timing.get('same_question_verified') is True and timing.get('delay_hours', 0) >= 24 and not assisted and context.get('used_notes') is False:
                    item['delayed_count'] += 1
                # "Unaided" means no app hint + self-reported no notes; external
                # assistance and independence remain unverified.
                if conditions_known and not assisted and context.get('used_notes') is False:
                    previous = item['unaided_quiz_score']
                    item['unaided_quiz_score'] = round(.7 * previous + .3 * score, 1) if previous is not None else score
    for topic, item in buckets.items():
        item['recent_assessments']=[entry[2] for entry in item['recent_assessments']]
        item['score'] = _reference_score(item['quiz_score'], item['feynman_score'])
        item['score_basis'] = 'traceable' if item['score'] is not None else 'self_report_only' if item['self_report_count'] else 'unscored'
    excluded = {row['topic'] for row in many('SELECT topic FROM legacy_profile_exclusions')}
    for topic, item in legacy.items():
        if topic not in ledger_topics and topic not in excluded:
            score = _reference_score(item['quiz_score'], item['feynman_score'])
            buckets[topic] = dict(item, score=score, score_basis='legacy_summary', assessment_count=None, self_report_count=None)
    weight = scoring_settings()['self_report_weight']
    return sorted((_learning_score(row, weight) for row in buckets.values()), key=lambda x: x['updated_at'], reverse=True)


def _profile_focuses(focus):
    return tuple(part for part in ((focus,) if isinstance(focus, str) else focus) if part.strip())


def assessment_context(profile: list[dict], relevance: str, *, focus: str | list[str] = '') -> str:
    parts = []
    cues = _profile_focuses(focus)
    def rank(row):
        return next((i for i, cue in enumerate(cues) if row['topic'] in cue), len(cues))
    relevant = [row for row in profile if row['topic'] in relevance or rank(row) < len(cues)]
    if cues:
        relevant.sort(key=rank)
    for row in relevant:
        score = row.get('score')
        label = f"评估参考分 {score:.0f}/100" if score is not None else '尚无作答评分'
        if row.get('score_basis') == 'legacy_summary':
            label += '（早期汇总，缺少逐条证据）'
        self_rating = row.get('self_rating')
        difficulty = row.get('difficulty_rating')
        combined, basis = row.get('learning_score'), row.get('learning_score_basis')
        if combined is not None:
            label += f"；综合学习参考分 {combined:g}/100"
            if basis == 'assessment_and_self_report':
                weight = row['self_report_weight']
                label += f"（作答参考 {100-weight}% + 最近有效自评 {weight}%）"
            elif basis == 'self_report_only': label += '（只有学生自评，未测验）'
        practice_note = (f"；有支持的作答{row.get('assisted_count', 0)}次，复习{row.get('review_count', 0)}次，"
                         f"间隔至少24小时且自报未看笔记/未用软件提示{row.get('delayed_count', 0)}次（非独立性验证）") if row.get('has_practice_context') else ''
        parts.append(f"{row['topic']}：{label}；自评掌握 {self_rating if self_rating is not None else '未自评'}；主观难度 {difficulty if difficulty is not None else '未自评'}" + practice_note + recent_assessment_text(row))
    return ('；'.join(parts[:30]) or '暂无相关评估证据') + '。参考分用于教学适配：综合学习参考分用于初步选择讲解详略与练习难度，结合具体疑问、错因与主观难度调整；自评和作答分差异较大时先核对理解，不凭综合分断言掌握。自评权重是用户可调的教学约定，不是经校准的能力或长期掌握概率；自评不算作答成绩，不改变试卷评分或80分过关条件。提示记录只涵盖本软件，未证实独立完成、期间未再接触材料或长期保持。'


def _profile_matcher(query):
    terms = [term.casefold() for term in re.split(r'\s+', query.strip()) if term]
    def matches(topic, items):
        if not terms:
            return True
        labels = [topic] + [anchor for item in items for anchor in item['anchors']]
        return any(term in label.casefold() or label.casefold() in term
                   for term in terms for label in labels if label)
    return matches


def mentor_profile(query='',offset=0,limit=12, *, focus=''):
    """Global teaching summaries, without raw evidence, transcript IDs or paths."""
    from .learning_memory import filter_existing_events
    filter_existing_events()
    profile=effective_profile()
    rows=many(PROFILE_SELECT+' WHERE '+DELETED+'=0 ORDER BY COALESCE(c.updated_at,i.created_at) DESC,i.id DESC')
    insights=[public_insight(row) for row in rows]
    relevant = _profile_matcher(query)
    prioritized = [_profile_matcher(cue) for cue in _profile_focuses(focus)]
    by_topic={}
    preferences=[]
    for item in insights:
        summary={key:item[key] for key in ('kind','dimension','observation','confidence','updated_at')}
        summary['user_corrected']=item['correction'] is not None
        if item['kind']=='preference' and not item['anchors']:
            if len(preferences)<6:preferences.append(summary)
            continue
        by_topic.setdefault(item['topic'],[]).append(item)
    scores={item['topic']:item for item in profile}
    topics=list(dict.fromkeys([item['topic'] for item in profile]+list(by_topic)))
    def rank(topic):
        return next((i for i, matches in enumerate(prioritized) if matches(topic,by_topic.get(topic,[]))), len(prioritized))
    matched=[topic for topic in topics if relevant(topic,by_topic.get(topic,[])) or rank(topic) < len(prioritized)]
    if prioritized:
        # Stable order within each tier preserves recency and pagination.
        matched.sort(key=rank)
    output=[]
    for topic in matched[offset:offset+limit]:
        row={'topic':topic}
        row.update({key:value for key,value in scores.get(topic,{}).items() if key!='topic'})
        selected=by_topic.get(topic,[])
        # Numeric assessment fields already expose scores; leave room for the
        # student's questions and conceptual difficulties, even after quizzes.
        observations=[item for item in selected if item['kind']!='assessment'][:4]+[item for item in selected if item['kind']=='assessment'][:1]
        recent=row.get('recent_assessments',[])
        latest=_event_time(recent[0]['recorded_at']) if recent else None
        row['observations']=[{key:item[key] for key in ('kind','dimension','observation','confidence','updated_at','evidence_recorded_at')}
                             |{'user_corrected':item['correction'] is not None,
                               'later_assessment_recorded':bool(item['kind']=='gap' and item['correction'] is None and latest
                                    and (observed:=_event_time(item['evidence_recorded_at'])) and observed<latest)} for item in observations]
        row['history_notice']=('历史疑问之后已有评估记录；先结合近期作答核对当前卡点，不能沿用旧疑问断定仍不会，'
                               '也不能凭一次高分认定已掌握。' if any(item['later_assessment_recorded'] for item in row['observations']) else '')
        row['observation_count']=len(selected)
        output.append(row)
    return {'scope':'global_learning_profile','chat_history_shared':False,'query':query,
            'total_topics':len(topics),'matched_topics':len(matched),'active_observations':len(insights),
            'pending_events':one("SELECT COUNT(*) AS n FROM learning_events e WHERE status IN ('pending','running') "
                "AND NOT EXISTS (SELECT 1 FROM learning_event_filters f WHERE f.event_id=e.id AND f.eligible=0) "
                "AND NOT EXISTS (SELECT 1 FROM learning_event_profile_blocks b WHERE b.event_id=e.id)")['n'],
            'topics':output,'general_preferences':preferences,'offset':offset,
            'next_offset':offset+limit if offset+limit<len(matched) else None,
            'notice':'用户画像跨项目共享；不包含其他对话原文、证据引句或消息路径。接触不证明掌握，聊天判断暂定，'
                     '综合学习参考分结合已有表现与最近有效自评，用于讲解详略和练习难度适配；只有自评时明确标为未测验。'
                     '作答参考分及真实试卷成绩另列，不受自评影响；近期评估按记录时间列出，题目、难度和帮助条件可能不同，分差不直接等于能力变化。'
                     '用户纠正优先，软件不验证用户纠正是否代表实际能力。'}
