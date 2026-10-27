const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/teaching_review.js'),'utf8'),context);
const {create,describe,issueStatus}=context.window.studyforgeTeachingReview;
test('private exercises, coding and malformed metadata cannot create an inspector',()=>{
  for(const kind of ['exercises','exercise','coding','grading','review',undefined])
    assert.equal(create({reviews:[{result:{solution:'PRIVATE'}}]},'a',kind),null);
  for(const meta of [null,undefined,[],{}, {reviews:[]}])assert.equal(create(meta,'a','explanation'),null);
});
test('a passed flag with issues cannot certify correctness',()=>{
  assert.match(describe({passed:true,issues:[{problem:'条件不足'}]}),/仍列出疑点/);
  assert.match(describe({passed:true,issues:[]}),/仍可能漏检/);
  assert.match(describe({passed:false,issues:[]}),/未确认通过/);
  for(const passed of [null,undefined,{},'true'])assert.match(describe({passed}),/未记录独立核查通过/);
});
test('revision records do not silently resolve an earlier issue',()=>{
  const report={passed:false,issues:[{problem:'需核对'}],locally_corrected_issues:[0]};
  assert.match(describe(report),/不代表最终稿仍然错误/);
  assert.match(issueStatus(report,0),/局部修订.*未再次独立复核/);
  assert.match(issueStatus(report,1),/结合交付稿核对/);
  for(const invalid of [true,false,'0',null,-1]){
    assert.match(issueStatus({locally_corrected_issues:[invalid]},0),/结合交付稿核对/);
  }
});
