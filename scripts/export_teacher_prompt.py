"""Keep the readable prompt document in sync with the actual application rules."""
from pathlib import Path

from studyforge.teaching import TEACHER_PERSONA, CHAT_RULES, LECTURE_RULES, REASONING_TEACHING_RULES, TEACHING_TASK_REMINDER
from studyforge.agent_tools import AGENT_RULES

root = Path(__file__).resolve().parents[1] / 'docs'
root.mkdir(exist_ok=True)
sections = [('共同导师设定', TEACHER_PERSONA), ('证明与解题思路（对话和文档共用）', REASONING_TEACHING_RULES),
            ('学习对话规则', CHAT_RULES.removeprefix(REASONING_TEACHING_RULES)), ('学习工具规则', AGENT_RULES),
            ('讲解文档规则', LECTURE_RULES.removeprefix(REASONING_TEACHING_RULES)), ('当前教学任务提醒', TEACHING_TASK_REMINDER)]
text = '# StudyForge AI 导师提示词\n\n以下内容与程序实际使用的导师规则一致。'
text += '聊天与文档生成由同一位导师沿用同一学习对话、模型和推理强度完成。Codex 继续同一远端会话；DeepSeek 保留完整对话及内部工具结果。生成讲解另附完整原文、学习画像和本次要求，成果保存回该对话。\n'
text += '证明与解题思路规则在实际对话和文档生成中各合并一次；只补写系统性总结时不附加这份展开规则。现有概括性强弱控制讲解深度，不额外增加审查调用。\n'
for title, content in sections:
    text += '\n## ' + title + '\n\n' + content.replace('。', '。\n\n') + '\n'
(root / 'AI导师提示词.md').write_text(text, encoding='utf-8')
