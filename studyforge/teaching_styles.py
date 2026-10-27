"""Saved expression, language and lecture review preferences for each chat."""
from __future__ import annotations

from typing import Literal

from .db import execute, now, one

ExplanationStyle = Literal['clear', 'balanced', 'academic']
OutputLanguage = Literal['zh', 'bilingual', 'en']
ReviewMode = Literal['express', 'fast', 'balanced', 'strict']
STYLE_LABELS = {'clear': '通俗清晰', 'balanced': '直观与专业并重', 'academic': '学术专业'}
LANGUAGE_LABELS = {'zh': '中文', 'bilingual': '中英双语', 'en': '英语'}
REVIEW_MODES = {'express', 'fast', 'balanced', 'strict'}
_GUIDANCE = {
    'clear': (
        '用常用词和具体过程解释抽象含义，必要术语与前置知识就地补足。'
        '重要公式先说明量的含义，再接上关系和关键步骤。'
        '抽象难点主动给一个已经讲完的具体例子；数值例子展示必要计算。'
        '合适的比喻说明对应与边界，再回到准确概念，不硬套生活比喻。'
        '步骤小一些，理由说透，不能为通俗删掉成立条件。'
    ),
    'balanced': (
        '把直观含义与准确的专业表述对应起来：概念疑问先定位混淆，用具体对象、'
        '图形关系或完整小例子解释，再接回定义、符号与成立条件。'
        '涉及证明、解题或方法选择时，讲清构造要解决的困难、从条件或目标找到的线索和选择的合法性，'
        '随后衔接关键推导，区分方便的选择与必要条件。'
        '按当前疑问选择这些路径，直觉与论证互相支撑；必要时说明误用边界或替代思路。'
    ),
    'academic': (
        '用紧凑的专业论证明确对象、定义、假设、关键依据和适用范围。'
        '记号和陌生关键术语仍须交代，不用晦涩措辞或跳步冒充专业；'
        '必要时仍解释方法选择，但少作已知背景铺陈。'
    ),
}


def style_policy(style: str) -> str:
    if style not in STYLE_LABELS:
        raise ValueError('未知讲解风格')
    return (f'\n【当前讲解风格：{STYLE_LABELS[style]}】' + _GUIDANCE[style] +
            '风格控制表达方式，学习模式控制目标，概括性控制详略。'
            '学生本次明确的篇幅、格式、来源与例子要求优先；'
            '风格不改变模型、推理强度、审查轮数、资料范围或是否出题。\n')


def style_task_reminder(style: str) -> str:
    """Short expression cue after long sources; never repeat the whole policy."""
    if style not in STYLE_LABELS:
        raise ValueError('未知讲解风格')
    focus = {
        'clear': '必要术语说清，抽象处用讲完的具体例子或恰当比喻接回概念。',
        'balanced': '把直观含义与准确论证对应起来；涉及方法选择时讲清动机。',
        'academic': '对象、条件和推理依据准确紧凑，记号清楚，关键步骤不跳过。',
    }[style]
    return f'\n【本次表达重点：{STYLE_LABELS[style]}】{focus}\n'


def resolve_style(requested: str | None = None, conversation_id: str | None = None) -> ExplanationStyle:
    return _resolve('explanation_style', requested, conversation_id, STYLE_LABELS, 'clear', '未知讲解风格')


def resolve_language(requested: str | None = None, conversation_id: str | None = None) -> OutputLanguage:
    return _resolve('output_language', requested, conversation_id, LANGUAGE_LABELS, 'zh', '未知讲解语言')


def resolve_review_mode(requested: str | None = None, conversation_id: str | None = None) -> ReviewMode:
    return _resolve('review_mode', requested, conversation_id, REVIEW_MODES, 'express', '未知讲解审查模式')


def _resolve(field, requested, conversation_id, choices, default, message):
    saved = one('SELECT * FROM conversation_teaching_styles WHERE conversation_id=?', (conversation_id,)) if conversation_id else None
    from .ai import settings
    value = requested if requested is not None else (saved or {}).get(field) or settings().get(field, default)
    if value not in choices:
        raise ValueError(message)
    return value


def language_policy(language: str) -> str:
    if language not in LANGUAGE_LABELS:
        raise ValueError('未知讲解语言')
    guidance = {
        'zh': '解释正文与总结使用中文，保留原文术语；必要时首次出现附原文词汇，不无故逐句重复英文。',
        'bilingual': '解释正文与总结按段落或小节先中文后对应英文，两种语言表达同样的论点、步骤和限定；不只翻译标题，不新增一套不同的结论。',
        'en': 'Use English for the explanation, headings, examples and summary. Explain unfamiliar terminology clearly; preserve the source terminology when needed.'
    }[language]
    return (f'\n【当前讲解语言：{LANGUAGE_LABELS[language]}】' + guidance +
            '逐字原文引用、来源文件名和定位保持原样，翻译或释义放在引用块外；代码标识符和数学记号不为翻译而改写。'
            '学生本次明确指定的语言或仅一句话等格式要求优先；语言选择不改变学科、深度、选材、审查轮数或是否出题。\n')


def save_conversation_style(conversation_id: str, style: ExplanationStyle) -> None:
    save_conversation_preferences(conversation_id, explanation_style=style)


def save_conversation_preferences(conversation_id: str, **changes) -> None:
    resolvers = {'explanation_style': resolve_style, 'output_language': resolve_language, 'review_mode': resolve_review_mode}
    if not set(changes).issubset(resolvers):
        raise ValueError('未知讲解偏好')
    # Update only explicit fields on conflict, so independent clients changing
    # language and style cannot overwrite each other's unrelated preferences.
    values = [resolvers[field](changes.get(field), conversation_id) for field in resolvers]
    updates = ','.join(f'{field}=excluded.{field}' for field in resolvers if field in changes)
    if updates: updates += ','
    execute('INSERT INTO conversation_teaching_styles(conversation_id,explanation_style,output_language,review_mode,updated_at) VALUES (?,?,?,?,?) '
            'ON CONFLICT(conversation_id) DO UPDATE SET ' + updates + 'updated_at=excluded.updated_at',
            (conversation_id, *values, now()))
