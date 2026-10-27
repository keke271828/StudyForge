"""Evidence-gated report for readable failures and correct phone-session handling."""
import hashlib
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/error-help-final-20261026-2'
UI=ROOT/'build/error-help-ui-20261026-4'
OUT=ROOT/'build/error-help-acceptance-20261026'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,label):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(label)+'</a>'
def picture(name,label):return '<figure><img loading="lazy" src="'+html.escape((UI/name).as_uri(),quote=True)+'" alt="'+html.escape(label,quote=True)+'"><figcaption>'+html.escape(label)+'</figcaption></figure>'


def main():
    gate,js,ui,flow=read(GATE/'command.json'),read(GATE/'javascript.json'),read(UI/'ui-report.json'),read(UI/'flow.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and js['exit_code']==0 and js['production_unchanged'] and ui['passed']
    assert not any(gate['tests'][key] for key in ['failure','error','skipped'])
    assert gate['production_after']=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in gate['production_after']}
    assert len(ui['checks'])==7 and ui['external_model_requests']==0 and not ui['console_errors']
    for key in ['jobs','book_jobs','grades','messages','learning_events','model_requests']:assert flow['before'][key]==flow['after'][key],key
    assert flow['after']['model_requests']==0 and flow['after']['requests']=={'model_catalog':4,'stream':1}
    log=(GATE/'javascript.log').read_text(encoding='utf-8');assert re.search(r'# fail 0\b',log)
    node_tests=int(re.search(r'# tests (\d+)',log)[1])
    checks=[
      '失败任务原来即使显示100%，也可能未交付。现在显示“未完成”，提供处理办法入口。',
      '常见的限流、连接、格式、公式、题目检查和权限问题有简短说明；不能确定原因时不会假装已经诊断。',
      '错误详情按需展开。常见密钥和配对码会隐藏；复制被浏览器拒绝时自动选中文字，仍可手动复制。',
      '有效手机连接遇到模型服务401时保持配对；真正失效或被撤销的连接仍要求重新配对。',
      '手机设置弹窗里的错误通知留在当前弹窗内；打开说明后通知收起，避免挡住内容。',
      '聊天发生受控错误后结束等待状态，问题草稿保留；打开帮助不重发模型请求。',
      '查看说明不改变原任务失败状态、评分和学习画像；题目未通过检查时仍不发布。',
    ]
    pairs=[('429 / Too Many Requests','AI 服务暂时限制了请求','等待服务允许再次请求，减少同时处理数，避免连续重试。'),
      ('ConnectError / 证书连接失败','连接模型或资料网站时失败','说明尚不能确定具体原因，再按当前操作检查服务地址或网页。'),
      ('JSONDecodeError','返回内容的格式不完整或不符合要求','先查原任务是否在自动重试，避免重复生成；按实际入口继续或重试。'),
      ('独立解题未通过','这套题还没有通过检查','保留检查问题，调整要求后再生成，不把未核实的题目发布。'),
      ('模型服务401','登录或访问凭证未通过','检查模型账号或API密钥，手机保持配对。'),
      ('手机连接真的失效','这台手机需要重新连接','电脑开启连接，手机重新配对；撤销权限仍然生效。'),
      ('提交前请求答案','提交作业后才能查看解析','保持原来的答案开放规则，不建议更换账号或绕过权限。')]
    rows=''.join('<tr>'+''.join('<td>'+html.escape(value)+'</td>' for value in pair)+'</tr>' for pair in pairs)
    evidence=' · '.join([link(GATE/'command.json','相关回归与源文件指纹'),link(GATE/'javascript.log','JavaScript模块测试'),link(UI/'ui-report.json','实际界面验收'),link(UI/'flow.json','查看帮助前后的任务与评分对照')])
    images=picture('desktop-failed-tasks.png','实际任务卡：失败显示“未完成”，可以查看处理办法')+picture('desktop-rate-limit.png','实际HTTP 429演示：中文说明与下一步操作')+picture('desktop-json-help.png','合成错误用来检查假密钥隐藏和HTML仅按文字显示；不是电脑感染提示')+picture('phone-error-320.png','配对手机页面，320像素宽度：可展开错误原文，内容没有横向溢出')+picture('phone-provider-login.png','模型账号报错时，手机仍留在工作台，无需重新配对')
    text=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>失败提示与手机连接判断验收</title><style>
