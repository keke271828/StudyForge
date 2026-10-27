/* Editing only changes teaching memory. Evidence and actual assessment grades remain intact. */
const profileState={offset:0,limit:30,total:0,token:0,editorToken:0,editor:null,saving:false,searchTimer:null};
const profileKindLabels={exposure:'读过或接触过的内容',understanding:'理解表现',gap:'待补知识',ability:'能力表现',preference:'教学偏好',strategy:'教学建议',assessment:'评估记录',self_report:'理解困难自评'};
const profileCategoryLabels={assessment:'做题或讲解记录',self_report:'你的自述',chat:'从学习对话中得到的初步判断',exposure:'读过或接触过的内容 · 不代表掌握',preference:'偏好 / 教学建议'};

function profileRecentAssessments(x){
  const records=(x.recent_assessments||[]).slice(0,3);if(!records.length)return '';
  const aid={assisted:'记录到提示或参考笔记',reported_no_aids:'软件未记录提示，你也说明没查笔记；是否借助其他帮助尚不清楚',unknown:'没有完整记录是否使用过提示或笔记'};
  const review=item=>item.is_review?' · 复习作答 · '+(item.same_question_verified===true?'已确认与上次是同一道题':'尚未确认与上次题目完全相同'):'';
  const date=value=>{const parsed=new Date(value);return value&&Number.isFinite(parsed.getTime())?parsed.toLocaleDateString(undefined,{year:'numeric',month:'2-digit',day:'2-digit'}):'日期未知';};
  return `<section class="profile-recent-assessments"><h4>最近的评分 · 最新在前</h4><ol>${records.map(item=>`<li><div><b>${escapeHtml(item.kind)} ${Number(item.score).toFixed(0)} / 100</b><time datetime="${escapeHtml(item.recorded_at||'')}">${escapeHtml(date(item.recorded_at))}</time></div><small>${escapeHtml(aid[item.aid_status]||aid.unknown)}${review(item)}${item.delay_hours!=null?' · 间隔 '+Number(item.delay_hours).toFixed(1)+' 小时':''}</small></li>`).join('')}</ol><p>前后题目、难度和使用的提示可能不同，分数不能直接比较；一次高分还需要后续练习确认。</p></section>`;
}

function profileScoreCard(x){
  const practice=x.has_practice_context?`<small>使用提示或笔记的作答 ${x.assisted_count} 次 · 复习 ${x.review_count} 次<br>已确认与上次是同一道题、间隔≥24小时且自报未看笔记 / 未用软件提示 ${x.delayed_count} 次；是否借助其他帮助尚不清楚</small>`:'';
  const combined=x.learning_score??x.score,basis=x.learning_score_basis;
  const label=basis==='self_report_only'?'只有自评 · 还未测验':basis==='assessment_and_self_report'?'综合掌握参考分':basis==='assessment_only'?'根据作答估计 · 尚未加上自评':'暂无可用评分';
  const formula=basis==='assessment_and_self_report'?`作答 ${x.score} × ${100-x.self_report_weight}% + 自评 ${x.self_rating} × ${x.self_report_weight}%`:'缺少的评分不会按 0 分计算';
  const gap=x.self_rating_gap!=null&&Math.abs(x.self_rating_gap)>=20?`<p class="profile-calibration">自评比题目作答评分${x.self_rating_gap>0?'高':'低'} ${Math.abs(x.self_rating_gap)} 分。可向导师核对理解或做一次短测；分差本身不能确定错因。</p>`:'';
  return `<div class="profile-card" data-profile-topic="${escapeHtml(x.topic)}"><h3>${escapeHtml(x.topic)}</h3><span class="small-note">${label}${x.score_basis==='legacy_summary'?' · 早期汇总，找不到每次评分的明细':''}</span>${combined==null?'<strong class="profile-no-score">未测验</strong>':`<div class="score-bar"><i style="width:${combined}%"></i></div><strong class="profile-combined-score">${Number(combined).toFixed(1)}<small>/100</small></strong>`}<small>${formula}<br>题目作答评分 ${x.score??'未测验'} · 你自评的掌握程度 ${x.self_rating??'未自评'} · 你觉得有多难 ${x.difficulty_rating??'未自评'}<br>${x.assessment_count==null?'评估次数未能核实':x.assessment_count+' 条评分记录'} · 做题评分 ${x.quiz_score??'—'} · 自己讲解的评分 ${x.feynman_score??'—'}</small>${gap}${practice}${profileRecentAssessments(x)}${x.score_basis==='legacy_summary'?`<button class="secondary" type="button" data-remove-legacy="${escapeHtml(x.topic)}">移出早期汇总</button>`:''}</div>`;
}

