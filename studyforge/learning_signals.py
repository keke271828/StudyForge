"""Cheap candidate filtering; only evidence-backed learning reaches the profile."""
import re


_APP = re.compile(r'工作台|按钮|选项卡|资料库|项目文件夹|聊天记录|用户画像|学习画像|更新软件|重装|'
                  r'JSONDecodeError|ConnectError|网络错误|生成失败|审查未通过|剪贴板|打包|'
                  r'模型列表|选择模型|推理强度|背景透明|切换模式|暂停生成|继续生成|[.]exe\b',re.I)
_OPERATION = re.compile(r'^(?:请|帮我|能否|能不能|可以|麻烦|我要|我想|给我)*\s*'
                        r'(?:新建|删除|重命名|打开|关闭|上传|下载|导入|导出|复制|打包|生成|出题|布置|输出|整理成|转换成|总结成)')
_TRIVIAL = re.compile(r'^(?:好[的吧]?|嗯|谢谢[你了]?|收到|继续[吧]?|下一项|下一步|没问题|可以|再来一次|重试|ok|thanks)[!！。\s]*$',re.I)
_LEARNING = re.compile(r'为什么|为何|什么是|(?:再|继续)讲(?:一下)?|请(?:解释|讲解|说明|证明)|帮我(?:理解|推导)|(?:怎么|怎样|如何)(?:理解|证明|推导|想到|构造|判断|求|算|解)|'
                       r'是什么(?:意思)?|有何(?:区别|联系|不同|相同)|区别|前置知识|'
                       r'(?:解释|讲解|说明).{0,40}(?:概念|定理|术语|公式|知识|前置|构造|动机|方法|思想|条件|机制)|(?:我|自己|这一步|这个概念|证明).{0,18}'
                       r'(?:不懂|没懂|没看懂|看不懂|不明白|不理解|不确定|理解|认为|觉得|推出|推导|证明|掌握|不会|会套|能复述)|'
                       r'(?:看懂|读懂).{0,15}(?:但是|但|却)|(?:定理|概念|公式|论证|证明|算法|知识点).{0,12}(?:解释|讲解|含义|条件|适用)|'
                       r'(?:请|希望|喜欢).{0,12}(?:讲慢|慢一些|举例|推导|证明|术语|讲解|教学)|'
                       r'what (?:is|does)|why|how (?:to|does)|I (?:think|understand|don.t understand)|prerequisite|explain|prove',re.I)
_FOLLOWUP = re.compile(r'^(?:这里|这一步|那一步|这个|它|上面).*(?:不懂|不明白|不理解|为什么|怎么|意思)|^(?:还是没懂|没听懂|能举个例子)',re.I)


def learning_excerpt(text, mentor_context=''):
    """Return plausible study evidence, without forwarding unrelated chat turns.

    This is a candidate gate, not a diagnosis. The bounded background model and
    literal-quote validation still decide whether there is enough evidence.
    """
    if not isinstance(text,str) or not text.strip() or _TRIVIAL.fullmatch(text.strip()):return ''
    from .learning_voice import partition
    text=partition(text)[0]
    clauses=re.split(r'(?<=[。！？!?])|\n',text)
    useful=[]
    for clause in clauses:
        clause=clause.strip()
        if not clause or _APP.search(clause):continue
        if _OPERATION.search(clause) and not re.search(r'(?:我|自己).{0,10}(?:不懂|不明白|理解|认为|推出|推导|掌握)',clause):continue
        reasoning=bool(re.search(r'因此|所以|假设|由此|可得|推出|=>|∴|\breturn\b|[a-zA-Z]\s*=',clause) and
                       re.search(r'证明|定理|概念|推导|题目|解法|代码|函数|为什么|如何',mentor_context) and not _APP.search(mentor_context))
        if _LEARNING.search(clause) or reasoning or (_FOLLOWUP.search(clause) and not _APP.search(mentor_context)):
            useful.append(clause)
    return '\n'.join(useful)


def eligible_event(kind,payload):
    if kind=='chat':return bool(learning_excerpt(payload.get('student_text',''),payload.get('mentor_context','')))
    # Importing a file alone does not identify knowledge actually studied.
    if kind=='import':return False
    return True


def unrelated_quote(text):
    return bool(_APP.search(text) or _TRIVIAL.fullmatch(text.strip()))


def explicit_definition_questions(text):
    """Preserve a narrow, literal doubt immediately, without diagnosing mastery."""
    topics=[]
    for clause in learning_excerpt(text).splitlines():
        cleaned=re.sub(r'^(?:请问|我想知道|请告诉我|我不明白|到底)\s*','',clause).strip()
        match=re.match(r'^([\w\u4e00-\u9fff· -]{2,24}?)是什么(?:意思)?[？?。！!\s]*$',cleaned)
        if not match:match=re.match(r'^什么是\s*([\w\u4e00-\u9fff· -]{2,24})[？?。！!\s]*$',cleaned)
        if match:
            topic=match.group(1).strip()
            if topic not in topics:topics.append(topic)
    return topics[:3]
