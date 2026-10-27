"""Construct synthetic teaching records, never learner production data."""
from pathlib import Path

from studyforge import conversations,lesson_feedback,lesson_focus,server
from studyforge.db import create_job,create_project,execute,j,now,one,uid
from studyforge.exporters import export_document

CASES={
    'math':{
        'title':'极限唯一性与开邻域', 'section':'为什么可以取距离的一半',
        'source':'收敛数列若有两个极限a<b，令ε=(b-a)/2>0。由极限定义，两种估计在n超过相应门槛后成立。取门槛最大值，同一项既严格小于又严格大于中点，矛盾。开邻域排除端点，半径等于两点距离一半时仍无交集；更小的正半径也可用。',
        'quote':'为了让两个邻域不相交，需要半径严格小于距离的一半，所以直接取等号。',
        'question':'我看懂不等式的计算，但这里为什么能取等号？是不是和前面说的严格小于矛盾？',
        'followup':'先更正旧讲解：不相交的充分范围包含半径等于距离的一半，因为两个邻域是开区间，共同中点不属于任何一个。极限定义允许任意正半径；a<b保证一半距离为正。选一半便于让两边以同一中点分界，更小半径也能证明，并非唯一取法。'},
    'causal':{
        'title':'大样本关联与因果识别','section':'大样本解决的是什么',
        'source':'观察调查发现，经常记笔记与较高成绩相关。样本扩大可减少抽样不确定性，但不会自动排除基础、动机等共同因素、反向因果或测量偏差。统计显著不等于效应大，也不单独证明因果。随机干预或在明确假设下的其他因果设计可以提供更强依据。',
        'quote':'调查人数足够多而且差异显著，就可以证明多记笔记让成绩提高。',
        'question':'我仍不懂：人数已经很多，为什么不能排除其他解释？请就抽样误差与混杂的区别解释。',
        'followup':'扩大样本量会让观察到的组间差异估计得更精确，但分组若来自学生自己的选择，两组的基础、动机等差异并不会随人数变大自动消失。统计显著描述与所用统计模型有关的抽样不确定性，不负责排除这些替代机制。原关联仍可保留；要讨论行为本身的因果作用，需要额外设计和假设，不限于某一种实验形式。'},
}


def seed(folder,key='math',project_id=None,conversation_id=None):
    case=CASES[key];folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    project_id=project_id or create_project('合成补讲检查 · '+key)['id']
    chat=(conversations.detail(conversation_id,project_id) if conversation_id else conversations.create(project_id,'deepseek','deepseek-flash'))
    if not conversation_id:chat=conversations.update(chat['id'],project_id,{'reasoning_effort':'high'})
    source=uid();path=folder/(case['title']+'_原资料.txt');path.write_text(case['source'],encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source,project_id,path.name,'.txt',str(path),'ready',now()))
    payload={'source_ids':[source],'conversation_id':chat['id'],'learning_mode':'deep','explanation_style':'balanced','output_language':'zh'}
    job=create_job(project_id,'generate',payload)
    lecture='# '+case['title']+'\n\n## '+case['section']+'\n\n'+case['quote']+'\n\n## 系统性总结\n\n这是一份特意保留不当说法的合成旧讲解，用于检查补讲是否纠正并定位。'
    word=export_document(lecture,'docx','合成旧讲解',uid()+'.docx')
    artifact=server.add_artifact(project_id,[source],'explanation','docx',case['title'],word,{'generation_job_id':job,'conversation_id':chat['id'],'synthetic_fixture':True})
    message=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(message,chat['id'],'assistant','已生成讲解文档：\n\n'+lecture,now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)',(job,chat['id'],message));execute("UPDATE jobs SET status='completed' WHERE id=?",(job,))
    q=lesson_feedback.ensure_questionnaire(job);row=lesson_feedback.get_questionnaire(q['id'])
    section=next(value for value in lesson_focus.section_options(row)['items'] if value['title']==case['section'])
    text=lesson_focus.select_focus(row,section['id'])['excerpt'];start=text.index(case['quote'])
    lesson_feedback.submit_questionnaire(q['id'],['motivation'],case['question'],focus_section_id=section['id'],
        focus_selection={'start':start,'end':start+len(case['quote']),'text':case['quote']})
    reply=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(reply,chat['id'],'assistant',case['followup'],now()))
    execute("UPDATE lesson_questionnaires SET reply_status='completed',reply_message_id=? WHERE id=?",(reply,q['id']))
    return {'project_id':project_id,'conversation_id':chat['id'],'questionnaire_id':q['id'],'source_id':source,
        'lesson_artifact':artifact,'case':key,'title':case['title'],'synthetic_teaching_records':True}
