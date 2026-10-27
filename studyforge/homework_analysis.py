"""Per-question reuse bound to the exact attempt, teaching basis and evidence."""
from __future__ import annotations

import copy
import hashlib
import json

from .db import unj

VERSION='2026-10-26-homework-analysis-v2'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


class AnalysisPlan:
    def __init__(self,row,worksheet,grade,causes,options,client,system,indices):
        self.indices=list(indices);self.reused={}
        self.basis=fingerprint({
            'attempt':[row.get(key) for key in ('id','exercise_set_id','project_id','conversation_id','source_version')],
            'worksheet':[worksheet.get(key) for key in ('id','questions_json','solutions_json','difficulty')],
            'answers':row['answers_json'],'grade':grade,'teaching':options['teaching'],'profile':options['profile'],
            'requested_service':[options.get(key) for key in ('provider','model','reasoning_effort','coding')],
            'actual_service':[getattr(client,key,None) for key in ('provider','model','effort')],
            'system':system,
        })
        self.inputs={str(index):fingerprint([self.basis,index,[cause for cause in causes if cause['index']==index]]) for index in indices}
        previous=unj(row.get('analysis_json') or '{}',{})
        saved=previous.get('analysis_reuse',{}) if isinstance(previous,dict) else {}
        items=previous.get('items') if isinstance(previous,dict) else None
        if (isinstance(saved,dict) and saved.get('version')==VERSION and saved.get('basis_sha256')==self.basis
                and isinstance(saved.get('entries'),dict) and isinstance(items,list)
                and all(isinstance(item,dict) and type(item.get('index')) is int for item in items)
                and len({item['index'] for item in items})==len(items)):
            for item in items:
                index=item['index'];entry=saved['entries'].get(str(index))
                if (index in self.indices and isinstance(entry,dict)
                        and entry.get('input_sha256')==self.inputs[str(index)]
                        and entry.get('output_sha256')==fingerprint(item)):
                    self.reused[index]=copy.deepcopy(item)
        self.pending=[index for index in self.indices if index not in self.reused]

    def finish(self,result):
        items=result.get('items')
        if (not isinstance(items,list) or any(not isinstance(item,dict) or type(item.get('index')) is not int for item in items)
                or sorted(item['index'] for item in items)!=self.pending):
            raise ValueError('本次补讲结果与需要更新的题号不一致')
        combined=self.reused|{item['index']:item for item in items}
        ordered=[copy.deepcopy(combined[index]) for index in self.indices]
        return {'items':ordered,'analysis_reuse':{
            'version':VERSION,'basis_sha256':self.basis,
            'requested_indices':self.pending,'reused_indices':sorted(self.reused),
            'entries':{str(item['index']):{'input_sha256':self.inputs[str(item['index'])],
                'output_sha256':fingerprint(item)} for item in ordered},
            'meaning':'unchanged_validated_teaching_not_a_new_assessment',
        }}
