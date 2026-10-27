const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../web/operation_errors');

test('a rate-limit error retains exact Error semantics and does not call any service',()=>{
 const raw="exceeded retry limit, last status: 429 Too Many Requests",error=new Error(raw);error.requiresBrowser=true;
 const result=ui.capture(error,{status:429,path:'/api/chat/stream?token=private'});
 assert.equal(result,error);assert.equal(result.message,raw);assert.equal(result.requiresBrowser,true);
 assert.equal(result.operationInfo.kind,'rate_limit');assert.equal(result.operationInfo.path,'/api/chat/stream');
 assert(result.operationInfo.steps.some(s=>s.includes('不会自动发送')));
 assert.equal(ui.summary(raw),'AI 服务暂时限制了请求');
});

for(const raw of ['请先完整提交作业，再查看答案解析','完整提交前不开放答案'])test('locked answers take precedence over HTTP status: '+raw,()=>{
 const info=ui.describe(new Error(raw),{status:403});assert.equal(info.kind,'answers_locked');
 assert(!info.steps.join('').includes('API 密钥'));assert(info.steps[0].includes('先完成并提交'));
});

test('a local access restriction never recommends a website or API workaround',()=>{
 const info=ui.describe('此项目不属于当前对话',{status:403,path:'/api/conversations/other'});
 assert.equal(info.kind,'application_rule');assert.equal(info.message,'此项目不属于当前对话');assert(!info.steps.join('').includes('浏览器读取'));
});

test('mobile session expiry is distinct from a provider API-key error',()=>{
 assert.equal(ui.describe('Unauthorized',{status:401,mobile:true,mobileSession:true}).kind,'pairing');
 assert.equal(ui.describe('invalid_api_key',{status:401,mobile:true,mobileSession:false}).kind,'authentication');
 assert.equal(ui.describe('invalid_api_key',{status:401}).kind,'authentication');
});

test('failed exercise validation remains a failure rather than an invitation to bypass checking',()=>{
 const raw='RuntimeError:习题修订后仍有实质问题:第1题:独立解题未通过';
 const info=ui.describe(raw);assert.equal(info.kind,'exercise_check');assert.equal(info.raw,raw);
 assert(info.message.includes('暂未发布'));assert(!info.steps.join('').includes('直接发布'));
});

for(const [raw,kind]of [
 ['JSONDecodeError: Expecting value: line 1 column 1 (char 0)','response_format'],
 ['ConnectError: certificate verify failed','service_connection'],
 ['TypeError: Failed to fetch','local_connection'],
 ['ValueError: 无法排版公式: \\mathbb{Q}','formula'],
 ['insufficient_quota','quota'],
 ['https://example.invalid 403 Forbidden','access_denied'],
 ['TypeError: dict() got multiple values for keyword argument stage','unknown'],
 ['无法读取 PDF 第429页','unknown'],
 ['请将答案写在第429页','unknown']])test('bounded classification: '+raw,()=>{
 const info=ui.describe(raw);assert.equal(info.kind,kind);assert.equal(info.raw,raw);
 assert(info.steps.length>0);assert(!info.steps.join('').includes('资料已删除'));
});

test('existing plain Chinese instructions remain directly readable',()=>{
 assert.equal(ui.summary('请先选择一份资料，再开始通读'),'请先选择一份资料，再开始通读');
 assert.equal(ui.summary('RuntimeError:请先确认章节页码'),'请先确认章节页码');
});

test('presenting an error does not mutate source data or saved status and score',()=>{
 const row={status:'failed',progress:100,score:79,error:'JSONDecodeError: Expecting value'};
 const before=JSON.stringify(row);ui.summary(row.error);ui.describe(row.error);assert.equal(JSON.stringify(row),before);
});

test('AbortError identity and existing recovery context survive decoration',()=>{
 const cancelled=Object.assign(new Error('stop'),{name:'AbortError'});assert.equal(ui.capture(cancelled,{status:500}),cancelled);
 assert.equal(cancelled.operationInfo,undefined);
 const transport=ui.capture(new Error('socket disconnected'),{transport:'local',path:'/api/projects'});
 assert.equal(ui.capture(transport).operationInfo.kind,'local_connection');
 assert.equal(ui.capture(Object.freeze(new Error('frozen'))).message,'frozen');
});

test('details and copied payloads mask credentials while preserving useful diagnostics',()=>{
 const raw='ConnectError: API_KEY="sk-abcdefghijklmn" access_token=abc123 https://user:pass@host.test/a?token=xyz&n=2 Authorization: Bearer hidden-value';
 const safe=ui.describe(raw).raw;
 for(const secret of ['sk-abcdefghijklmn','abc123','user:pass','xyz','hidden-value'])assert(!safe.includes(secret),secret);
 assert(safe.includes('ConnectError'));assert(safe.includes('host.test'));assert(safe.includes('&n=2'));
 assert(ui.redact('x=2 and y=3').includes('x=2'));
 assert(!safe.includes('[已隐藏]]'));assert.equal(ui.redact(safe),safe);
 assert(!ui.redact('https://100.1.2.3:1234/#pair=12345678').includes('12345678'));
});

test('unexpected, circular and very long errors remain bounded without guessed completion',()=>{
 const circular={};circular.self=circular;assert.doesNotThrow(()=>ui.describe(circular));
 const long=ui.describe('x'.repeat(1000000));assert(long.raw.length<16500);assert.equal(long.kind,'unknown');assert(long.raw.includes('只显示前'));
});