function showProfileWeight(weight){
  $('profileWeightValue').textContent=weight+'%';
  $('profileWeightFormula').textContent=`题目作答评分 × ${100-weight}% + 最近有效自评 × ${weight}%`;
}

async function renderLearningProfile(loadControls=true){
  const token=++profileState.token;
  const params=new URLSearchParams({search:$('profileSearch').value.trim(),category:$('profileCategory').value,status:$('profileStatus').value,offset:profileState.offset,limit:profileState.limit});
  const [rows,memory,config,removedLegacy,scoring]=await Promise.all([api('/api/profile'),api('/api/profile/memory?'+params),loadControls?api('/api/settings'):Promise.resolve(null),api('/api/profile/legacy'),loadControls?api('/api/profile/scoring'):Promise.resolve(null)]);
  if(token!==profileState.token)return;
  if(profileState.offset>=memory.filtered_count&&profileState.offset>0){profileState.offset=Math.max(0,Math.floor((memory.filtered_count-1)/profileState.limit)*profileState.limit);return renderLearningProfile(false);}
  $('profile').innerHTML=rows.length?rows.map(profileScoreCard).join(''):'<p class="small-note">还没有可用评分。上传资料、让 AI 阅读或聊天都不会自动加分；完成作答或填写自评后再看。</p>';
  $('ratingTopics').innerHTML=rows.slice(0,200).map(row=>`<option value="${escapeHtml(row.topic)}"></option>`).join('');
  $('removedLegacyProfiles').hidden=!removedLegacy.length;
  $('removedLegacyProfiles').querySelector('div').innerHTML=removedLegacy.map(x=>`<p>${escapeHtml(x.topic)} <button class="secondary" type="button" data-restore-legacy="${escapeHtml(x.topic)}">重新采用这条早期汇总</button></p>`).join('');
  if(config){$('backgroundLearningEnabled').checked=config.background_learning_enabled!==false;$('backgroundLearningInterval').value=config.background_learning_interval_minutes;$('backgroundLearningDailyLimit').value=config.background_learning_daily_limit;}
  if(scoring){$('profileSelfWeight').value=scoring.self_report_weight;showProfileWeight(scoring.self_report_weight);}
  const labels={running:'正在整理',completed:'整理完成',failed:'整理失败，将限次重试',interrupted:'已让位于当前操作，稍后继续'};
  $('memoryStatus').textContent=`${memory.enabled?'已开启':'已关闭'} · ${memory.pending} 条待整理 · 今日 ${memory.today_calls}/${memory.daily_limit} 次${memory.latest_run?' · '+(labels[memory.latest_run.status]||memory.latest_run.status):''}`;
  profileState.total=memory.filtered_count;
  $('profileCount').textContent=`${memory.total_insights} 条正在使用的学习记录 · 当前筛选 ${memory.filtered_count} 条`;
  $('learningMemory').innerHTML=memory.insights.map(item=>`<article class="memory-card${item.deleted?' memory-removed':''}"><div><strong>${escapeHtml(item.topic)}</strong><span class="count-pill">${escapeHtml(profileCategoryLabels[item.category])}</span></div><p>${escapeHtml(item.observation)}</p><div class="memory-card-footer"><small>${escapeHtml(item.confidence)} · ${escapeHtml(item.project_name||'跨项目自评')} · ${escapeHtml(new Date(item.updated_at).toLocaleString())}</small><button class="secondary" type="button" data-profile-insight="${item.id}">${item.deleted?'查看 / 恢复':'查看原记录 / 修改判断'}</button></div></article>`).join('')||'<p class="small-note">没有找到符合条件的学习记录。可以换关键词，或清除筛选。</p>';
  $('profilePage').textContent=memory.filtered_count?`${Math.floor(profileState.offset/profileState.limit)+1} / ${Math.ceil(memory.filtered_count/profileState.limit)} 页`:'0 条记录';
  $('profilePrevious').disabled=profileState.offset===0;$('profileNext').disabled=profileState.offset+profileState.limit>=memory.filtered_count;
}

