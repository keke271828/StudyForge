"""Build a local, verbatim comparison; human verdicts remain separate data."""
import base64
import hashlib
import json
from pathlib import Path
import re
import statistics

from scripts.build_teaching_comparison import ROOT, TEMPLATE, inline_script
from scripts.compare_teaching_models import CASES, CANDIDATES


def failure_type(row):
    error=row.get('error','')
    if 'Metered.__init__' in error:return '测试记录器故障；未发出模型请求，不计模型表现'
    if '401' in error or '密钥' in error:return '账号或授权；不计教学能力'
    if '402' in error or '余额' in error:return '账户额度；不计教学能力'
    if '404' in error or 'model_not_found' in error:return '模型不可调用；不计教学能力'
    return '未取得完整正文；不计教学能力'


def build():
    base=ROOT/'build/model-teaching-20261014'
    reviews=json.loads((base/'human-review.json').read_text(encoding='utf-8'))
    candidates={row['key']:row for row in CANDIDATES}
    all_rows=[]
    for folder in (base,ROOT/'build/model-overview-focused-20261014'):
        if not (folder/'results.json').exists():continue
        requests=json.loads((folder/'requests.json').read_text(encoding='utf-8'))
        for row in json.loads((folder/'results.json').read_text(encoding='utf-8')):
            row=dict(row,folder=folder,request=requests[row['case']],variant='focused' if folder!=base else 'baseline')
            all_rows.append(row)
    groups=[]
    for name,case in CASES.items():
        rows=[]; seen=set()
        for row in all_rows:
            if row['case']!=name or row['status']!='completed' or row['variant']!='baseline':continue
            if row['candidate'] in seen:continue
            seen.add(row['candidate'])
            rows.append(display(row,reviews,candidates))
        if rows:
            rows.sort(key=lambda row:row['sha256'])
            groups.append({'case':name,'round':'同一冻结输入','title':case['title'],'question':case['question'],
                           'source':case['source']+'\n\n核对重点：\n'+'\n'.join(case['checks']),'rows':rows})
    focused=[row for row in all_rows if row['variant']=='focused' and row['status']=='completed']
    for candidate in dict.fromkeys(row['candidate'] for row in focused):
        prior=[row for row in all_rows if row['candidate']==candidate and row['case']=='overview' and row['status']=='completed' and row['variant']=='baseline']
        controlled=next((row for row in prior if row['attempt']==4),prior[0])
        pairs=[controlled]+[row for row in focused if row['candidate']==candidate]
        groups.append({'case':candidate+'_focused','round':'同模型概览规则对照','title':candidates[candidate]['label']+'：概览组织调整',
            'question':CASES['overview']['question'],'source':CASES['overview']['source'],
            'rows':[display(row,reviews,candidates) for row in pairs]})
    failures=[{'round':row['variant'],'kind':failure_type(row),**{key:row.get(key) for key in ('sample_id','candidate','case','error','seconds')}}
              for row in all_rows if row['status']!='completed']
    payload={'groups':groups,'count':sum(len(g['rows']) for g in groups),'failures':failures}
    raw=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')
    assets=ROOT/'web/vendor';css=(assets/'katex.css').read_text(encoding='utf-8')
    css=re.sub(r'url\(fonts/([^)]*\.woff2)\)',lambda m:'url(data:font/woff2;base64,'+base64.b64encode((assets/'fonts'/m[1]).read_bytes()).decode()+')',css)
    css=re.sub(r',url\(fonts/[^)]*\) format\("(?:woff|truetype)"\)','',css)
    libraries='\n'.join(inline_script((assets/f).read_text(encoding='utf-8')) for f in ('marked.js','purify.js','katex.js'))
    html=TEMPLATE.replace('__KATEX_CSS__',css).replace('__PAYLOAD__',raw).replace('__LIBRARIES__',libraries).replace('__RENDERER__',inline_script((ROOT/'web/lesson_render.js').read_text(encoding='utf-8')))
    html=html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。','多种实际服务组合，用相同学习任务比较正确性、讲解与耗时。')
    html=html.replace('讲解质量：看真实回答，再选规则','教学模型实测：先看回答，再选模型')
    html=html.replace("'次请求失败'","'条失败或无效记录'")
    html=html.replace('查看未取得正文的失败请求（不计作有效回答）','查看失败与无效记录（含未发出请求的测试记录器故障）')
    start,end=html.index('<div class="notice">'),html.index('</div>',html.index('<div class="notice">'))+len('</div>')
    notice=('全部为本机现有账号的真实调用，使用合成资料、隔离学习数据；未改写原回答，不含私有思考或密钥。'
            '同一任务的基础输入冻结，但Codex有原生代理系统指令，Kimi使用服务默认推理，不能当成严格控制计算预算的模型本体排名。'
            '人工评语来自逐份阅读，未盲评、未经校准；有实质错误的回答不凭文笔获推荐。'
            '初筛每模型每题一次，后续题仅给部分候选；概览规则的两组复测统一API直连，仍不是随机多次抽样。失败另存，不把连接、授权或测试程序故障当智力得分。'
            '耗时包含各接口开销，不代表所有资料或视频的普遍提速；Gemini未取得本机账号授权，不在实测排名中。'
            '概览试验规则没有显示稳定收益，已经撤回；默认教学请求恢复到试验前版本。')
    html=html[:start]+'<div class="notice">'+notice+'</div>'+html[end:]
    html=html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'",'row.metrics')
    html=html.replace('renderLessonText(body,row.text);',"if(row.render_plain){body.append(element('pre','',row.text))}else{renderLessonText(body,row.text)}")
    html=html.replace('份原始回答 · ','个原样展示条目 · ').replace('核对实际请求、用量与原文指纹','核对冻结输入、服务记录与原文指纹')
    html=html.replace('<span class="summary" id="count"></span>','<label for="candidateFilter">显示</label><select id="candidateFilter"><option value="all">全部版本</option></select><span class="summary" id="count"></span>')
    html=html.replace("let showLabels=false;","let showLabels=false;const candidateFilter=document.getElementById('candidateFilter');let activeGroup=-1;")
    html=html.replace("const group=comparison.groups[Number(groupSelect.value)||0];","const groupIndex=Number(groupSelect.value)||0,group=comparison.groups[groupIndex];if(activeGroup!==groupIndex){activeGroup=groupIndex;candidateFilter.replaceChildren(new Option('全部版本','all'));group.rows.forEach((r,i)=>candidateFilter.add(new Option('版本 '+(i+1),String(i))));}")
    html=html.replace("group.rows.forEach((row,index)=>{","group.rows.forEach((row,index)=>{if(candidateFilter.value!=='all'&&candidateFilter.value!==String(index))return;")
    html=html.replace("answerGrid.classList.toggle('solo',group.rows.length===1)","answerGrid.classList.toggle('solo',group.rows.length===1||candidateFilter.value!=='all')")
    html=html.replace('groupSelect.onchange=showGroup;','groupSelect.onchange=showGroup;candidateFilter.onchange=showGroup;')
    html=html.replace('grid-template-columns:repeat(3,minmax(0,1fr))','grid-template-columns:repeat(2,minmax(0,1fr))')
    target=base/'多模型教学质量实际对照.html'
    target.write_text(html,encoding='utf-8')
    valid=[row for row in all_rows if row['status']=='completed']
    recorder_errors=sum('测试记录器故障' in row['kind'] for row in failures)
    summary={'successful_calls':len(valid),'failed_or_invalid_samples':len(failures),
             'recorder_errors_without_model_call':recorder_errors,'model_requests_without_complete_answer':len(failures)-recorder_errors,
             'displayed_samples':payload['count'],
             'groups':len(groups),'models':{key:{'label':spec['label'],
                'successful_calls':len([row for row in valid if row['candidate']==key]),
                'median_seconds':statistics.median([row['seconds'] for row in valid if row['candidate']==key]) if any(row['candidate']==key for row in valid) else None}
                for key,spec in candidates.items()},'new_model_calls_from_report':0,'private_reasoning_included':False}
    (base/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def display(row,reviews,candidates):
    identifier=row['variant']+'/'+row['sample_id']
    if identifier not in reviews:raise ValueError('缺少人工评阅：'+identifier)
    review=reviews[identifier]
    path=row['folder']/row['answer_file'];text=path.read_bytes().decode('utf-8')
    if hashlib.sha256(text.encode()).hexdigest()!=row['answer_sha256']:raise ValueError('原结果指纹不匹配')
    return {'case':row['case'],'arm':identifier,'label':candidates[row['candidate']]['label']+(' · 调整后概览' if row['variant']=='focused' else ''),
            'text':text,'output':str(path),'sha256':row['answer_sha256'],
            'metrics':f"{row['seconds']} 秒（本次单条回答） · {len(text)} 字符 · 推理 {row['effort'] or '服务默认'} · {'原生连接' if row['provider']=='codex' else 'API '+row.get('api_connection_mode','system')} · 尝试 {row['attempt']}",
            'review':review['verdict']+'：'+review['notes'],'render_plain':review.get('render_plain',False),
            'request':{'frozen_request':row['request'],'requested_model':row['requested_model'],'effort':row['effort'],
                       'api_connection_mode':row.get('api_connection_mode','system'),'sample_id':row['sample_id'],
                       'observed':row['observed'],'human_review':review},
            'response_model':row['observed'],'usage':None}


if __name__=='__main__':build()
