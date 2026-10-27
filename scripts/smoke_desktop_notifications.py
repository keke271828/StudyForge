"""Native desktop UI fixture on real HTTP/chat tools, without paid models."""
import os
import json
from pathlib import Path

import uvicorn

from studyforge import conversations, server
from studyforge.ai import save_settings
from studyforge.db import create_project, create_job, execute, j, now, uid, update_job
from studyforge.exporters import export_document
from . import smoke_chat_approvals


def main():
    report=Path(os.environ['STUDYFORGE_PERMISSION_CASE'])
    original=uvicorn.run
    token=uid();os.environ['STUDYFORGE_DESKTOP_TOKEN']=token

    def launch(app,*args,**kwargs):
        info=json.loads(report.read_text(encoding='utf-8'))
        project=create_project('另一个项目 · 后台成果')
        chat=conversations.create(project['id'],'deepseek','approval-model')
        info.update(owner_token=token,output_project=project['id'],output_chat=chat['id'])
        save_settings({'desktop_notifications_sound':False})

        @app.post('/__desktop_notice_test__/output')
        def output():
            job=create_job(project['id'],'generate',{'conversation_id':chat['id']})
            path=export_document('# 通知验收讲解\n\n这份文档已实际导出。','docx','后台成果',uid()+'.docx')
            item=server.add_artifact(project['id'],[],'explanation','docx','后台成果 · 跨项目定位',path,
                                     {'conversation_id':chat['id'],'generation_job_id':job})
            update_job(job,'completed',100,{'artifacts':[item]})
            return item|{'job_id':job}

        @app.post('/__desktop_notice_test__/questionnaire')
        def questionnaire():
            worksheet,attempt=uid(),uid();job=create_job(project['id'],'homework_grade',{'conversation_id':chat['id']})
            questions=[{'index':0,'topic':'加法','question':'计算 2 + 3，并写出你的步骤。','points':100}]
            execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
                    (worksheet,project['id'],'[]','错因问卷通知验收',j(questions),j([{'answer':'5','solution':'2+3=5'}]),1,'assigned',now()))
            analysis={'items':[{'index':0,'confidence':'uncertain','clarification':'作答当时怎样得到 4？'}]}
            execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,answers_json,options_json,status,analysis_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (attempt,worksheet,project['id'],chat['id'],job,'fixture','["4"]','{}','awaiting_causes',j(analysis),now(),now()))
            update_job(job,'paused',70,{'waiting_for_causes':True,'homework_attempt_id':attempt})
            return {'attempt':attempt,'job_id':job}

        @app.post('/__desktop_notice_test__/failure')
        def failure():
            job=create_job(project['id'],'generate',{'conversation_id':chat['id']})
            update_job(job,'failed',35,error='模拟任务失败：用于确认桌面通知，未调用模型。')
            return {'job_id':job}

        mount=next(route for route in app.router.routes if getattr(route,'name',None)=='web')
        app.router.routes.remove(mount);app.router.routes.append(mount)
        report.write_text(j(info),encoding='utf-8')
        original(app,*args,**kwargs)

    uvicorn.run=launch
    smoke_chat_approvals.main()


if __name__=='__main__':main()
