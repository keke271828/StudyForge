"""Verify saved measurements and build a local, content-free speed report."""
import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/deepseek-speed-review-20261015'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def seconds(value):return '未报告' if value is None else f'{value:.2f} 秒'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    first=ROOT/'build/deepseek-speed-20261015-1';second=ROOT/'build/deepseek-connection-speed-20261015-1'
    rows=read(first/'results.json');connections=read(second/'results.json');config=read(first/'configuration.json')
    assert len(rows)==6 and len(connections)==4
    for row in rows+connections:
        assert row['status']=='completed' and len(row['http_attempts'])==1
        trace=row['http_attempts'][0];assert trace['status']==200 and trace['finish']=='stop' and trace['error'] is None
        assert trace['usage']['prompt_tokens']+trace['usage']['completion_tokens']==trace['usage']['total_tokens']
        assert trace['headers_s']<=trace['first_content_s']<=trace['last_content_s']<=trace['end_s']<=row['wall_s']
    for case in ('short_off','short_high','audit_high'):
        pair=[row for row in rows if row['case']==case]
        assert {row['arm'] for row in pair}=={'software','direct'}
        assert len({row['http_attempts'][0]['body_sha256'] for row in pair})==1
    assert len({row['http_attempts'][0]['body_sha256'] for row in connections})==1
    for path,digest in config['source_hashes'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    tests=ET.parse(ROOT/'build/deepseek-speed-checks.xml').findall('.//testcase')
    assert len(tests)==8 and not any(any(case.find(tag) is not None for tag in ('failure','error','skipped')) for case in tests)
    audit=next(row for row in rows if row['case']=='audit_high' and row['arm']=='software');metrics=audit['http_attempts'][0]
    ratio=metrics['usage']['reasoning_tokens']/metrics['usage']['completion_tokens']
    total=sum(row['http_attempts'][0]['usage']['total_tokens'] for row in rows+connections)
    names={'short_off':'短讲解 · 关闭思考','short_high':'短讲解 · 高推理','audit_high':'核查任务 · 高推理'}
    lines=[];export=[]
    for row in rows:
        trace=row['http_attempts'][0];usage=trace['usage']
        entry={'sample':names[row['case']],'path':'软件客户端' if row['arm']=='software' else '直接HTTP',
            'wall_s':row['wall_s'],'headers_s':trace['headers_s'],'first_reasoning_s':trace['first_reasoning_s'],
            'first_content_s':trace['first_content_s'],'output_tokens_including_reasoning':usage['completion_tokens'],
            'reasoning_tokens':usage.get('reasoning_tokens'),'visible_tokens':trace['visible_tokens_from_provider'],
            'prompt_cache_hit_tokens':usage.get('prompt_cache_hit_tokens'),'consumer_seconds':trace['consumer_seconds']}
        export.append(entry)
        cells=[entry['sample'],entry['path'],seconds(entry['wall_s']),seconds(entry['headers_s']),seconds(entry['first_content_s']),
            str(entry['reasoning_tokens']) if entry['reasoning_tokens'] is not None else '未分项（思考关闭）',
            str(entry['visible_tokens']) if entry['visible_tokens'] is not None else '未单列',str(entry['prompt_cache_hit_tokens'])]
        lines.append('<tr>'+''.join('<td>'+html.escape(value)+'</td>' for value in cells)+'</tr>')
    connection_lines=[]
    for row in connections:
        trace=row['http_attempts'][0]
        connection_lines.append(f'<tr><td>{row["sample"]}</td><td>{"沿用环境代理" if row["mode"]=="system" else "直接连接"}</td><td>{row["wall_s"]:.2f} 秒</td><td>{trace["headers_s"]:.2f} 秒</td></tr>')
    averages={mode:{'wall_s':statistics.mean(row['wall_s'] for row in connections if row['mode']==mode),
        'headers_s':statistics.mean(row['http_attempts'][0]['headers_s'] for row in connections if row['mode']==mode)} for mode in ('system','direct')}
    with (OUT/'逐请求指标.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(export[0]));writer.writeheader();writer.writerows(export)
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepSeek 实际速度诊断</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f2f0e8;color:#1f3d35;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1400px;padding:36px 24px 70px;margin:auto}header,section{background:#fffefa;border:1px solid #d7dfd3;border-radius:22px;padding:28px;margin-bottom:24px}h1{font-size:clamp(28px,4vw,42px);line-height:1.35;margin:8px 0 20px}h2{margin-top:0;font-size:25px}.eyebrow{font-size:12px;letter-spacing:.16em;color:#526d61;font-weight:700}.badges{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}.badges span{padding:7px 14px;background:#e6eee3;border-radius:100px}.notice{padding:16px 20px;background:#e6eee3;border-radius:14px}.caution{background:#f4eddb;color:#66512b}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:13px 12px;text-align:left;border-bottom:1px solid #dce1d6;vertical-align:top}th{white-space:nowrap;background:#eef2e8}td{min-width:85px}.phases{display:grid;grid-template-columns:1fr 3fr 1fr;gap:10px;margin:20px 0}.phase{padding:18px;border-radius:14px;background:#e6eee3}.phase strong{display:block;font-size:26px}.phase.reason{background:#d5e6d9}.phase.output{background:#f4eddb}a{color:#17634c;text-underline-offset:4px}li{margin:9px 0}code{font-size:.9em;overflow-wrap:anywhere}footer{font-size:13px;color:#526d61}@media(max-width:700px){main{padding:16px 10px}header,section{padding:21px}.phases{grid-template-columns:1fr}h2{font-size:22px}}</style></head>
    <body><main><header><div class="eyebrow">STUDYFORGE · 2026.10.15 · REAL API DIAGNOSIS</div><h1>慢在哪里：推理量、等待与多轮请求</h1><p>本轮测量 DeepSeek Flash 的实际流式响应，使用同一份请求分别走软件客户端和直接 HTTP；另对比关闭思考、高强度思考及冷连接方式。</p><div class="badges"><span>10 次真实请求</span><span>8 项计量检查通过</span><span>请求体指纹逐对相同</span><span>输入／生成合计 TOTAL_TOKENS token</span></div><p class="notice">本次证据支持：长核查耗时主要伴随大量推理和响应前等待，未测出客户端逐字消费造成的明显瓶颈。它不是全软件或网页端的速度排名。</p></header>
    <section><h2>一条“只返回52字符”的核查，实际生成了什么</h2><p>该条软件请求总耗时约60.82秒。服务报告生成7423 token，其中7406为推理token、17为正文token，推理占生成量约99.77%。只看最终正文长度会严重低估本轮工作量。</p><div class="phases"><div class="phase"><strong>15.67秒</strong>发送到首个推理片段</div><div class="phase reason"><strong>45.01秒</strong>首个推理片段到首个正文片段</div><div class="phase output"><strong>0.03秒</strong>首个到末个正文片段</div></div><p>上层消费已到达片段的累计计时约0.05秒。它不含网络等待与全部协议解析，不能当作软件全部CPU时间；但本次没有显示逐片段处理占掉几十秒。</p><p>长核查中，包含推理的输出接收速率约165–170 token/秒。这里用服务报告的生成token数除以首末生成片段之间的到达时间，是近似接收速率，不是服务端纯计算速度。17个正文token的到达窗口过短，不用它单独评价吞吐率。</p><p>Token字段按 <a href="https://api-docs.deepseek.com/api/create-chat-completion/">DeepSeek 官方 Chat Completions 文档</a>解释；缺失的分项保留未知，不冒充为零。输入与生成的总token数含缓存记录，不能直接换算费用。</p></section>
    <section><h2>六次逐请求对照</h2><div class="table"><table><thead><tr><th>任务</th><th>路径</th><th>总耗时</th><th>收到响应头</th><th>首个正文</th><th>推理token</th><th>正文token</th><th>输入缓存命中token</th></tr></thead><tbody>ROWS</tbody></table></div><p>每一组请求体完全相同，但每次生成长度、推理量、缓存命中和服务状态仍会变化。短高推理样例中软件路径比直接HTTP更快；长核查相反，因此不能把一对总耗时的差值全部归因于客户端。长核查两次缓存命中分别为256与3584 token，收到响应头时间也相差约15秒。</p><p>所有本机模型名额排队都只有几十毫秒；本次没有主动制造并发或资源紧张，因此不能代表你多任务运行时的排队情况。</p></section>
    <section><h2>四次新连接对照</h2><p>相同短请求，关闭思考，每次新建连接，顺序为：沿用环境 → 直连 → 直连 → 沿用环境。四次请求体指纹一致。</p><div class="table"><table><thead><tr><th>次序</th><th>连接方式</th><th>总耗时</th><th>收到响应头</th></tr></thead><tbody>CONNECTION_ROWS</tbody></table></div><p>本次两组平均总耗时：沿用环境4.42秒、直连2.29秒。沿用环境的首次响应等待较长，说明这次测试中的代理／连接路径值得关注；不能用四次样本推广所有网络环境。</p><p class="notice caution">测试进程存在环境代理。另查Windows用户与系统级HTTP_PROXY／HTTPS_PROXY／ALL_PROXY环境变量，均未设置；这不等于Windows没有其他代理配置，也不能证明你平常从桌面启动的软件继承了同一代理。未修改用户生产网络设置。</p></section>
    <section><h2>诊断结论与后续优先级</h2><ol><li><strong>优先减少重复的高强度核查。</strong>本次核查的生成量绝大多数用于推理。先对照合并重叠检查或分配不同推理预算的质量，再决定采用；不据此把导师默认改成关闭思考。</li><li><strong>把逐请求用量与首字等待保留到任务记录。</strong>历史118秒核查没有这些分项，不能靠本次补测反推它当时每一秒做了什么。当前诊断脚本不等于软件已增加实时token仪表。</li><li><strong>确认实际运行环境后再选连接方式。</strong>软件已有API连接方式设置，本次仅在隔离测试目录对照，没有改用户全局配置。</li><li><strong>改善等待期间的可见进度。</strong>流式显示可以更早显示可读内容；它本身不让远端模型少算或加快计算。</li></ol><p>当前DeepSeek协议中medium、high、xhigh都映射到high，这与兼容接口说明一致；把高改成中不一定降低推理预算。“快速审查”控制审查轮数，与模型推理档位分开，快速加high仍可能长时间思考。</p><p>本轮只有单请求、合成讲解和既有合成核查材料，没有测量长视频、本机转录、繁忙多任务、真实安卓或网页端。每格一次，连接方式各两次，缓存与生成长度未固定，不做显著性或整体质量提升结论。</p><p><a href="逐请求指标.csv">下载六次请求指标CSV</a> · <a href="最终核验记录.json">查看核验记录</a></p></section><footer>测试目录与生产资料分离；仅保存计时、计数、状态与内容指纹。没有保存密钥、请求正文、模型思考正文或最终回答正文。软件核心源码指纹保持一致。</footer></main></body></html>'''
    page=page.replace('六次逐请求对照</h2>','六次逐请求对照</h2><p>本表六次请求均沿用同一测试环境连接配置。“直接HTTP”指绕过软件Agent状态循环，仍沿用环境代理；后面的“直接连接”网络试验才忽略环境代理。软件路径也不包含完整工作台界面或文件处理。</p>')
    page=page.replace('TOTAL_TOKENS',str(total)).replace('CONNECTION_ROWS',''.join(connection_lines)).replace('ROWS',''.join(lines))
    target=OUT/'DeepSeek实际速度诊断.html';target.write_text(page,encoding='utf-8')
    record={'passed':True,'real_requests':10,'reported_total_tokens':total,'diagnostic_checks':len(tests),
        'request_body_pairs_verified':True,'core_sources_unchanged':True,'production_settings_written':False,
        'reasoning_text_saved':False,'credentials_saved':False,'sample_output_text_saved':False,
        'audit_software':{'wall_s':audit['wall_s'],'reasoning_tokens':metrics['usage']['reasoning_tokens'],
            'visible_tokens':metrics['visible_tokens_from_provider'],'reasoning_fraction':ratio,'consumer_seconds':metrics['consumer_seconds']},
        'connection_means':averages,'html_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'limitations':['One sample per client/thinking cell; two per network mode.','Different cache hits, server state and generated lengths.',
            'Test process has proxy environment; ordinary desktop process environment not established.',
            'Receive throughput is not pure server inference rate.','Not a full workflow, video, RAM or concurrent performance benchmark.'],
        'source_sha256':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            'scripts/diagnose_deepseek_speed.py','tests/test_speed_probe.py')}}
    (OUT/'最终核验记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in record.items() if key not in ('source_sha256','limitations','connection_means')},ensure_ascii=True))


if __name__=='__main__':main()