body{{margin:0;background:#edf3ef;color:#244839;font:17px/1.85 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1150px;margin:auto;padding:30px 20px}}header,section{{padding:26px;background:white;border:1px solid #bbd2c3;border-radius:18px;margin-bottom:22px}}h1{{font-size:31px;line-height:1.45}}h2{{font-size:23px}}a{{color:#176743}}.stats{{display:flex;flex-wrap:wrap;gap:14px}}.stats b{{padding:10px 14px;background:#e8f3e9;border-radius:11px}}.note{{padding:14px 18px;background:#f0f3e9;border-radius:10px}}figure{{margin:24px 0}}img{{max-width:100%;height:auto;border:1px solid #bfd1c4;border-radius:12px}}figcaption{{font-size:14px;color:#4d685b}}figure:nth-last-child(-n+2) img{{max-width:390px}}.table{{overflow:auto}}table{{width:100%;min-width:640px;border-collapse:collapse}}th,td{{padding:13px;border-bottom:1px solid #d4e1d8;text-align:left;vertical-align:top}}th{{background:#e8f3e9}}@media(max-width:650px){{main{{padding:12px}}header,section{{padding:18px}}h1{{font-size:26px}}}}</style><main>
<header><small>StudyForge · 2026-10-26 · 本轮界面改进</small><h1>操作失败时，先知道发生了什么，再知道下一步做什么</h1><p>上一轮改写了日常说明。这一轮把常见失败提示接到真实任务卡和通知中，并修复手机将模型登录失败误当作配对失效的问题。</p><div class="stats"><b>{gate['tests']['total']} 项相关回归通过</b><b>{node_tests} 项JavaScript测试通过</b><b>{js['syntax_files']} 份JavaScript语法检查</b><b>7组实际界面检查</b></div><p>{link(ROOT/'验收最新版.vbs','最新版启动文件：验收最新版.vbs')}</p><p class="note">先从Windows右下角托盘退出旧版，再双击启动文件。软件内按F1可查操作指南。本轮更新在项目文件夹中，尚未重新制作安装包。</p></header>
<section><h2>本轮完成的改进</h2><ol>{''.join('<li>'+html.escape(item)+'</li>' for item in checks)}</ol><div class="table"><table><thead><tr><th>遇到的情况</th><th>现在先看到的说明</th><th>可采取的下一步</th></tr></thead><tbody>{rows}</tbody></table></div><p class="note">真实限流、网络阻断、模型返回格式或题目检查问题仍需按具体原因处理。这轮让失败更容易看懂、可排查，并修复手机连接判断；不会把失败结果当成成功交付。</p></section>
<section><h2>实际检查了什么</h2><p>使用独立学习数据、合成失败任务和真实HTTPS手机配对通道：4次受控HTTP错误、1次受控聊天流错误。界面测试没有请求外部模型。查看说明前后，原任务、原始错误、已保存评分、学习事件和消息数量保持一致；模型请求数仍为0。</p><p>手机检查包含390和320像素窄屏、任务弹窗、设置弹窗、模型401和断连提示。尚未在安卓实机逐项体验，也不以本轮结果证明所有网络或教学模型都无误。</p><p>{evidence}</p></section><section><h2>实际页面</h2>{images}</section></main></html>'''
    OUT.mkdir(exist_ok=True);report=OUT/'失败提示与手机连接判断验收.html';report.write_text(text,encoding='utf-8')
    result={'passed':True,'report':str(report),'python_tests':gate['tests']['total'],'node_tests':node_tests,'syntax_files':js['syntax_files'],'native_groups':len(ui['checks']),'external_model_requests':0,'source_only':True}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'docs/失败提示与手机连接判断-20261026.md').write_text('# 失败提示与手机连接判断\n\n'
        '接续日常界面提示改写，提供共同的中文错误说明、实际处理步骤与可展开原文。打开帮助不调用AI、不自动重试。\n\n'
        '修复模型服务401使手机误退回配对页的问题；网关明确标记自身的连接失效，撤销设备仍有效。手机弹窗内的通知按钮随当前弹窗放置，打开说明后收起通知。\n\n'
        f'当前相关回归 {gate["tests"]["total"]} 项、JavaScript测试 {node_tests} 项、实际界面检查7组通过。\n\n'
        '验收：`build/error-help-acceptance-20261026/失败提示与手机连接判断验收.html`。\n\n'
        '复核脚本：`scripts/verify_error_help.py`；历史证据目录不覆盖，重跑需使用新目录。实际界面：`scripts/run_error_help.py`。上一轮 `verify_ui_copy.py` 保留旧文案快照的核对规则，本轮以当前复核脚本为准。\n\n'
        '本轮没有重新打包；先从托盘退出旧窗口，再双击根目录 `验收最新版.vbs` 打开最新项目代码。\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
