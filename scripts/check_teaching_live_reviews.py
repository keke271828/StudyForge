"""Exercise the production fast-review path on synthetic real teaching outputs.

Outputs are retained separately; this does not change a learner's document or
settings. The response is still subject to human review, not self-certification.
"""
import asyncio
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(args):
    OUT=ROOT/args.output
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'isolated-data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(OUT/'isolated-model')
    from studyforge.ai import DeepSeekClient
    from studyforge.review import review_explanation
    from scripts.teaching_prompt_comparison import CASES
    rows=[]
    for name,folder in [('limit_document','learning-quality-20261013-math-retry'),
                        ('causality_document','learning-quality-20261013-final')]:
        if args.case and name not in args.case:continue
        path=ROOT/'build'/folder/f'{name}-C-revised.md'
        original=path.read_text(encoding='utf-8')
        client=DeepSeekClient('deepseek-flash',effort='high')
        start=time.perf_counter()
        try:
            document,reports=await asyncio.wait_for(review_explanation(client,CASES[name]['source'],original,
                mode='fast',learning_mode='deep',explanation_style='balanced',output_language='zh'),240)
            (OUT/f'{name}-reviewed.md').write_text(document,encoding='utf-8')
            (OUT/f'{name}-review.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
            row=dict(case=name,status='completed',original_sha256=hashlib.sha256(original.encode()).hexdigest(),
                     changed=document!=original,review=reports,output=str(OUT/f'{name}-reviewed.md'))
        except Exception as exc:
            row=dict(case=name,status='failed',error=str(exc) or type(exc).__name__)
        finally:
            await client.close()
        row['seconds']=round(time.perf_counter()-start,2)
        rows.append(row)
        (OUT/'report.json').write_text(json.dumps({'model':'deepseek-flash','effort':'high','mode':'fast','results':rows,
            'scope':'Production fast review on synthetic answers; no private learner history or reasoning export'},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:row[key] for key in ('case','status','seconds')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='build/learning-quality-20261013-audit')
    parser.add_argument('--case',action='append',choices=['limit_document','causality_document'])
    asyncio.run(main(parser.parse_args()))
