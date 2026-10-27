"""Small task views. Full intent/results stay in jobs for execution and detail."""
from .db import j,many,unj

PAYLOAD_KEYS=('project_id','source_ids','reading_id','workflow_version','only_exercises','set_id','conversation_id','provider','model','reasoning_effort')
RESULT_KEYS=('stage','request_status','source_id','reading_id','knowledge_map_id','requires_browser',
             'parallel','scheduling_note','waiting_for_causes','homework_attempt_id')
PUBLIC_PAYLOAD_KEYS=('only_exercises','reading_id','set_id','conversation_id','provider','model','reasoning_effort')


def projection(column,keys):
    valid=f"CASE WHEN json_valid({column}) THEN {column} ELSE '{{}}' END"
    return 'json_extract('+valid+','+','.join("'$."+key+"'" for key in keys)+')'


def columns():
    # JSON paths are fixed internal names. Selecting a projection prevents
    # sqlite3/Python from copying a full private dialogue for every listed job.
    payload="CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END"
    values=f"json_extract({payload},'$.values')"
    truth=(f"CASE WHEN kind IN ('generate','read','knowledge') THEN 0 ELSE CASE json_type({payload},'$.values') "
           f"WHEN 'text' THEN length({values})>0 WHEN 'object' THEN json({values})<>'{{}}' "
           f"WHEN 'array' THEN json({values})<>'[]' ELSE COALESCE({values},0)<>0 END END")
    return ('id,project_id,kind,status,progress,error,created_at,updated_at,'+
            projection('payload_json',PAYLOAD_KEYS)+' AS _payload_fields,'+
            projection('result_json',RESULT_KEYS)+' AS _result_fields,'+truth+' AS _values_present')


def expand(row):
    payload={key:value for key,value in zip(PAYLOAD_KEYS,unj(row.pop('_payload_fields'),[])) if value is not None}
    payload['values']=bool(row.pop('_values_present'))
    row['payload_json']=j(payload)
    row['result_json']=j({key:value for key,value in zip(RESULT_KEYS,unj(row.pop('_result_fields'),[])) if value is not None})
    for key in PUBLIC_PAYLOAD_KEYS:row[key]=payload.get(key)
    return row


def public_payload(payload):
    return {key:payload[key] for key in PUBLIC_PAYLOAD_KEYS if key in payload}


def execution(rows):
    result={row['id']:{} for row in rows}
    ids=list(result)
    for start in range(0,len(ids),400):
        batch=ids[start:start+400]
        spans=many("SELECT job_id,status,COUNT(*) AS count FROM execution_spans WHERE job_id IN ("+
            ','.join('?' for _ in batch)+") AND resource='model' AND status IN ('queued','running') GROUP BY job_id,status",tuple(batch))
        for span in spans:result[span['job_id']][span['status']]=span['count']
    return result
