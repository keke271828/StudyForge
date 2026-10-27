"""Saved actual baseline requests must remain byte-identical for unique prose."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


async def main(name,phase='baseline'):
    folder=ROOT/'build'/name
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'request-check-data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge.review import review_explanation
    from studyforge.review_passages import build
    from studyforge.db import j
    cases=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))['cases'];rows=[]
    for case in cases:
        saved=json.loads((folder/(case['id']+'-'+phase+'-records.json')).read_text(encoding='utf-8'))[0]
        class Capture:
            calls=0
            async def complete(self,system,user,**kwargs):
                self.calls+=1
                assert system==saved['system'] and user==saved['user'] and kwargs.get('json_mode')
                return saved['response']
        if phase=='baseline':assert not build(case['draft'])['public']
        else:assert build(case['draft'])['public']
        client=Capture()
        text,reports=await review_explanation(client,case['source'],case['draft'],mode='fast',requirements=case['requirements'],
            summary_level=3,learning_mode='deep',explanation_style='balanced')
        assert client.calls==1
        if phase!='baseline':
            old=(folder/(case['id']+'-'+phase+'-final.md')).read_text(encoding='utf-8')
            assert text==old and [a['mode'] for a in reports[0]['local_correction_anchors']]==['registered_passage']*2
        rows.append({'case':case['id'],'same_system_and_user':True,'replayed_saved_responses':1,'new_external_requests':0})
    result={'passed':True,'cases':rows}
    (folder/('narrow-unchanged-request-checks.json' if phase=='baseline' else 'narrow-final-code-replay.json')).write_text(j(result),encoding='utf-8');print(j(result))


if __name__=='__main__':asyncio.run(main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'baseline'))
