"""Keep literal math delimiters without guessing missing JSON or formula text."""
import asyncio
import json

import pytest

from studyforge.ai import complete_json,parse_json_response


@pytest.mark.parametrize('delimiter',[r'\(',r'\)',r'\[',r'\]'])
def test_raw_delimiter_in_a_string_value_is_preserved_literally(delimiter):
    value='文字'+delimiter+'a+b'+delimiter
    raw='{"result":"'+value+'"}'
    assert parse_json_response(raw)=={'result':value}


def test_nested_real_reply_shape_preserves_formula_newlines_and_every_non_delimiter_escape():
    raw=r'{"passed":false,"issues":[{"problem":"仅在 \(a=2\) 成立。","evidence":"\[(a+b)/2\]，另有 \\frac{1}{2}。\n下一行。"}],"corrections":[]}'
    result=parse_json_response(raw)
    assert result['passed'] is False and result['corrections']==[]
    assert result['issues'][0]['problem']==r'仅在 \(a=2\) 成立。'
    assert result['issues'][0]['evidence']==r'\[(a+b)/2\]，另有 \frac{1}{2}。'+'\n下一行。'


@pytest.mark.parametrize('slashes',[1,2,3,4,5,6,7,8])
def test_backslash_parity_is_respected_not_blanket_replaced(slashes):
    raw='{"value":"'+'\\'*slashes+'(x'+'\\'*slashes+')"}'
    expected='\\'*((slashes+1)//2)+'(x'+'\\'*((slashes+1)//2)+')'
    assert parse_json_response(raw)=={'value':expected}


def test_valid_json_strings_keys_and_escaped_quotes_are_not_rewritten():
    expected={'quote':'"quoted"','math':r'\(x\)','line':'a\nb\tc',
              'literal':r'\\(not a delimiter)','control':'\f\b','key\\(x)':{'unicode':'😀'}}
    assert parse_json_response(json.dumps(expected,ensure_ascii=False))==expected
    raw=r'{"value":"say \"hi\"; \(x\); slash \\; unicode \u0041"}'
    assert parse_json_response(raw)=={'value':'say "hi"; '+r'\(x\); slash \; unicode A'}


@pytest.mark.parametrize('wrapper',['```json\n%s\n```','返回对象：\n%s\n以上为对象。','%s'])
def test_existing_object_and_fence_extraction_still_applies(wrapper):
    assert parse_json_response(wrapper%r'{"formula":"\(x\)"}')=={'formula':r'\(x\)'}


@pytest.mark.parametrize('raw',[
    r'{"value":"\unknown"}',r'{"value":"\(x\)","bad":"\q"}',
    r'{"value":"\(x\)","bad":"\uZZZZ"}',r'{"value":"\(x\)",}',
    r'{"value":"\(x\)"',r'{"value":"\(x\)","missing":}',
    '{"value":"'+r'\(x\)'+'\nraw newline"}',r'{"value":\(x\)}',
])
def test_unknown_escapes_structure_errors_and_raw_control_characters_still_fail(raw):
    with pytest.raises((ValueError,json.JSONDecodeError)):parse_json_response(raw)


def test_complete_json_keeps_one_request_for_unambiguous_delimiters():
    calls=[]
    class Client:
        async def complete(self,*args,**kwargs):
            calls.append(args);return r'{"passed":false,"issues":[{"problem":"仅在 \(a=2\) 成立"}]}'
    result=asyncio.run(complete_json(Client(),'只返回审核对象。','核对公式。',validate=lambda value:value['issues'][0]['problem']))
    assert len(calls)==1 and result['passed'] is False and result['issues'][0]['problem']==r'仅在 \(a=2\) 成立'


def test_schema_failure_after_delimiter_recovery_still_uses_the_bounded_model_repair():
    calls=[]
    class Client:
        async def complete(self,*args,**kwargs):
            calls.append(args);return r'{"passed":"\(wrong-type\)","issues":[]}' if len(calls)==1 else '{"passed":true,"issues":[]}'
    def validate(value):
        if type(value.get('passed')) is not bool:raise ValueError('passed must be boolean')
    result=asyncio.run(complete_json(Client(),'核对。','资料。',validate=validate))
    assert len(calls)==2 and result['passed'] is True
