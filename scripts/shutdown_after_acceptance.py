"""One-shot, explicitly requested normal Windows shutdown after saved acceptance."""
import argparse
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',required=True)
    parser.add_argument('--delay',type=int,default=45,choices=range(15,121))
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    report_path=Path(args.report).resolve()
    if report_path.name!='report.json' or not report_path.is_relative_to(ROOT/'build'):
        raise SystemExit('Only a saved workspace acceptance report is allowed.')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if not report.get('requested_shutdown') or not report.get('source_frozen') or not report.get('ui_checks'):
        raise SystemExit('Completed, saved acceptance and a shutdown request are required.')
    tests=report.get('tests',{})
    if not tests.get('total') or any(tests.get(key)!=0 for key in ('failure','error','skipped')):
        raise SystemExit('Final tests have not passed.')
    command=[str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/shutdown.exe'),'/s','/t','0']
    if not args.execute:
        print(json.dumps({'dry_run':True,'delay_seconds':args.delay,'command':command}));return
    if os.name!='nt':raise SystemExit('Windows is required.')
    status_path=report_path.with_name('shutdown-status.json')
    if status_path.exists():raise SystemExit('A shutdown record already exists; do not issue it twice.')
    current=datetime.now(timezone.utc)
    status={'state':'scheduled','pid':os.getpid(),'scheduled_at_utc':current.isoformat(),
        'request_at_utc':(current+timedelta(seconds=args.delay)).isoformat(),'delay_seconds':args.delay,
        'force_applications':False,'command':command,'user_request':'继续，做完关机'}
    def save():
        status_path.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
        report.update(shutdown_state=status['state'],shutdown_status_file=status_path.name)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save();time.sleep(args.delay)
    status.update(state='requesting',requested_at_utc=datetime.now(timezone.utc).isoformat());save()
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    status.update(state='requested' if result.returncode==0 else 'failed',exit_code=result.returncode,
        output=result.stdout,error=result.stderr);save()


if __name__=='__main__':main()
