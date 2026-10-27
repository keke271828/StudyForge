"""Run ONLY the exact, self-authored QA models, never a learner/AI program."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from .smoke_deliverables import PROGRAMS


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',required=True);args=parser.parse_args()
    report_path=Path(args.report).resolve();root=report_path.parent
    report=json.loads(report_path.read_text(encoding='utf-8'));results={}
    for fmt,binary in [('m','matlab'),('wl','wolframscript')]:
        path=Path(report['paths'][fmt]).resolve()
        if not path.is_relative_to(root): raise ValueError('仅可运行本次验收目录内的自编模型')
        first,_,body=path.read_text(encoding='utf-8').partition('\n')
        notice='运行状态：仅导出；尚未执行验证，依赖、数值结果和适用条件需在目标环境核对。'
        expected='% '+notice if fmt=='m' else '(* '+notice+' *)'
        if first!=expected or body!=PROGRAMS[fmt][1]+'\n': raise ValueError('模型样例已变更，拒绝执行')
        executable=shutil.which(binary)
        if not executable:
            results[fmt]={'status':'unavailable','executed':False};continue
        command=[executable,'-batch',"run('"+path.as_posix().replace("'","''")+"')"] if fmt=='m' else [executable,'-file',str(path)]
        try:
            process=subprocess.run(command,cwd=root,capture_output=True,encoding='utf-8',errors='replace',timeout=90,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            results[fmt]={'status':'passed' if process.returncode==0 and '1' in process.stdout else 'failed',
                          'exit_code':process.returncode,'executed':process.returncode==0,'stdout':process.stdout[-2000:],
                          'stderr':process.stderr[-2000:],'fixture_only':True}
        except subprocess.TimeoutExpired:
            results[fmt]={'status':'timeout','executed':False,'fixture_only':True}
    report['native_models']=results
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__': main()
