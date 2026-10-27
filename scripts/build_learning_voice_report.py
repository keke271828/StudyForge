"""Publish the verified evidence boundary, with an openable synthetic comparison."""
import hashlib
from html import escape as esc
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from urllib.parse import quote,unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/learning-voice-acceptance-20261023'
GATE=ROOT/'build/learning-voice-final-20261023'
UI=ROOT/'build/learning-voice-ui-20261023-2'
LOCAL=ROOT/'build/learning-voice-local-20261023-1'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def url(path):return quote(os.path.relpath(path,OUT).replace('\\','/'),safe='/')
def link(path,label):return '<a href="'+url(path)+'">'+esc(label)+'</a>'


def main():
    gate=read(GATE/'command.json');ui=read(UI/'ui-report.json');local=read(LOCAL/'report.json')
    assert gate['exit_code']==0 and gate['source_frozen'] and gate['tests']['failure']==gate['tests']['error']==gate['tests']['skipped']==0
    assert all(sha(ROOT/name)==value for name,value in gate['production_after'].items())
    assert all(sha(ROOT/name)==value for name,value in local['production'].items())
    assert ui['passed'] and ui['external_model_requests']==local['real_model_requests']==0 and local['passed']
    assert not OUT.exists();OUT.mkdir()
    cases=''.join('<details'+(' open' if i<3 else '')+'><summary>'+esc(row['name'])+'</summary><h4>发给导师的原消息</h4><pre>'+esc(row['message'])+'</pre><div class="comparison"><div><h4>旧筛选留下的候选证据</h4><pre>'+esc(row['before'] or '（无）')+'</pre></div><div><h4>新筛选留下的候选证据</h4><pre>'+esc(row['after'] or '（无；引用只作上下文）')+'</pre></div></div></details>' for i,row in enumerate(local['cases']))
    checks=''.join('<li>'+esc(text)+'</li>' for text in ui['checks'])
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>学习画像引用归属与教学输入验收</title>
<style>:root{{color-scheme:light;color:#233f36;background:#f0ede6;font:16px/1.8 "Microsoft YaHei",sans-serif}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1120px;margin:auto;padding:32px 20px 70px}}header,section{{background:#fffdf8;border:1px solid #d9dfd7;border-radius:20px;padding:26px 30px;margin-bottom:20px}}h1{{font-size:31px;line-height:1.4}}h2{{font-size:23px}}h4{{margin:10px 0}}.eyebrow{{font-size:13px;letter-spacing:.12em;color:#4d7868}}.notice{{background:#fff1da;border-left:4px solid #bc8a35;border-radius:10px;padding:16px 20px}}.good{{background:#e9f3ec;border-radius:10px;padding:16px 20px}}.comparison{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f2ec;padding:16px;border-radius:10px;font:14px/1.9 Consolas,"Microsoft YaHei",monospace}}details{{border:1px solid #dce1d7;padding:14px 18px;border-radius:14px;margin:12px 0}}summary{{cursor:pointer;font-weight:700}}li{{margin:8px 0}}a{{color:#116c58;text-underline-offset:3px}}img{{display:block;max-width:100%;border-radius:14px;border:1px solid #dce1d7;margin:16px 0}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #dce1d7;padding:10px}}@media(max-width:660px){{main{{padding:16px 9px}}header,section{{padding:20px 16px}}h1{{font-size:25px}}.comparison{{grid-template-columns:1fr}}}}</style>
<main><header><div class="eyebrow">STUDYFORGE · 2026-10-23 · SOURCE ACCEPTANCE</div><h1>引用材料，与学习者自己的理解分开</h1><p>修复粘贴题干／AI回答中的“我认为”“为什么”误入画像候选的问题，并让历史上明确误归属的判断可查看、恢复。</p><p>{link(ROOT/'验收最新版.vbs','启动最新版源码应用')} · {link(ROOT/'web/help/guide.html','软件内操作指南')} · {link(LOCAL/'report.json','本机对照与开销记录')}</p><p>先从Windows托盘彻底退出旧StudyForge，再在资源管理器双击源码启动入口。本轮未打包EXE。</p></header>
<section><h2>为何会影响教学</h2><p>旧候选筛选主要看关键词。明确引用中的“我认为高斯定律……”可能被当作学习者的观点；同一消息另有真实疑问时，后续校验只确认引句出现在整段文字里，也可能通过。</p><div class="good">现在在两处核对归属：生成画像候选前先识别明确引用；后台整理返回后，证据引句还须落在学习者自己的候选文字中。导师仍可阅读你发来的引用来讲解，但引用本身不能证明你的理解或误解。</div><ul><li>支持Markdown引用块、代码块及“原文／原题／AI回答”等明确标签。</li><li>“我的问题／我的理解／我的推导／我的代码”等归属明确的部分保留；自己的代码可以使用代码块。</li><li>旧提取若丢失引用标记，尽量回看同一对话绑定的原始用户消息，不读取别的对话。</li><li>历史混合事件中，只暂时移出有明确外部引用依据的判断，真实疑问保留；不会整条抹掉。</li><li>查看原消息、恢复、纠正沿用已有入口；原判断、原聊天和实际分数不被重写。</li></ul></section>
<section><h2>本机可复现的前后对照</h2><p>下面比较“准备进入画像的候选文字”，不是导师讲解内容。旧版基线由当前同一函数移除新增归属步骤还原，原正则表达式保持相同；另有修复前17项失败、3项通过的针对性回归作证据。</p>{cases}<div class="notice">没有标记的自然语言无法可靠自动判断作者。以“原文：”开始的多段引用，请用“我的问题：”明确结束引用并表达自己的疑问。尚不明确属于你的代码或论证仅作讨论上下文，不据此认定能力；这不会阻止导师正常回答。</div></section>
<section><h2>历史判断可以核对后恢复</h2><p>在“学习画像”选择“已移出画像”，打开“查看 / 恢复”。有明确引用依据的记录会显示暂时移出的原因、原判断和完整原消息。恢复后采用显示的判断；原证据仍保留。</p><img src="{url(UI/'desktop-excluded-evidence.png')}" alt="合成历史画像的原引用、真实疑问、自动移出原因与恢复入口"><p>截图中的英文标记是隔离测试哨兵，不是实际产品给学生的教学评语。{link(UI/'desktop-own-profile.png','查看只保留真实疑问的画像界面截图')}</p></section>
<section><h2>实际验证</h2><p>最终{gate['tests']['total']}项关联回归全通过，失败／错误／跳过均为0，7个生产文件在测试前后指纹一致；其中25项新针对性覆盖引用边界、自己的代码、旧混合记录、后台输入／提交与讲解／出题输入。原生讲解和习题设计收到保留的真实疑问，不再收到被排除的错误判断。</p><p>实际电脑和已配对HTTPS手机完成{len(ui['checks'])}项操作；导师请求由模拟模型响应，用于核对软件实际传出的画像，不作模型教学质量认证：</p><ol>{checks}</ol><p>{link(GATE/'command.json','最终测试命令与源码指纹')} · {link(GATE/'regression.xml','最终回归XML')} · {link(UI/'ui-report.json','电脑／手机操作记录')} · {link(ROOT/'build/learning-voice-red-20261023.xml','修复前针对性失败记录')}</p><p>首轮手机测试脚本误用了仅电脑开放的流式接口，得到403；改为手机自身聊天入口后通过，未扩大手机权限。沙箱首次启动Python被系统拒绝后，测试在获准的隔离运行环境执行。这两项是验收环境／脚本记录，不计为产品功能通过。</p></section>
<section><h2>额外开销与边界</h2><table><tr><th>合成负载</th><td>{local['synthetic_events']}条事件、{local['synthetic_insights']}条判断</td></tr><tr><th>正确分开</th><td>{local['excluded']}条外部引用暂时移出，{local['kept']}条真实疑问保留</td></tr><tr><th>首次本机过滤</th><td>{local['migration_seconds']}秒</td></tr><tr><th>再次访问</th><td>12次中位{local['warm_median_ms']}毫秒；重复数据库写入0次</td></tr><tr><th>Python追踪分配峰值</th><td>{local['python_tracemalloc_peak_mib']} MiB，仅此过滤步骤</td></tr><tr><th>新增真实模型请求</th><td>0次；界面核对使用2次模拟模型请求</td></tr></table><p class="notice">这是本机合成数据下的归属过滤开销。tracemalloc不包含全部原生内存，不能代表整个软件RAM或AI任务速度。实体安卓、任意文本作者识别、模型讲解质量均未因此获得全面认证。已有讲解／批改文档和任务快照不会被静默改写。</p><p>指南和手机壳v69已同步。{link(ROOT/'docs/学习画像引用归属与教学输入验收.md','实现及验收说明')}</p></section></main></html>'''
    target=OUT/'学习画像引用归属与教学输入验收.html'
    doc=ROOT/'docs/学习画像引用归属与教学输入验收.md'
    doc.write_text(f'''# 学习画像引用归属与教学输入验收

2026-10-23，源码更新，未打包。

## 改动

- 候选前识别明确外部引文、源内容标签与未署明归属的代码块；明确自己的理解／代码保留。引文之外明确的真实疑问逐字保留。
- 后台返回的引句必须同时属于实际用户候选证据，旧提取丢失标记时回查同对话绑定的原用户消息。引用只作教学上下文，不充当用户能力证据。
- 新增可逆的逐条证据过滤表；旧混合事件只移出明确外部引用形成的判断，完整原消息及原判断不删除。用户恢复／纠正优先，实际分数不变。
- 旧过滤按版本及每100事件一批处理；重复访问不重复写入，不增加固定模型请求。指南和手机壳v69同步。

## 验证

- 修复前17项失败、3项通过；最终{gate['tests']['total']}项关联回归全通过，包括25项新针对性。7个生产文件指纹前后相同。
- 电脑与配对HTTPS手机{len(ui['checks'])}项操作通过：查看／恢复／再次移出、原记录保留，以及两端导师实际系统输入采用有效画像。模拟模型2次，真实云调用0次。
- 原生讲解与习题设计输入的受控验证通过；提交前仍无答案，不新增作答／评分。
- 800事件／1600判断本机过滤{local['migration_seconds']}秒；后续12次中位{local['warm_median_ms']}毫秒、0次重复写入；Python追踪峰值{local['python_tracemalloc_peak_mib']}MiB。仅此合成步骤，不是全软件RAM或AI速度指标。
- 首次沙箱Python启动失败单列；首轮手机脚本使用电脑端点403后改用手机正式入口通过，没有扩大权限。

## 限制

不能从未标记的自然语言可靠推断作者。原消息缺失时只能采用仍可确认的归属；没有证据的旧判断不猜着移除。长期能力仍需实际作答验证。旧文档和任务快照保持原交付，不自动重写。没有实体安卓或模型教学质量全面认证。

验收页：[{target.name}]({target.as_posix()})
''',encoding='utf-8')
    target.write_text(page,encoding='utf-8')
    class Links(HTMLParser):
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key not in ('src','href') or not value:continue
                parsed=urlsplit(value);assert not parsed.scheme and not parsed.netloc
                assert (OUT/unquote(parsed.path)).resolve().is_file(),value
    Links().feed(page)
    (OUT/'manifest.json').write_text(json.dumps({'gate':gate,'ui':ui,'local':local,
        'public_files':{str(p.relative_to(ROOT)):sha(p) for p in (target,doc,UI/'desktop-excluded-evidence.png',UI/'desktop-own-profile.png')}},ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(target),flush=True)


if __name__=='__main__':main()
