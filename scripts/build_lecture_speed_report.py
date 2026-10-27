"""Saved full-workflow timings and byte-equivalent Word export comparison."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/lecture-speed-review-20261015'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def esc(value):return html.escape(str(value))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    before=read(ROOT/'build/docx-table-profile-20261015-before/results.json')
    after=read(ROOT/'build/docx-table-profile-20261015-after/results.json')
    assert len(before)==len(after)==3
    export=[]
    for old,new in zip(before,after):
        assert (old['rows'],old['columns'],old['content_sha256'])==(new['rows'],new['columns'],new['content_sha256'])
        assert old['docx_member_sha256']==new['docx_member_sha256']
        assert old['grid_accesses']==old['rows']*old['columns'] and new['grid_accesses']==1
        export.append({'rows':old['rows'],'columns':old['columns'],'before_seconds':old['seconds'],
            'after_seconds':new['seconds'],'before_grid_reads':old['grid_accesses'],'after_grid_reads':1,
            'input_equal':True,'xml_and_assets_equal_except_core_properties':True})
    assert sha(ROOT/'studyforge/exporters.py')==sha(ROOT/'build/docx-table-profile-20261015-after/exporters-baseline.py')
    samples=[];requests=0
    old_export=ROOT/'build/docx-table-profile-20261015-before/exporters-baseline.py'
    for suffix,label in [('2','服务默认（未显式指定推理档位）'),('4','明确指定 high，并冻结任务对话')]:
        base=ROOT/f'build/lecture-workflow-profile-20261015-{suffix}';row=read(base/'result.json')
        assert row['status']=='completed' and row['requests']==2 and row['input_pdf_pages']==10
        assert row['pdf_type']=='synthetic_text_pdf_not_scanned' and not row['reasoning_saved'] and not row['production_data_written']
        for file,digest in read(base/'source-hashes.json').items():
            assert sha(old_export if file=='studyforge/exporters.py' and suffix=='2' else ROOT/file)==digest,file
        for trace in row['traces']:
            assert trace['status']==200 and trace['finish']=='stop' and trace['requested_model']=='deepseek-flash'
            usage=trace['usage'];assert usage['prompt_tokens']+usage['completion_tokens']==usage['total_tokens']
            assert 0<=usage['reasoning_tokens']<=usage['completion_tokens']
            assert trace['effort']==('high' if suffix=='4' else None)
        source_chars=sum(item['characters'] for item in row['source_reading'])
        assert len(row['source_reading'])==1 and row['source_reading'][0]['segments']==10
        file=f'完整流程{suffix}_原始讲解_需核对.docx';shutil.copy2(row['artifacts'][0]['path'],OUT/file)
        sample={'label':label,'wall_seconds':row['wall_seconds'],'source_characters':source_chars,
            'phases':row['phases'],'model_requests':row['requests'],
            'model_elapsed_ms':sum(span['duration_ms'] for span in row['spans'] if span['resource']=='model'),
            'export_elapsed_ms':sum(span['duration_ms'] for span in row['spans'] if span['resource']=='document_export'),
            'provider':[{'reasoning_tokens':t['usage']['reasoning_tokens'],
                'visible_tokens':t['visible_tokens_from_provider'],'first_content_s':t['first_content_s'],
                'consumer_seconds':t['consumer_seconds'],'requested_effort':t['effort']} for t in row['traces']],
            'lesson_file':file,'lesson_sha256':sha(OUT/file)}
        samples.append(sample);requests+=row['requests']
    failed=read(ROOT/'build/lecture-workflow-profile-20261015-1/result.json')
    assert failed['status']=='failed' and failed['requests']==0
    cases=[]
    for file in ('build/docx-table-export-regression-20261015.xml','build/lecture-speed-guide-20261015.xml'):
        rows=ET.parse(ROOT/file).findall('.//testcase')
        assert not any(case.find(tag) is not None for case in rows for tag in ('failure','error','skipped'))
        cases.extend(rows)
    ids={(case.get('classname'),case.get('name')) for case in cases};assert len(ids)==len(cases)
    ui=read(ROOT/'build/review-hints-ui-20261015-2/ui-report.json')
    assert ui['passed'] and len(ui['checks'])==4 and ui['external_model_requests']==ui['controlled_model_calls']==0
    assert not ui['console_errors']
    names={'generation_input_records':'原文读取／版本核对（每次）','source_digest':'原文组装与图像准备',
        'generate_explanation':'讲解撰写','review_explanation':'快速核查','finish_explanation':'总结整理'}
    table=''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in (r['rows'],r['columns'],
        f"{r['before_seconds']:.3f} 秒",f"{r['after_seconds']:.3f} 秒",f"{r['before_grid_reads']} → 1",'相同'))+'</tr>' for r in export)
    sections=''
    for sample in samples:
        rows=''.join(f'<tr><td>{esc(names[p["name"]])}</td><td>{p["seconds"]:.3f} 秒</td></tr>' for p in sample['phases'])
        tokens=''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in
            ('撰写' if i==0 else '核查',p['requested_effort'] or '未显式指定',p['reasoning_tokens'],p['visible_tokens'],
             f"{p['first_content_s']:.2f} 秒",f"{p['consumer_seconds']:.3f} 秒"))+'</tr>' for i,p in enumerate(sample['provider']))
        sections+=f'''<section><h2>完整流程：{esc(sample['label'])}</h2><p>总耗时 {sample['wall_seconds']:.2f} 秒 · 2 次模型请求 · 原文 {sample['source_characters']} 字符，分布在 10 个内容较少的 PDF 页面。</p><div class="table"><table><thead><tr><th>阶段</th><th>用时</th></tr></thead><tbody>{rows}<tr><td>Word 本机排版（调度记录）</td><td>{sample['export_elapsed_ms']/1000:.3f} 秒</td></tr></tbody></table></div><h3>服务用量与正文等待</h3><div class="table"><table><thead><tr><th>请求</th><th>发送的推理档位</th><th>推理 token</th><th>正文 token</th><th>首个正文等待</th><th>片段上层消费</th></tr></thead><tbody>{tokens}</tbody></table></div><p>模型名额占用共 {sample['model_elapsed_ms']/1000:.2f} 秒。阶段可能包含子阶段，不应把表中各行相加当作总时长；名额时间也不是服务端纯推理时间。</p><p><a href="{sample['lesson_file']}">下载本次原始实验讲解 Word（需核对）</a></p></section>'''
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>讲解全流程计时与 Word 表格提速</title><style>*{box-sizing:border-box}body{margin:0;background:#efeee7;color:#203d34;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1300px;padding:32px 22px 64px;margin:auto}header,section{background:#fffefa;border:1px solid #d8dfd1;border-radius:22px;padding:28px;margin-bottom:22px}h1{font-size:clamp(28px,4vw,42px);line-height:1.35;margin:8px 0 18px}h2{font-size:24px;margin-top:0}.eyebrow{font-size:12px;letter-spacing:.15em;color:#587164}.notice{padding:16px 20px;border-radius:14px;background:#e8eee2}.caution{background:#f5ecda;color:#66522b}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:12px 14px;border-bottom:1px solid #dce3d6;text-align:left}th{white-space:nowrap;background:#eff2e8}td{min-width:75px}a{color:#21674f}li{margin:7px 0}footer{font-size:13px;color:#52675d}@media(max-width:600px){main{padding:14px 10px 38px}header,section{padding:20px 16px;border-radius:16px}h2{font-size:21px}}</style></head><body><main>
    <header><div class="eyebrow">STUDYFORGE · 2026-10-15 · 隔离数据实际计时</div><h1>把模型等待与本机排版分开看</h1><p>完成两次真实讲解工作流，并修复 Word 大表格的重复遍历。本轮保留教学提示词、模型和生成内容，没有为了获得更短时间降低推理或减少核查。</p><p class="notice">4 次实际模型请求 · TEST_COUNT 项相关程序检查通过 · 4 项实际电脑／配对手机尺寸界面检查通过 · 0 次界面验收模型请求</p></header>
    <section><h2>已修复：Word 大表格导出</h2><p>原程序每填写一个单元格，python-docx 都会重新构建整张表的单元格列表。现在每张新表只构建一次，在本张表内复用节点，不跨文档缓存。大表格避免了随单元格数平方增长的遍历。</p><div class="table"><table id="exports"><thead><tr><th>行数（含表头）</th><th>列数</th><th>优化前</th><th>优化后</th><th>整表遍历次数</th><th>正文／公式／样式等文件内容</th></tr></thead><tbody>EXPORT_ROWS</tbody></table></div><p>三组使用相同内容，均包含中文、加粗、原文引用、原生公式和系统性总结。Word 包中的全部条目逐字节校验相同，仅排除文档核心属性元数据；未以截图相似替代内容核对。不是 Word 应用视觉验收。每组每版一次，预热依赖后计时。</p><p class="notice caution">大型合成表格的 12.60 → 0.25 秒不能解释模型生成等待，也不能套用成整份讲解的通用提速比例。实际讲解没有大表格时，收益较小。</p></section>
    PROFILE_SECTIONS
    <section><h2>样本边界与人工复看</h2><p>这里的 PDF 是同一个极限唯一性主题的十段短材料，每页只放一段，不是普通十页密集教材或扫描书。第一次完整运行继承对话默认推理，发出的请求未指定 effort；不能把它记作 high。第二次明确保存 high 与任务对话快照。两次输出长度、缓存、连接和服务状态仍可能不同，不用它们给默认档位与 high 排速度名次。</p><p>第一份讲解的主要证明讲出了半径选择、开端点和统一门槛，快速核查耗时较长并返回通过。但人工复看发现：改成闭区间的扩展仍用了两侧严格不等式，端点估计应先写为 ≤；另有一个 AI 自述引用块没有来源定位。已有定位检查把后者标在正文中。核查“通过”不能当全文正确性认证。</p><p>high 样本在同一次核查中发现不等式方向、邻域端点、直接证明收尾和内部指路四项问题，程序应用五处局部替换，并保留“未再次独立复核”说明。但最终稿仍有表达问题：“为什么别无选择”与随后给出的替代矛盾；“等半径让边界合并”漏掉半径取一半的条件；“半径不等时分界点不是中点”说得过强。第二处原文引用也保留核对提示。这些原始输出不是全部正确的正式教材。</p><p>开发夹具准备曾因缺少会话 ID、错误设置快照字段而失败，两次均未发模型请求；没有将这些准备失败混入模型速度或成功样本。</p></section>
    <section><h2>软件内说明与验收</h2><ul><li>电脑和手机生成入口提示：审查档位控制额外核查次数，不自动降低模型推理强度，单次高推理核查也可能较久。</li><li>零基础指南说明如何看“耗时详情”，并优先用已完成正文的“另存格式”，避免重复生成。</li><li>实际桌面与配对 HTTPS 手机尺寸界面验证：说明可见、模型和推理选择不变、帮助可读、零模型请求。未使用真实安卓设备。</li><li>相关程序检查覆盖原文读取、公式、表头、空白补齐、跨表节点、旧成果另存、媒体成果和指南访问。</li></ul><p>本轮没有证明全软件卡顿、并行内存或长视频／扫描 OCR 提速，也没有重新打包。生产用户资料与设置不由实验脚本改动。</p><p><a href="最终核验记录.json">最终核验记录</a> · <a href="阶段与导出对照数据.json">阶段与导出对照数据</a></p></section><footer>测速保存计时、状态、服务 token 计数与指纹。模型思考正文和凭据不写入测速结果；原始最终讲解仅作为合成 QA 资料。</footer></main></body></html>'''
    page=page.replace('TEST_COUNT',str(len(ids))).replace('EXPORT_ROWS',table).replace('PROFILE_SECTIONS',sections)
    target=OUT/'讲解全流程计时与Word表格提速.html';target.write_text(page,encoding='utf-8')
    (OUT/'阶段与导出对照数据.json').write_text(json.dumps({'export':export,'workflow':samples},ensure_ascii=False,indent=2),encoding='utf-8')
    files=('studyforge/exporters.py','tests/test_nested_math_exports.py','web/app.js','web/mobile/index.html','web/mobile/sw.js',
        'web/help/guide.html','scripts/profile_docx_table_export.py','scripts/profile_lecture_workflow.py',
        'scripts/smoke_review_hints_ui.js','scripts/build_lecture_speed_report.py','scripts/preview_lecture_speed_report.js',
        'docs/首次讲解计时与Word表格提速验收.md','docs/当前功能状态与待验收清单.md')
    record={'passed':True,'real_model_requests':requests,'full_workflows':2,'source_pdf_pages':10,
        'source_is_dense_or_scanned_pdf':False,'word_content_members_equal':True,'deduplicated_program_checks':len(ids),
        'actual_ui_checks':4,'ui_model_requests':0,'model_or_teaching_policy_changed':False,
        'reasoning_text_saved':False,'production_settings_written':False,'html_sha256':sha(target),
        'source_sha256':{file:sha(ROOT/file) for file in files},'lesson_files':{s['lesson_file']:s['lesson_sha256'] for s in samples}}
    (OUT/'最终核验记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in record.items() if key not in ('source_sha256','lesson_files')},ensure_ascii=True))


if __name__=='__main__':main()
