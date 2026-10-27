"""Publish all unsuccessful alignment trials verbatim, with human assessment."""
import hashlib
import json

from scripts.build_teaching_inference_report import ROOT,assets


def main():
    first=ROOT/'build/teaching-alignment-real-20261015-1'
    second=ROOT/'build/teaching-alignment-pairs-real-20261015-1'
    inputs=json.loads((first/'inputs.json').read_text(encoding='utf-8'))
    groups=[];failures=[]
    for key,entry in inputs.items():
        rows=[]
        for folder,arm,label in ((first,'current','现有快速审查'),(first,'candidate','全文主题与例子对齐候选（未采用）'),(second,'candidate','例子结论与理由配对候选（未采用）')):
            result=next(item for item in json.loads((folder/'results.json').read_text(encoding='utf-8')) if item['case']==key and item['arm']==arm)
            if result['status']!='completed':failures.append(result);continue
            path=folder/result['output_file'];text=path.read_bytes().decode('utf-8')
            assert hashlib.sha256(text.encode()).hexdigest()==result['output_sha256']
            if key=='historical_social':
                note='没有指出例子开头问“为什么迟到”，制度却主要解释“为何担心迟到”的衔接不足。原稿后面确实区分了两类问题，也给出孩子生病、地铁故障等同一迟到事件的原因，因此这是教学示范不够贴合的问题，不能据此把整篇判为因果理论全错。两版候选都未稳定改善。'
            elif key=='code_target':
                note='正确指出strip只去首尾空白，不统一大小写，正文与总结两处修正均已应用；代码静态推演Alice/alice为False。现有审查同样检出，不能把结果归功于新增字段。'
                if folder==second:note+='候选修订“必须在strip后统一大小写”又把一种实现办法说得过强；也可以先统一大小写再strip，或按字母比较。更正原错误不代表整段完全正确。'
            elif key=='math_contrast':
                note='保持原文，正确保留形式系数的反例：它反驳“单点非负足够”，不是声称真实向量违反柯西。A=0及A>0的分支均在正文中。不能因对象是形式系数就判跑题。'
            else:
                note=('保持原文，有明确界限的收支类比与匀强场立方体算例都有效；其余四面通量为零，未被错误地说成六面都非零。' if folder==first else
                    '要求补出高斯定律完整等式后才算“接回”，并局部加了一句。补充本身正确，但当前问题允许简明解释，原文已有净通量与内部净电荷的联系及完整反例，把未再写等式定性为实质缺口偏严。没有错判收支类比，却增加了不必要的修订。')
            request=json.loads((folder/(key+'-'+arm+'-requests.json')).read_text(encoding='utf-8'))
            rows.append({'label':label,'text':text,'output':str(path),'sha256':result['output_sha256'],'review':note,
                'metrics':f"{result['seconds']}秒 · {result['model_calls']}次审查组件调用 · 正文原样",
                'request':{'frozen_requests_and_public_responses':request,'result':result}})
        groups.append({'case':key,'title':entry['title'],'round':'同一份现成讲解，三种审查请求',
            'question':entry['question'],'source':entry['source']+'\n\n待审历史讲解或合成讲解：\n'+entry['draft'],'rows':rows})
    count=sum(len(group['rows']) for group in groups)
    html=assets({'groups':groups,'count':count,'failures':failures})
    html=html.replace('讲解质量：看真实回答，再选规则','例子是否回答了问题：两版候选均未采用')
    html=html.replace('原有规则、简短基线、修订规则，以及三种展开方式的实际对照。','保留实际漏检、不必要修订与有用的对照，不把结构化输出当作教学质量保证。')
    html=html.replace("row.seconds+'秒 · 正文 '+row.output_chars+'字符 · 提示 '+row.input_chars+'字符'",'row.metrics')
    notice=('共12次实际DeepSeek Flash / high快速审查组件调用，工具关闭、并发最多2，使用保存的旧AI讲解与构造的对照材料。'
        '没有新增讲解生成、没有后台阅读原书，也不是网页端重放。每格只抽样一次，未盲评，不用于模型排名或速度结论。'
        '两版候选均未进入软件：社会科学例子仍有衔接漏检，第二版对有效电场解释提出了不必要补充，并在代码修正中增加了过强的“必须”措辞。'
        '因此本轮不继续扩充全局教学提示词、默认审查轮次或强制输出表格。'
        '本轮实际软件改进是“理解反馈中选定具体原句补讲”，两端读取原句无需模型或重新解析；它改善定位，不保证导师的后续答案绝对正确。'
        '冻结请求、原始审查JSON和完整正文可逐项展开；不含密钥、私有思考或用户真实学习记录。')
    start=html.index('<div class="notice">');end=html.index('</div>',start)+len('</div>')
    html=html[:start]+'<div class="notice">'+notice+'</div>'+html[end:]
    out=ROOT/'build/teaching-alignment-20261015';out.mkdir(parents=True,exist_ok=True)
    target=out/'例子核查候选实际对照.html';target.write_text(html,encoding='utf-8')
    (out/'人工评阅.json').write_text(json.dumps({'audit_component_calls':12,'groups':len(groups),'samples':count,
        'candidate_policies_adopted':False,'teacher_policy_changed':False,'review_rounds_changed':False,
        'notes':[{'case':g['case'],'label':r['label'],'note':r['review']} for g in groups for r in g['rows']]},ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)


if __name__=='__main__':main()
