"""Synthetic source, submitted work and self-report for isolated evaluations."""
from pathlib import Path


def seed(folder,project_id=None,conversation_id=None):
    from studyforge import conversations,homework
    from studyforge.db import create_project,create_job,execute,j,now,one,uid
    project_id=project_id or create_project('错因再练隔离验收')['id']
    conversation_id=conversation_id or conversations.create(project_id,'deepseek','deepseek-flash')['id']
    original=Path(folder)/'高斯定律_合成原材料.txt'
    text=('高斯定律：闭合曲面的净电通量等于内部净电荷除以真空介电常数。'
        '通量是电场法向分量对面积的积分，是有正负的整体求和；各点的电场是局部矢量。'
        '内部净电荷为零只说明净通量为零，不能推出内部电场处处为零。'
        '均匀电场穿过一个盒子时，可以在一个面穿入、另一个面穿出，贡献抵消，但各点电场不为零。'
        '外部电荷能影响内部的场，却不贡献这个闭合曲面的净通量。')
    original.write_text(text,encoding='utf-8');source=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source,project_id,original.name,'.txt',str(original),'ready',now()))
    ident=uid();questions=[{'index':0,'topic':'高斯定律','question':'内部净电荷为零能否推出内部电场处处为零？说明理由。'},
        {'index':1,'topic':'算术','question':'计算2+3并说明步骤。'}]
    answers=['我认为内部净电荷为零就能推出里面每个点的电场为零。','从2依次加三个1，得到3、4、5，因此2+3=5。']
    solutions=[{'index':0,'solution':'净电通量是整体求和，穿入和穿出可抵消，电场可以不为零。','rubric':'整体与局部的区别及解释。'},
        {'index':1,'solution':'2+3=5。','rubric':'加法及步骤正确。'}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,project_id,j([source]),'通量与场的概念检查',
        j(questions),j(solutions),2,'passed',now()))
    submission=uid();grade={'scores':[90,100],'score':95,'feedback':['整体净和不能决定各点的值；需要区分通量与电场。','正确。'],
        'grading_verification_required':False,'submission_id':submission}
    attempt=uid();grade['homework_attempt_id']=attempt
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(submission,ident,j(answers),j(grade),95,'{}',now()))
    job=create_job(project_id,'homework_grade',{'set_id':ident,'conversation_id':conversation_id})
    execute("UPDATE jobs SET status='completed',progress=100 WHERE id=?",(job,))
    cause='我把电通量当成了每个点的电场，没有区分整体求和与局部的值。'
    analysis={'items':[{'index':0,'kind':'terminology','confidence':'self_report','cause':'学生自报混淆净通量和各点电场，尚未独立验证。',
        'evidence':[{'source':'questionnaire','quote':cause}],
        'explanation':'净通量把闭合面上有正负的穿出、穿入贡献相加；合计为零可以来自抵消。电场描述某个位置的局部作用，两者不是同一个量。',
        'check':'先分清题目问整体净和还是局部场，再检查边界和条件。'}]}
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,answers_json,'
        'options_json,status,grade_json,analysis_json,causes_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (attempt,ident,project_id,conversation_id,job,homework.version(worksheet),j(answers),
         j({'coding':False,'teaching':{'explanation_style':'clear','output_language':'zh','learning_mode':'deep'}}),
         'completed',j(grade),j(analysis),j([{'index':0,'kinds':['terminology'],'text':cause}]),now(),now()))
    conversations.activate(conversation_id)
    return {'project_id':project_id,'conversation_id':conversation_id,'set_id':ident,'source_id':source,
        'attempt_id':attempt,'submission_id':submission,'source_text':text}
