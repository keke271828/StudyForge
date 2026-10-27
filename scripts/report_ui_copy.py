"""Only publish the UI-copy report after regression and real UI receipts pass."""
import hashlib
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
GATE=ROOT/'build/ui-copy-final-20261026'
UI=ROOT/'build/ui-copy-ui-20261026-3'
AUDIT=ROOT/'build/ui-copy-audit-20261026-2'
OUT=ROOT/'build/ui-copy-acceptance-20261026'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,title):return '<a href="'+html.escape(path.as_uri(),quote=True)+'">'+html.escape(title)+'</a>'
def image(name,label):return '<figure><img loading="lazy" src="'+html.escape((UI/name).as_uri(),quote=True)+'" alt="'+html.escape(label,quote=True)+'"><figcaption>'+html.escape(label)+'</figcaption></figure>'


def main():
    gate,copy,js,ui=read(GATE/'command.json'),read(GATE/'copy-contracts.json'),read(GATE/'javascript-rechecked.json'),read(UI/'ui-report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and ui['passed'] and js['exit_code']==0
    assert all(gate['tests'][key]==0 for key in ('failure','error','skipped'))
    assert gate['production_after']=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in gate['production_after']}
    assert len(ui['checks'])==7 and ui['external_model_requests']==0 and ui['controlled_model_requests']==1
    assert not ui['console_errors'] and copy['protected_control_values_and_recognizers_unchanged']
    desktop_log=(GATE/'desktop-tests-rechecked.log').read_text(encoding='utf-8')
    assert re.search(r'# fail 0\b',desktop_log) and re.search(r'# cancelled 0\b',desktop_log)
    node_tests=int(re.search(r'# tests (\d+)',desktop_log)[1])
    edits=sum(sum(row['count'] for row in read(path)['changes']) for path in AUDIT.glob('wording-changes*.json'))
    changed=len(copy['changed_files']);before=len(ui['before_notice']);after=len(ui['after_notice'])
    examples=[
      ('执行优先级／前台阅读','何时阅读／优先开始 · 可继续聊天','告诉你什么时候会开始，不暗示必须停在这个页面。'),
      ('结构索引','先梳理概念和重点','说明会得到什么；详细阅读另有选项。'),
      ('几百字挤在阅读按钮下','两句下一步提示；其他说明点开再看','阅读顺序、模型、页码和用量规则仍保留。'),
      ('所选节点已有任务','说明正在处理哪些章节，并提供“查看正在进行的阅读”','可以直接找到原任务，暂停的任务可继续，避免重复开始。'),
      ('上传／解析／通读容易混淆','先保存文件 → 选需要的页或文字 → 提取内容 → 按需让 AI 整理笔记','上传不自动读全文；网址和图片有自己的解析按钮。'),
      ('构造动机','计算能看懂，但不知道为什么要这样设式或构造','电脑和手机都使用这类说法，保存的选项编号不变。'),
      ('任务内部并行','同时生成多个部分','模型请求数、暂停和依赖顺序保持原来的规则。'),
      ('针对导师原句追问','选中导师原话再提问','提示先选句子、返回输入框写问题、最后发送；打开窗口不调用 AI。'),
      ('自评、作答分数与画像混在一起','说明自评怎样参与综合参考分，作业实际分数单独保留','不会把读过资料、查看提示或单次高分说成已经掌握。'),
      ('设置解释堆实现术语','说明用于什么、影响哪类新任务、在哪里保存','模型 ID、访问权限、文件操作及连接检查仍保留必要的技术信息。'),
      ('指南正文夹着很多历史修复说明','先给操作步骤，恢复记录与题目版本问题放到展开说明','19 个主题仍可搜索、跳转，不会插入聊天或请求模型。'),
    ]
    rows=''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in examples)
    photos=image('before-library.png','改写前：设置说明集中在一大段文字中')+image('after-library.png','改写后：先说明选择与开始，详细规则收在展开项中')+image('desktop-reading-help.png','点开后仍能看到完整的阅读规则')+image('desktop-select-pages.png','文件先保存，再选页码；这里不会自动开始全文解析')+image('desktop-settings-models.png','模型设置说明与当前工作台的名称保持一致')+image('phone-library-320.png','配对手机页面，320 像素宽度，可在弹窗中继续滚动')
    evidence=' · '.join([link(GATE/'command.json','回归与文件指纹'),link(GATE/'copy-contracts.json','按钮和历史协议检查'),link(GATE/'desktop-tests-rechecked.log','桌面模块测试'),link(UI/'ui-report.json','实际界面验收记录'),link(AUDIT/'before.json','改写前完整清单')])
    checks=['书库说明默认简短，切换设置时提示与按钮同步变化。','已有阅读任务时解释禁用原因，并能跳到原任务；全选与清空仍实际生效。','电脑主要页面和六组设置均实际打开。','打开页码选择和指南不解析文件、不发送资料、不增加聊天消息。','实际点击新名称的阅读按钮，用受控模型完成一章阅读并保存。','经真实 HTTPS 配对检查手机主要弹窗；书库在390和320像素宽度下没有横向溢出。','手机指南与电脑共用，不增加模型请求。']
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>界面提示与新手操作说明验收</title>
<style>body{{margin:0;background:#eef3ef;color:#203f34;font:17px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1180px;margin:auto;padding:32px 20px}}section,header{{background:#fff;padding:28px;border:1px solid #c8d9cf;border-radius:20px;margin:0 0 24px}}h1{{font-size:32px;line-height:1.4}}h2{{font-size:23px}}a{{color:#126747}}.stats{{display:flex;flex-wrap:wrap;gap:15px}}.stats b{{background:#e7f4eb;padding:10px 16px;border-radius:12px}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:630px}}td,th{{text-align:left;border-bottom:1px solid #d6e4dc;padding:14px;vertical-align:top}}th{{background:#eaf3ec}}figure{{margin:24px 0}}img{{max-width:100%;height:auto;border-radius:12px;border:1px solid #c9d8d0}}figcaption{{color:#4f685c;font-size:15px}}.photos figure:last-child img{{width:320px}}.note{{background:#f4f6ef;padding:16px;border-radius:12px}}code{{overflow-wrap:anywhere}}@media(max-width:600px){{main{{padding:15px 10px}}section,header{{padding:18px}}h1{{font-size:26px}}}}</style><main>
<header><small>StudyForge · 2026-10-26 · 项目文件夹中的最新版</small><h1>让第一次使用的人看懂提示，再知道下一步做什么</h1><p>这轮检查了电脑、手机、桌面窗口和软件内指南的文字。常用操作保留简短说明；较长的规则按需要展开。没有改动导师提示词、模型选择算法、评分规则或文件权限。</p><div class="stats"><b>{copy['reviewed_files']} 个界面文件已检查</b><b>{changed} 个文件改写</b><b>{gate['tests']['total']} 项相关回归通过</b><b>{node_tests} 项 JavaScript 测试通过</b><b>7 组实际界面检查</b></div><p>{link(ROOT/'验收最新版.vbs','最新版启动文件：验收最新版.vbs')} · 进入软件后按 F1 查看新手指南。</p><p class="note">请先从 Windows 右下角托盘退出旧版，再双击上面的启动文件。旧窗口不会自动加载项目文件夹中的新文字。本轮没有重新制作安装包。</p></header>
<section><h2>这次怎样改</h2><p>分三轮记录的替换共 {edits} 次，另外手工整理了书库说明、问卷用语和页面名称。不是把每个词都换掉：保存、取消、删除等熟悉的按钮保留；模型调用名、程序参数和历史记录识别用语保留原值。</p><div class="table"><table><thead><tr><th>以前容易看不懂的地方</th><th>现在的说明方式</th><th>仍保留的边界</th></tr></thead><tbody>{rows}</tbody></table></div><p>截图中书库的默认阅读说明由 {before} 字缩为 {after} 字。用量、顺序、模型及页码规则保存在“这些阅读设置怎么选？”里。</p></section>
<section><h2>实际怎么检查</h2><ol>{''.join('<li>'+html.escape(c)+'</li>' for c in checks)}</ol><p>相关回归没有失败或跳过；全部 {js['syntax_files']} 份自有 JavaScript 文件通过语法检查。原有按钮编号、选项实际值和历史协议识别保持不变。实际阅读只用 1 次受控模型请求，没有调用付费云模型，也没有接触个人学习数据库。</p><p class="note">这次验证的是提示与操作是否一致，不代表新用户访谈已经完成，也不代表重新验证了所有模型的教学质量。手机使用真实配对网关与窄屏浏览窗口，尚未在安卓实机逐项体验。</p><p>{evidence}</p></section><section class="photos"><h2>实际页面对照</h2>{photos}</section></main></html>'''
    OUT.mkdir(exist_ok=True)
    output=OUT/'界面提示与新手操作说明验收.html';output.write_text(body,encoding='utf-8')
    record={'passed':True,'report':str(output),'reviewed_files':copy['reviewed_files'],'changed_files':changed,
            'python_tests':gate['tests']['total'],'node_tests':node_tests,'native_groups':len(ui['checks']),
            'default_library_notice_chars':{'before':before,'after':after},'source_only':True}
    (OUT/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'docs/界面提示与新手操作说明-20261026.md').write_text(
        '# 界面提示与新手操作说明\n\n'
        '此次只调整面向用户的提示、按钮名称与指南；不修改模型提示词、评分、文件权限或资料范围。\n\n'
        f'已检查 {copy["reviewed_files"]} 个界面文件，改写 {changed} 个。覆盖电脑、配对手机与桌面窗口。\n\n'
        '原则：先给下一步动作；技术细节按需展开；名称与真实按钮一致；不以阅读完成代替掌握。\n\n'
        f'相关回归 {gate["tests"]["total"]} 项、JavaScript 模块测试 {node_tests} 项和7组实际界面检查通过。\n\n'
        '运行 `python -X utf8 -m scripts.verify_ui_copy` 可执行回归；历史证据目录不覆盖，重跑需改新目录。\n\n'
        '验收报告：`build/ui-copy-acceptance-20261026/界面提示与新手操作说明验收.html`。\n\n'
        '双击项目根目录 `验收最新版.vbs` 打开最新项目代码；先从托盘退出旧窗口。本轮未打包。\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
