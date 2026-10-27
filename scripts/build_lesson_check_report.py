"""Student-only review page. Never publish private solutions or model reasoning."""
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/lesson-check-review-20261015'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    runs=[];cards=[];checks=[]
    notes={
        'math':('极限唯一性与开邻域',
            '第一版三段任务较长，评分文本中存在一处错误可能覆盖整个小问的冲突。审查已删除首稿题面中的答案暗示，但不能据此认定其他细节全部正确。',
            '新版改为开／闭区间条件对照与解释，评分拆成独立分项。它更贴合“等号为何可取”的卡点，但一般符号与求完整条件仍有负担，不宜把“小问较少”直接等同于更容易。'),
        'causal':('大样本关联与因果识别',
            '第一版同时要求误差、显著性、替代解释和研究设计，超过一次小检查的需要。私有解析还加入题面未保证的抽样前提与多余方法。',
            '新版改为原调查判断与随机分组对照，去掉额外研究设计。私有解析的统计显著措辞、有限样本随机平衡，以及对假设结果的表达仍应更严谨；这份试验不能当完全可靠的评分标准。')}
    for name,label in (('lesson-check-real-20261015-2','第一版'),('lesson-check-real-20261015-3','收紧后')):
        folder=ROOT/'build'/name
        results=read(folder/'results.json');runs.append({'folder':name,'results':results})
        assert len(results)==2
        for result in results:
            assert result['status']=='completed'
            text=(folder/result['student_file']).read_text(encoding='utf-8')
            assert hashlib.sha256(text.encode()).hexdigest()==result['student_sha256']
            student=read(folder/(result['case']+'-student.json'))
            assert 'solutions' not in student and len(student['questions'])==1
            context=read(folder/(result['case']+'-context.json'))
            link='../'+name+'/'+quote(Path(result['word_file']).name)
            cards.append((result['case'],label,result,text,link,context['student_question']))
            checks.append({'case':result['case'],'version':label,'file':str(folder/result['student_file']),
                'sha256':result['student_sha256'],'student_only':True,'verbatim':True})
    groups=[]
    for key,(title,before,after) in notes.items():
        columns=[]
        for case,label,row,text,link,question in cards:
            if case!=key:continue
            note=before if label=='第一版' else after
            columns.append(f'''<article class="sample" data-case="{key}" data-version="{html.escape(label)}">
              <header><span>{label}</span><small>{row['component_calls']} 次请求 · {row['seconds']:.2f} 秒</small></header>
              <p class="review">{html.escape(note)}</p>
              <pre class="verbatim">{html.escape(text)}</pre>
              <a class="download" href="{link}">打开该版无答案 Word 题单</a></article>''')
        question=next(card[5] for card in cards if card[0]==key)
        groups.append(f'<section class="group" id="{key}"><h2>{title}</h2><p class="question">合成学生疑问：{html.escape(question)}</p><div class="columns">'+''.join(columns)+'</div></section>')
    calls=sum(row['component_calls'] for run in runs for row in run['results'])
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>补讲后单题理解检查 · 实际对照</title>
    <style>*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f3f1e9;color:#173e35;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1460px;margin:auto;padding:40px 26px 80px}h1{font-size:clamp(26px,4vw,43px);line-height:1.4;margin:6px 0 16px}h2{font-size:27px;margin:0 0 14px}.hero,.guide,.limits{background:#fffefa;border:1px solid #d8dfd1;border-radius:24px;padding:30px;margin-bottom:24px}.eyebrow{letter-spacing:.16em;font-size:12px;color:#547064;font-weight:700}.stats{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}.stats span,nav a{border-radius:100px;background:#e5eee3;padding:8px 14px}nav{display:flex;flex-wrap:wrap;gap:10px}a{color:#17664d;text-decoration-thickness:1px;text-underline-offset:4px}nav a{text-decoration:none}.guide ol{padding-left:25px}.notice,.question{padding:16px 20px;background:#e7f0e7;border-radius:15px}.group{margin:42px 0}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}.sample{min-width:0;background:#fffefa;border:1px solid #d8dfd1;border-radius:20px;padding:24px}.sample header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;border-bottom:1px solid #d8dfd1;padding-bottom:15px;font-size:20px;font-weight:700}.sample small{font-size:13px;font-weight:400;color:#536b60}.review{padding:15px;background:#f4eddb;border-radius:12px;color:#5f4c27;font-size:14px}.verbatim{font:15px/1.9 "Segoe UI","Microsoft YaHei",sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;color:#243e36;margin:24px 0}.download{display:inline-block;background:#e5eee3;border-radius:10px;padding:8px 14px}li{margin:9px 0}details{margin-top:18px}summary{cursor:pointer;font-weight:600}.pictures{display:grid;grid-template-columns:1fr 300px;gap:20px;align-items:start}.pictures img{max-width:100%;height:auto;border:1px solid #d8dfd1;border-radius:12px}footer{font-size:13px;color:#526b60;margin-top:30px}@media(max-width:900px){main{padding:22px 14px}.columns,.pictures{grid-template-columns:1fr}.hero,.guide,.limits,.sample{padding:22px}.pictures img{max-height:650px;object-fit:contain}}
    </style></head><body><main><header class="hero"><div class="eyebrow">STUDYFORGE · 2026.10.15 · LOCAL REVIEW</div><h1>补讲之后，检查一个真正的理解</h1><p>完成导师补讲后，由你主动选择做一题。下面保留两轮真实模型的完整学生题面，方便比较任务是否聚焦；没有发布私有答案、评分内容或隐藏推理。</p>
    <div class="stats"><span>2 个学科</span><span>2 轮完整流程</span><span>COMPONENT_CALLS 次真实组件请求</span><span>DeepSeek Flash / high</span></div>
    <p class="notice">这是合成旧讲解和合成补讲后的测试；不是用户真实作答。两轮请求先后执行，各样例只运行一次，未做盲评。题面与私有参考的人工评价分开，不能以“任务成功”替代“教学完全正确”。</p><nav><a href="#how">怎么验收</a><a href="#math">数学对照</a><a href="#causal">社会科学对照</a><a href="#limits">结果与边界</a></nav></header>
    <section id="how" class="guide"><h2>在软件中怎样使用</h2><ol><li>打开最新版源码入口，回到一份已生成讲解的原对话。</li><li>填写“理解反馈／哪里没懂”，可选章节和原句，提交并请导师补讲。</li><li>补讲完成后点击“针对本次补讲检查 1 题”。不点击就不出题。</li><li>后台生成时可继续聊天、暂停或继续；完成后点“查看这道检查题”，完整作答后再看解析及批改。</li></ol><p>同一依据重复点击复用同一任务或题单；当前另外勾选的资料不会被小检查改动。题单按原项目、原对话归档。</p><details><summary>查看实际桌面与配对 HTTPS 手机界面</summary><p>这两张界面图采用受控模型响应验证交互，与下方真实模型题面是两组测试。</p><div class="pictures"><img alt="桌面打开对应单题作业" src="../lesson-check-ui-20261015-2/desktop-one-question.png"><img alt="配对手机理解反馈入口" src="../lesson-check-ui-20261015-2/phone-check-ready.png"></div></details></section>
    GROUPS
    <section class="limits" id="limits"><h2>我对结果的判断</h2><p>收紧后的题目更集中，评分也成为可校验的分项数组。这次两份题单均以4次组件请求完成，第一轮均因修订使用8次。实际等待仍取决于服务响应，不能把请求减半直接当成耗时减半。</p><p>数学样例仍需要一般区间推导；社会科学参考的统计措辞和假设边界仍应更严谨。当前改进是让问题更容易暴露、让任务能对准具体卡点，并没有让模型免于错误。实际教学与评分仍需继续抽样核对。</p><ul><li>只主动选择时才启动；阅读和生成题目不新增测验分数。</li><li>题单生成、暂停续接、答案隔离、完整提交后先导出参考已走真实程序链路。</li><li>手机界面为真实配对 HTTPS 的手机尺寸 Electron，真实安卓生命周期仍需设备验收。</li><li>本轮没有长视频／整本书计时、全软件内存测量或长期学习成效试验。</li></ul></section><footer>本页零外部依赖。四份题面按文件逐字保留；修改任务要求后没有删除第一轮结果。下载的是无答案 Word，私有审查内容不随页面发布。</footer></main></body></html>'''
    page=page.replace('COMPONENT_CALLS',str(calls)).replace('GROUPS','\n'.join(groups))
    target=OUT/'补讲后单题理解检查实际对照.html';target.write_text(page,encoding='utf-8')
    result={'passed':True,'student_samples':len(checks),'groups':len(groups),'real_component_calls':calls,
        'verbatim_student_outputs':True,'private_solutions_published':False,'samples':checks,
        'html_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUT/'页面静态核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='samples'},ensure_ascii=True))


if __name__=='__main__':main()