function fillProfileEditor(result){
  profileState.editor=result.insight;
  const item=result.insight;
  $('profileEvidenceTopic').textContent=item.topic;
  $('profileEvidenceMeta').textContent=`${profileKindLabels[item.kind]} · ${item.confidence} · ${item.project_name||'跨项目自评'}${item.deleted?' · 已移出画像':''}`;
  $('profileCorrection').value=item.observation;
  $('profileCorrection').disabled=item.deleted;
  $('saveProfileCorrection').hidden=item.deleted;$('resetProfileCorrection').hidden=item.deleted||item.correction===null;
  $('removeProfileInsight').hidden=item.deleted;$('restoreProfileInsight').hidden=!item.deleted;
  $('profileOriginalObservation').textContent=item.original_observation;
  $('profileEvidenceQuote').textContent=item.quote;
  $('profileEvidenceText').textContent=result.evidence_text||'这条旧记录没有保存你的原话，无法进一步核对当时的理解。';
  $('profileEvidenceFeedback').textContent=result.feedback?'原评估反馈：'+result.feedback:'';
  $('profileEvidenceSources').textContent=result.sources.length?'资料：'+result.sources.map(x=>x.name).join('、'):'';
  $('profileEvidenceNotice').textContent=result.notice+(result.truncated?' 这里最多显示原记录前 24000 个字符；后面的内容没有显示，不代表已经检查过。':'');
  $('profileEvidenceBody').hidden=false;
  $('profileRemovalConfirm').hidden=true;
  $('profileEvidenceStatus').textContent=item.deleted?'这条记录已停用，导师不会再参考它；恢复后会采用当前显示的判断。':'先看原记录，再写出你认为应当采用的判断。保存修改不会请求 AI。';
}

async function openProfileInsight(id){
  if(profileState.saving)return;
  const token=++profileState.editorToken;
  profileState.editor=null;
  $('profileEvidenceBody').hidden=true;$('profileEvidenceStatus').textContent='正在读取原记录…';
  if(!$('profileEvidenceDialog').open)$('profileEvidenceDialog').showModal();
  try{const result=await api(`/api/profile/insights/${id}/evidence`);if(token===profileState.editorToken&&$('profileEvidenceDialog').open)fillProfileEditor(result);}
  catch(failure){if(token===profileState.editorToken)$('profileEvidenceStatus').textContent=failure.message;}
}

async function changeProfileInsight(action){
  const item=profileState.editor;
  if(!item||profileState.saving)return;
  const draft=$('profileCorrection').value.trim();
  if(action==='correct'&&!draft){$('profileEvidenceStatus').textContent='请填写纠正内容。';return;}
  profileState.saving=true;
  for(const button of $('profileEvidenceDialog').querySelectorAll('button'))button.disabled=true;
  $('profileEvidenceStatus').textContent='正在保存…';
  try{
    const path=`/api/profile/insights/${item.id}`;
    await api(action==='remove'?path+'?version='+item.version:action==='restore'?path+'/restore':path,
      action==='remove'?{method:'DELETE'}:jsonOptions(action==='restore'?'POST':'PATCH',action==='restore'?{version:item.version}:{version:item.version,correction:action==='reset'?null:draft}));
    fillProfileEditor(await api(path+'/evidence'));
    $('profileEvidenceStatus').textContent=action==='remove'?'已移出画像；后续教学不再采用这条判断或分数。':action==='restore'?'已恢复到画像。':'已保存。之后聊天、生成讲解和出题时，导师会参考这条更新后的记录。';
    await refreshProfile(false);
  }catch(failure){$('profileEvidenceStatus').textContent=failure.message+' 可关闭后重新打开核对；当前填写内容保留。';}
  finally{profileState.saving=false;for(const button of $('profileEvidenceDialog').querySelectorAll('button'))button.disabled=false;}
}

