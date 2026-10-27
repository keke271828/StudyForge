"""Record the final technical acceptance edits without changing raw outputs."""
from __future__ import annotations

import json
from pathlib import Path

from studyforge.exporters import export_docx

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-video-refined-20261010-1'
document = (TARGET / 'acceptance-lecture.md').read_text(encoding='utf-8')
changes = []
table_source = 'https://raw.githubusercontent.com/latex3/latex2e/develop/base/lttab.dtx'
float_source = 'https://raw.githubusercontent.com/latex3/latex2e/develop/base/ltfloat.dtx'
space_source = 'https://raw.githubusercontent.com/latex3/latex2e/develop/base/ltspace.dtx'


def correct(before, after, reason, source=None):
    global document
    if document.count(before) != 1:
        raise ValueError('验收修正无法唯一定位：' + reason)
    document = document.replace(before, after, 1)
    changes.append(dict(before=before, after=after, reason=reason, checked_source=source))


correct('顺带说明：竖线只能写在列格式里，**不能写在某一行内容里**——这是使用边界，写错位置要么报错要么毫无效果。',
        '顺带说明：本课用列格式里的 `|` 声明列边界竖线。在普通单元格中直接输入 `|`，不会因此变成整列边框；这与专门画线的命令不同。'
        f'**补充校核：**LaTeX 还提供可以写在单元格内容中的 `\\vline`，所以不能概括成“所有竖线只能写在列格式里”。[LaTeX 内核表格源码]({table_source})。',
        '区分列边界声明和单元格内画线命令，不错误禁止合法的 vline。', table_source)
correct('竖线只能写在列格式里；横线 `\\hline`',
        '本课通过列格式里的 `|` 声明竖线；横线 `\\hline`',
        '第一部分小结保留本课方法的范围。', table_source)
correct('竖线只能写在列格式里。',
        '这是本课设置列边界竖线的方法；正文已说明它不是所有画线命令的唯一写法。',
        '全文总结不再次引入唯一方法的断言。', table_source)
correct('因为 LaTeX 的表格编号按 `table` 环境在文档中出现的顺序自动递增。这张新表排在前面那些表之后，所以接着往下编号。',
        '本例每张表都调用了 `\\caption`，这个命令在生成题注时推进表格计数器。因此这次题注接着前面的编号成为“表 3”。'
        f'**补充校核：**真正推进计数的是 `\\caption`，只有 `table` 环境而没有题注，并不会因此自动新增编号。[LaTeX 内核题注源码]({float_source})。',
        '表格编号由 caption 推进，不是单凭 table 环境出现。', float_source)
correct('因为它按 `table` 环境出现的顺序自动编号。',
        '因为本例各张表的 `\\caption` 依次推进表格计数器。',
        '第3部分小结与正文的题注计数规则一致。', float_source)
correct('表 2、表 3 按 `table` 环境出现顺序递增',
        '本例的表 2、表 3 由各次 `\\caption` 推进表格计数器',
        '全文总结保留真正的编号触发条件。', float_source)
correct('每行必须凑够与列数一致的条目数（含空条目）',
        '每行各条目占用的列数相加应覆盖整行：普通格或留空位置计1列，横向合并按跨度计列，而不是只数条目个数',
        '跨列合并时按实际跨度计列。', table_source)
correct('每行条目数（含空条目）必须凑够列数',
        '每行按跨度累计占用的列数应覆盖整行；普通格和必要的留空位置各计1列，横向合并格按其跨度计列',
        '全文总结不把合并后的条目数量误当成列数。', table_source)
correct('`\\hspace` 放在一行开头时会被丢弃，如果想在行首留出空格，要用带星号的 `\\hspace*{...}`。',
        '`\\hspace` 产生的空白在换行等边界处可能被丢弃；希望在那里保留指定空白时，可用带星号的 `\\hspace*{...}`。',
        '空白可能在边界被丢弃，不概括成所有行首情形必然丢弃。', space_source)
correct('`\\hspace` 在行首会被丢弃，需用 `\\hspace*`（补充背景）。',
        '`\\hspace` 的空白在换行等边界处可能被丢弃；需要保留时可用 `\\hspace*`（补充背景）。',
        '总结保留空白处理的条件。', space_source)
correct('想要更宽的间距只能用这些命令。',
        '本课使用这些命令控制间距，不表示其他排版手段都不可用。',
        '列举的演示方法不是全部方法。')
correct('括号里必须带**长度单位**（`cm`、`mm`、`pt`、`em`、`in` 等），只写数字不行。',
        '像本例这样填写数值长度时，要带**长度单位**（`cm`、`mm`、`pt`、`em`、`in` 等），不能只写一个裸数字。',
        '限定为数值长度输入，避免误排除合法的长度变量。', space_source)
correct('括号里必须带单位。普通源码空格',
        '像本例这样填写数值长度时，数字后要带单位。普通源码空格',
        '全文总结保留数值长度输入的范围。', space_source)

output = TARGET / 'LaTeX表格课程_验收复核版.docx'
export_docx(document, 'LaTeX 表格课程：讲解与操作实例（验收复核版）', output)
(TARGET / 'acceptance-lecture.md').write_text(document, encoding='utf-8')
(TARGET / 'semantic-acceptance.json').write_text(json.dumps({
    'original_model_output_preserved': True,
    'model_prose_changed': True,
    'additional_model_requests': 0,
    'corrections': changes,
    'summary_review': '已核对三个部分主线、命令职责与使用条件；关键词出现不作为全面语义验证。',
    'source_warning_count_retained': 3,
}, ensure_ascii=False, indent=2), encoding='utf-8')
summary_report = json.loads((TARGET / 'summary-acceptance.json').read_text(encoding='utf-8'))
summary_report['semantic_validation'] = '另行核对三个部分的主线与关键命令，局部技术修正见 semantic-acceptance.json；不宣称所有细节已穷尽验证。'
(TARGET / 'summary-acceptance.json').write_text(json.dumps(summary_report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(docx=str(output), recorded_local_edits=len(changes)), ensure_ascii=False))
