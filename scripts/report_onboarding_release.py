"""Collect this build's actual acceptance receipts; never install or publish."""
from pathlib import Path
import hashlib
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    version = load(ROOT / 'package.json')['version']
    ui_root, desktop_root, runtime_root, phone_root = [Path(x).resolve() for x in sys.argv[1:]]
    sources = ROOT / 'build/onboarding-final-20261025-3/command.json'
    regression, ui = load(sources), load(ui_root / 'ui-report.json')
    desktop = load(desktop_root / 'report.json')
    runtime, phone = load(runtime_root / 'result.json'), load(phone_root / 'result.json')
    release = load(ROOT / f'build/release-{version}-artifacts.json')
    asr_path = ROOT / f'build/packaged-asr-{version}/result.json'
    asr = load(asr_path)
    assert regression['exit_code'] == 0 and regression['source_frozen']
    assert ui['passed'] and desktop['ok'] and desktop['packaged'] and desktop['version'] == version
    assert runtime['ok'] and phone['ok'] and phone['own_backend_stopped'] and release['ok']
    assert release['version'] == version
    assert asr['ok'] and asr['local_files_only']
    node_log = ROOT / 'build/onboarding-node-final-20261025.log'
    assert 'pass 65' in node_log.read_text(encoding='utf-8-sig')
    for name, digest in regression['production_after'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    out = ROOT / 'build/onboarding-acceptance-20261025'
    out.mkdir(exist_ok=True)
    receipt = {'version': version, 'regression': str(sources), 'guide_ui': str(ui_root / 'ui-report.json'),
        'desktop': str(desktop_root / 'report.json'), 'runtime': str(runtime_root / 'result.json'),
        'phone': str(phone_root / 'result.json'), 'artifacts': str(ROOT / f'build/release-{version}-artifacts.json'),
        'desktop_node_tests': str(node_log), 'gpu_runtime': str(asr_path),
        'tests': regression['tests'], 'guide_checks': ui['checks'], 'real_data_modified': False,
        'installed': False, 'published': False}
    (out / 'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    esc = html.escape
    def link(path, label):
        return f'<a href="{esc(Path(path).as_uri(), quote=True)}">{esc(label)}</a>'
    picture = ui_root / 'guide-desktop-light.png'
    phone_picture = ui_root / 'guide-phone-dark.png'
    markup = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyForge {esc(version)} · 新手指南与安装包验收</title><style>
*{{box-sizing:border-box}}body{{max-width:1120px;margin:40px auto;padding:0 24px 60px;background:#f3f5ef;color:#263c32;font:16px/1.9 system-ui,"Microsoft YaHei",sans-serif}}h1{{line-height:1.35}}header,section{{background:#fffefa;border:1px solid #dbe3d9;border-radius:20px;padding:28px 32px;margin:20px 0}}a{{color:#28664c}}.tag{{font-size:12px;letter-spacing:1px;color:#527664}}.download{{display:inline-block;padding:10px 18px;background:#28664c;color:white;border-radius:10px;text-decoration:none}}img{{max-width:100%;height:auto;border-radius:12px;border:1px solid #dbe3d9}}.phone{{max-width:390px}}code{{overflow-wrap:anywhere;font-size:13px}}li{{margin:9px 0}}@media(max-width:600px){{body{{margin:15px auto;padding:0 12px}}header,section{{padding:22px}}}}
</style><header><div class="tag">WINDOWS · 2026-10-25 · 实际构建与隔离验收</div><h1>StudyForge {esc(version)}<br>从第一次使用者的视角重新写指南</h1><p>先连接一个 AI、发出第一条问题，再按需上传资料、生成讲解或交作业。查看指南不调用模型。</p><p><a class="download" href="{esc(Path(release['installer']['path']).as_uri(), quote=True)}">打开 Windows 安装包</a></p><p>安装包 {release['installer']['bytes']/1024**3:.2f} GiB。先从托盘彻底退出旧版，再选择原位置安装。未自动安装到你的环境。</p></header>
<section><h2>验收时先试这几件事</h2><ol><li>在软件左侧打开使用指南，或按 F1；首页有六个按任务分类的入口。</li><li>点“我想读一份资料”，跟着按钮名称操作，先解析一页 PDF。</li><li>在指南搜索“429”，确认相关折叠说明自动展开；清空搜索后恢复。</li><li>在资料、成果、作业、画像或全局书库附近点“怎么用”，确认直接到相关主题。</li><li>关闭帮助，确认未发送的输入、聊天和所选资料仍在。</li></ol><img alt="电脑端新版指南首页" src="{esc(picture.as_uri(), quote=True)}"></section>
<section><h2>本轮实际完成的检查</h2><ul><li>{regression['tests']['total']} 项 Python 相关回归及65项桌面启动、通知、退出与更新测试通过，最终源文件指纹保持一致。</li><li>{len(ui['checks'])} 组指南界面检查：电脑、HTTPS手机、390/320像素宽度、深色与浅色、搜索、跳转、复制替代方式、草稿和对话不丢失。</li><li>最终 Windows EXE 在不依赖系统 Python/Node 的 PATH 和独立数据目录中启动，版本为 {esc(desktop['version'])}；检查内置指南、上传后主动解析、设置、历史公式和启动项迁移。</li><li>冻结后端完成13类格式生成与回读，检查 OCR、FFmpeg、语音和凭据依赖；{len(runtime['asset_sha256'])} 个网页资源与当前源码逐一比对。</li><li>冻结 HTTPS 手机服务完成配对、上传、解析、中文文件名下载，并在重启后保留证书、会话及项目。</li><li>桌面 ASAR 源文件、版本与安装包 SHA-256 已核对。构建仅去除字节完全相同的嵌套 CUDA 副本，保留加载目录版本与许可；包内GPU短静音探测使用缓存模型离线通过，不代表视频识别质量或速度测试。</li></ul><p>以上不是模型教学质量、所有网络环境、真实安卓触控或所有历史功能的完整认证。本轮未重新跑付费模型评测，未发布更新源。</p><img class="phone" alt="手机端深色指南" src="{esc(phone_picture.as_uri(), quote=True)}"></section>
<section><h2>文件与记录</h2><p>{link(ROOT / 'docs/0.4.4新手指南与打包验收.md', '使用方式与改动说明')} · {link(sources, '最终回归记录')} · {link(out / 'result.json', '本轮验收索引')} · {link(ROOT / f'build/release-{version}-artifacts.json', '安装包及源文件核对')}</p><p>SHA-256：<code>{esc(release['installer']['sha256'])}</code></p><p>保留原学习数据目录。电脑升级后，手机刷新页面获取新版界面；AI服务仍需原有有效配置。没有正式更新源时使用本安装包升级。</p></section></html>'''
    report = out / '新手指南与新版安装包验收.html'
    report.write_text(markup, encoding='utf-8')
    print(str(report))


if __name__ == '__main__':
    main()