document.addEventListener('click',event=>{
  const target=event.target.closest('[data-profile-insight],[data-remove-legacy],[data-restore-legacy],#profilePrevious,#profileNext,#closeProfileEvidence,#saveProfileCorrection,#resetProfileCorrection,#removeProfileInsight,#restoreProfileInsight,#confirmProfileRemoval,#cancelProfileRemoval');
  if(!target)return;
  if(target.dataset.removeLegacy||target.dataset.restoreLegacy){
    const removed=!!target.dataset.removeLegacy,topic=target.dataset.removeLegacy||target.dataset.restoreLegacy;
    if(removed&&!target.dataset.confirmed){target.dataset.confirmed='true';target.textContent='确认移出（原成绩保留）';return;}
    target.disabled=true;
    api('/api/profile/legacy',jsonOptions('PUT',{topic,removed})).then(()=>refreshProfile(false)).catch(error).finally(()=>target.disabled=false);return;
  }
  if(target.dataset.profileInsight){openProfileInsight(Number(target.dataset.profileInsight));return;}
  if(target.id==='profilePrevious'||target.id==='profileNext'){profileState.offset+=target.id==='profileNext'?profileState.limit:-profileState.limit;refreshProfile(false).catch(error);return;}
  if(target.id==='closeProfileEvidence'){
    if(!profileState.saving){profileState.editorToken++;profileState.editor=null;$('profileEvidenceDialog').close();}
    return;
  }
  if(target.id==='removeProfileInsight'){$('profileRemovalConfirm').hidden=false;return;}
  if(target.id==='cancelProfileRemoval'){$('profileRemovalConfirm').hidden=true;return;}
  const actions={saveProfileCorrection:'correct',resetProfileCorrection:'reset',restoreProfileInsight:'restore',confirmProfileRemoval:'remove'};
  if(actions[target.id])changeProfileInsight(actions[target.id]).catch(error);
});
document.addEventListener('input',event=>{
  if(event.target.id==='profileSelfWeight'){showProfileWeight(Number(event.target.value));$('profileScoringStatus').textContent='点击应用后影响后续教学。';return;}
  if(event.target.id!=='profileSearch')return;
  clearTimeout(profileState.searchTimer);profileState.offset=0;
  profileState.searchTimer=setTimeout(()=>refreshProfile(false).catch(error),250);
});
document.addEventListener('click',async event=>{
  if(!event.target.closest('#saveProfileScoring'))return;
  const button=$('saveProfileScoring');button.disabled=true;
  try{
    await api('/api/profile/scoring',jsonOptions('PUT',{self_report_weight:Number($('profileSelfWeight').value)}));
    await refreshProfile(false);$('profileScoringStatus').textContent='已应用；综合分及后续导师、讲解与习题使用的画像已更新。';
  }catch(failure){$('profileScoringStatus').textContent=failure.message;}
  finally{button.disabled=false;}
});
document.addEventListener('change',event=>{if(['profileCategory','profileStatus'].includes(event.target.id)){profileState.offset=0;refreshProfile(false).catch(error);}});
document.addEventListener('cancel',event=>{if(event.target.id==='profileEvidenceDialog'&&profileState.saving)event.preventDefault();},true);
document.addEventListener('close',event=>{
  // Native close is queued. A previous close event must not invalidate a
  // different record opened in the meantime (keyboard/fast consecutive clicks).
  if(event.target.id==='profileEvidenceDialog'&&!event.target.open){profileState.editorToken++;profileState.editor=null;}
},true);
