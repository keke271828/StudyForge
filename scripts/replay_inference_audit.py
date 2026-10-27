"""Replay preserved model JSON through final production guards. Zero AI calls."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def main():
    out = ROOT/'build/teaching-inference-20261015/replay'; out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge.review import review_explanation, INFERENCE_SCOPE_RULES
    from studyforge.exporters import export_document
    from docx import Document
    rows = []
    for folder in (ROOT/'build/inference-audit-real-20261015-1', ROOT/'build/inference-audit-control-20261015-1'):
        inputs = json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
        for old in json.loads((folder/'results.json').read_text(encoding='utf-8')):
            key, arm = old['case'], old['arm']; records = json.loads((folder/(key+'-'+arm+'-requests.json')).read_text(encoding='utf-8'))
            assert old['status']=='completed' and len(records)==1
            class Replay:
                calls = 0
                async def complete(self, system, user, **kwargs):
                    self.calls += 1
                    if arm=='expanded':
                        assert system == records[0]['system'] and user == records[0]['user']
                    else:
                        assert system.replace(INFERENCE_SCOPE_RULES, '') == records[0]['system'] and user == records[0]['user']
                    return records[0]['response']
            client = Replay()
            text, reports = await review_explanation(client, inputs[key]['source'], inputs[key]['draft'], mode='fast',
                learning_mode='deep', explanation_style='balanced', requirements=inputs[key]['requirements'], summary_level=3)
            file = key+'-'+arm+'.md'; (out/file).write_text(text, encoding='utf-8', newline='')
            row = {'case': key, 'arm': arm, 'output_file': file, 'output_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'replayed_calls': client.calls, 'external_model_requests': 0, 'reports': reports,
                'original_body_unchanged': text==inputs[key]['draft'], 'note': 'Replay of historical response, not a newly generated model answer.'}
            assert client.calls==1
            if key=='causal' and arm=='expanded':
                assert reports[0]['locally_corrected_issues']==[0,1]
                assert '通常会把' not in text and '比例之差"里混进了自选择' not in text
                replacements = json.loads(records[0]['response'])['corrections']
                assert all(change['after'] in text for change in replacements)
                assert '尚未再次独立复核' in text
                word = export_document(text, 'docx', '因果讲解审查回放', 'causal-audit-replay.docx')
                content = '\n'.join(paragraph.text for paragraph in Document(word).paragraphs)
                assert all(change['after'] in content for change in replacements) and '通常会把' not in content
                row['word_verified'] = True
            rows.append(row)
    (out/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'historical_responses_replayed': len(rows), 'external_model_requests': 0,
                      'same_expanded_requests': True, 'actual_word_verified': True}, ensure_ascii=True))


if __name__=='__main__': asyncio.run(main())
