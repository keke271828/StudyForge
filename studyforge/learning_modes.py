"""One learning intent shared by dialogue, lecture, revision and follow-up."""
from __future__ import annotations

from typing import Literal

from .db import execute, one, now

LearningMode = Literal['overview', 'deep', 'research']
DEFAULT_LEARNING_MODE: LearningMode = 'deep'
MODE_LABELS = {'overview': '概览', 'deep': '精学', 'research': '研究'}
MODE_FEATURES = {
    'overview': {
        'aim': '建立问题地图，读懂主线',
        'allocation': '讲解主体用于问题定位和概念、论据、结论的连接；证明串联关键转折，逐行计算留给明确的追问；重要理由和成立条件仍保留',
        'focus': '材料解决什么问题、概念之间怎样连接、结论由什么支持、重要限制是什么',
        'structure': '从问题和主结论进入，连起核心概念与关键论据，交代必要条件和在知识体系中的位置，最后串联主线',
        'method': '用少量关键转折说明方法怎样推进结论；详略增加时补足主线细节、术语及背景，不自动变成逐行证明',
        'interaction': '回答完后可邀请学生选择希望深入的概念或转折；简短问答无需固定追问',
        'checks': ['能说明材料解决的问题及主结论', '核心概念与论据形成一条主线', '必要条件与重要限制保留清楚'],
    },
    'deep': {
        'aim': '形成可复现、可迁移的理解',
        'allocation': '讲解主体用于打通当前概念或推理障碍，用适合本学科的完整例子、对照或论证；涉及证明、计算或实现时讲明关键步骤依据，提炼再次使用和判断的线索',
        'focus': '真正卡住的概念、构造或方法选择、步骤依据，以及再次遇到问题时的识别线索',
        'structure': '围绕当前困难组织：概念辨析用完整具体例子或对照说明含义、区别和误用；存在证明、计算或实现任务时展开目标、构造线索和关键步骤依据；经验主张说明证据如何支持结论，哲学论证说明前提与反驳；提炼使用线索和边界，最后串联主线',
        'method': '关键步骤同时说明操作、合法依据和对目标的作用；有帮助时完成一个条件变化的例子或反例，由导师讲解，不让学生先作答',
        'interaction': '围绕学生刚才的具体表述定位一处理解缺口；解释后可询问哪一步的依据仍不清楚，不按固定模板布置任务',
        'checks': ['关键构造说明目标、障碍和选择线索', '关键步骤说明合法依据而非只列公式', '指出一处具体的使用条件或误用边界'],
    },
    'research': {
        'aim': '评估论证边界，设计可核实的追问',
        'allocation': '已有结论及证明用少量关键依据准确回顾，主体篇幅用于分析条件依赖、证据强弱与核实路径',
        'focus': '结论依赖哪些假设、现有材料能支持到哪一步、替代解释如何区分、进一步核实需要什么',
        'structure': '先准确重建主张及其依据，分清已证明或已观察的内容与假设，分析有实质作用的边界或替代解释，说明能够区分它们的验证办法及局限，最后归纳已知与未决',
        'method': '数学具体说明一处条件改变会影响哪一步、应如何核对，再讨论可推广范围；已证结论不虚构成争议。经验学科比较解释及能区分它们的证据；哲学辨析概念、前提、反驳和评价原则，不一律要求实验',
        'interaction': '适合时邀请学生选择要检验的假设或证据缺口；进一步方向写成建议，不强制提交研究作业',
        'checks': ['区分材料已支持的结论与额外假设', '展开一处有实质作用的边界或替代解释', '具体说明进一步核实哪一步、用什么办法及其局限'],
    },
}
_GUIDANCE = {
    'overview': (
        '目标是建立问题地图、读懂主线。主体串联问题、核心概念、关键论据和结论及限制；'
        '证明保留推动主线的关键转折，不默认逐行计算或穷尽延伸。'
        '必要术语仍讲清；学生明确追问某一步时，把那个卡点讲透。'
    ),
    'deep': (
        '目标是可复现、可迁移的理解。主体用于解释真正的困难：概念怎样理解，'
        '方法为何适合，关键构造怎样找到，步骤为何成立。'
        '概念问题先用完整具体例子或对照说明；有证明、计算或实现任务时才展开相应的构造步骤。'
        '精学不默认升级成自建数学模型或新理论课，原资料已有的专业论证仍须讲透。'
        '按需完成例子、反例或替代思路，提炼方法的使用线索与条件；'
        '不把看懂或复述认定为已经独立掌握，不强迫学生先答题才讲解。'
    ),
    'research': (
        '目标是评估证据与适用边界。先把主张及依据讲准，主体分析条件依赖、'
        '证据强弱或有实质作用的替代解释，并给具体核实办法及局限。'
        '数学核对条件改变后哪一步失效；经验学科说明什么证据能区分解释；'
        '哲学辨析概念、前提和反驳，不一律要求实验。'
        '已证结论不虚构成争议，核实建议不冒充已经取得的新证据。'
    ),
}


