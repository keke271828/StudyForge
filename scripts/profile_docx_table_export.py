"""Bounded local table-export measurement, identical content before/after."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main(name):
    folder=ROOT/'build'/name
    if folder.exists() and any(folder.iterdir()):raise SystemExit('Use a fresh folder.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge.exporters import export_document
    from docx.table import Table
    original=Table._cells;count=0
    def observed(table):
        nonlocal count
        count+=1;return original.fget(table)
    Table._cells=property(observed)
    # Warm dependencies, not the measured content.
    export_document('# 依赖预热\n\n数学 $x_n$。','docx','预热','warm.docx')
    rows=[]
    for size in (32,128,256):
        content='# 学习概念对照\n\n| 节点 | 准确定义 | 成立条件 | 直观解释 |\n|---|---|---|---|\n'
        for index in range(size):
            content+=f'| 概念 {index+1} | 正数半径 $r_{index}$ | 端点归属必须明确 | **先核对条件**，再比较结论。 |\n'
        content+='\n> 这是合成验收原文。[来源：合成材料]\n\n## 系统性总结\n\n保留节点、条件与直观解释的对应关系。'
        before=count;start=time.perf_counter();path=export_document(content,'docx','概念对照验收',f'table-{size}.docx')
        elapsed=time.perf_counter()-start
        with zipfile.ZipFile(path) as package:
            hashes={file:hashlib.sha256(package.read(file)).hexdigest() for file in package.namelist() if file!='docProps/core.xml'}
        rows.append({'rows':size+1,'columns':4,'seconds':elapsed,'grid_accesses':count-before,
            'content_sha256':hashlib.sha256(content.encode()).hexdigest(),'docx_member_sha256':hashes,'path':str(path)})
        print(json.dumps({key:value for key,value in rows[-1].items() if key not in ('docx_member_sha256','content_sha256','path')},ensure_ascii=True),flush=True)
    (folder/'exporters-baseline.py').write_bytes((ROOT/'studyforge/exporters.py').read_bytes())
    (folder/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main(sys.argv[1])
