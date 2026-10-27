"""Local verification of this round's public deliverables; no app DB or models."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from docx import Document

root=Path(__file__).resolve().parents[1]
folder=root/'build'/'learning-transfer-real-20261013-2'
report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
student=json.loads((folder/'student.json').read_text(encoding='utf-8'))
private=json.loads((folder/'private-solutions-and-audit.json').read_text(encoding='utf-8'))
word=Document(report['word_file'])
text='\n'.join(p.text for p in word.paragraphs)
questions=student['questions']
assert len(questions)==3
assert all(item['question'] in text for item in questions)
assert all('solution' not in item and 'context_change' not in item for item in questions)
def private_rows(value):
    if isinstance(value,dict):
        yield value
        for nested in value.values():yield from private_rows(nested)
    elif isinstance(value,list):
        for nested in value:yield from private_rows(nested)
secret_fields=[]
for row in private_rows(private):
    for key in ('solution','context_change'):
        value=row.get(key)
        if isinstance(value,str) and len(value)>20:secret_fields.append(value)
assert secret_fields and all(value not in text for value in secret_fields)
docs=['README.md','docs/新情境理解检查与证据分开验收.md']
links=[]
for name in docs:
    source=root/name
    for target in re.findall(r'\]\(([^)]+)\)',source.read_text(encoding='utf-8')):
        if '://' in target or target.startswith('#'):continue
        resolved=(source.parent/target.split('#',1)[0]).resolve()
        assert resolved.exists(),(name,target)
        links.append(str(resolved))
guide=(root/'web/help/guide.html').read_text(encoding='utf-8')
section=guide.split('<section id="goals"',1)[1].split('</section>',1)[0]
assert '自愿检查理解' in section and '新情境检查' in section
results=[]
for name in ('related-tests.xml','mobile-and-guide-tests.xml'):
    suite=ET.parse(root/'build/learning-transfer-20261013'/name).getroot().find('testsuite')
    assert suite is not None and int(suite.attrib['failures'])==int(suite.attrib['errors'])==0
    results.append({'file':name,**suite.attrib})
ui=json.loads((root/'build/learning-transfer-ui-20261013-4/ui-report.json').read_text(encoding='utf-8'))
assert ui['passed'] and len(ui['checks'])==8 and not ui['console_errors']
delivery={'word_reopened':True,'questions':len(questions),'private_fields_absent':True,
          'word_visual_render_performed':False,'local_links_checked':len(links),
          'guide_section_checked':True,'pytest':results,'ui_checks':len(ui['checks'])}
(root/'build/learning-transfer-20261013/delivery-check.json').write_text(json.dumps(delivery,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in delivery.items() if key!='pytest'},ensure_ascii=False))