def mode_policy(mode: str) -> str:
    if mode not in MODE_LABELS:
        raise ValueError('未知学习模式')
    return (f'\n【当前学习模式：{MODE_LABELS[mode]}】' + _GUIDANCE[mode] +
            '模式控制教学目标，概括性档位控制该目标下的详略。'
            '学生明确的篇幅、来源、格式与不出题要求优先；具体追问先解释该点，不重讲整份资料。'
            '模式不授权新的联网、视频或文件访问，不改变模型、推理等级或审查轮数。'
            '讲解不附习题，同步出题由独立选项决定。\n')


def mode_structure(mode: str) -> str:
    if mode not in MODE_FEATURES:
        raise ValueError('未知学习模式')
    return MODE_FEATURES[mode]['structure']


def mode_task_reminder(mode: str, *, role: str = 'tutor') -> str:
    """Keep the selected aim explicit after full sources and past responses.

    The reminder is part of the existing request, not an additional review or
    a request for private chain of thought. Explicit user requirements prevail.
    """
    if mode not in MODE_FEATURES:
        raise ValueError('未知学习模式')
    if role not in ('tutor', 'lecture'):
        raise ValueError('未知教学任务')
    feature = MODE_FEATURES[mode]
    focus = {
        'overview': '',
        'deep': '概念辨析先用完整具体例子讲透；未要求建模或量化推导时不默认自建数学模型，原资料已有的证明和公式仍完整解释。',
        'research': '',
    }[mode]
    return (f'\n【本次{MODE_LABELS[mode]}教学重点，不属于原资料】{feature["aim"]}。'
            '本次明确问题与要求优先，不机械套固定标题。'
            + focus
            + ('需要时在讲清后确认当前困难。' if role == 'tutor' else
               '生成可独立阅读的讲解，保留系统性总结，不附待答练习。'))


def mode_catalog() -> dict:
    return {key: {'label': MODE_LABELS[key], **feature, 'checks': list(feature['checks'])}
            for key, feature in MODE_FEATURES.items()}


def resolve_mode(requested: str | None = None, conversation_id: str | None = None) -> LearningMode:
    saved = one('SELECT learning_mode FROM conversation_learning_modes WHERE conversation_id=?',
                (conversation_id,)) if conversation_id else None
    from .ai import settings
    mode = requested or (saved or {}).get('learning_mode') or settings().get('learning_mode', DEFAULT_LEARNING_MODE)
    if mode not in MODE_LABELS:
        raise ValueError('未知学习模式')
    return mode


def save_conversation_mode(conversation_id: str, mode: LearningMode) -> None:
    if mode not in MODE_LABELS:
        raise ValueError('未知学习模式')
    execute('INSERT INTO conversation_learning_modes VALUES (?,?,?) '
            'ON CONFLICT(conversation_id) DO UPDATE SET learning_mode=excluded.learning_mode,updated_at=excluded.updated_at',
            (conversation_id, mode, now()))
