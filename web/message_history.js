/* One current history per host. Preserve stable message DOM and public text only. */
(()=>{
 const histories=new WeakMap(),pages=new WeakMap();
 const values=rows=>(rows||[]).map((row,index)=>({id:String(row.id??'position-'+index),role:row.role,content:String(row.content??''),reply_reference:row.reply_reference,referenceKey:row.reply_reference?JSON.stringify(row.reply_reference):''}));
 function matches(host,rows,scope){
  const saved=histories.get(host),incoming=values(rows);
  return Boolean(saved&&saved.scope===scope&&saved.order.length===incoming.length&&incoming.every((row,index)=>{
   const old=saved.rows.get(row.id);return saved.order[index]===row.id&&old&&old.node.parentNode===host&&old.role===row.role&&old.content===row.content&&old.referenceKey===row.referenceKey;
  }));
 }
 function sync(host,rows,create,{scope='',preserve=[]}={}){
  const incoming=values(rows),saved=histories.get(host),previous=saved?.scope===scope?saved.rows:new Map(),next=new Map(),nodes=[];
  let rendered=0,retained=0,removed=0,changed=false;
  for(const row of incoming){
   if(next.has(row.id))throw new Error('重复的历史消息标识');
   const old=previous.get(row.id);
   let node;
   if(old&&old.node.parentNode===host&&old.role===row.role&&old.content===row.content&&old.referenceKey===row.referenceKey){node=old.node;retained++;}
   else{node=create(row);node.dataset.messageId=row.id;rendered++;}
   next.set(row.id,{...row,node});nodes.push(node);
  }
  for(const node of preserve)if(node&&node.parentNode===host&&!nodes.includes(node))nodes.push(node);
  const older=pages.get(host)?.button;if(older?.parentNode===host&&pages.get(host).hasOlder)nodes.unshift(older);
  const wanted=new Set(nodes);
  for(const child of [...host.childNodes])if(!wanted.has(child)){child.remove();removed++;changed=true;}
  // Initial restoration is a single attachment; no per-message scrollHeight.
  if(!host.firstChild&&nodes.length){const fragment=document.createDocumentFragment();nodes.forEach(node=>fragment.append(node));host.append(fragment);changed=true;}
  else{let cursor=host.firstChild;for(const node of nodes){if(node===cursor)cursor=cursor.nextSibling;else{host.insertBefore(node,cursor);changed=true;}}}
  histories.set(host,{scope,rows:next,order:incoming.map(row=>row.id)});
  return {changed,rendered,retained,removed};
 }
 function begin(host,id,payload){const old=pages.get(host);old?.button?.remove();pages.set(host,{id,range:0,rows:payload.messages||[],revision:payload.history?.revision,oldest:payload.history?.oldest_cursor,hasOlder:Boolean(payload.history?.has_older)});}
 function request(host,{older=false,force=false}={}){const state=pages.get(host),query=new URLSearchParams({limit:'60'});if(!state)return null;
  if(older){if(!state.hasOlder||!state.oldest)return null;query.set('before',state.oldest);}
  else{if(state.oldest)query.set('start',state.oldest);if(!force&&state.revision!==undefined)query.set('since',state.revision);}
  return {state,range:state.range,older,query:String(query)};
 }
 function apply(host,payload,ticket){const state=pages.get(host);if(!ticket||state!==ticket.state||state.range!==ticket.range||payload.not_modified)return null;
  if(ticket.older){const combined=new Map((payload.messages||[]).map(row=>[row.id,row]));state.rows.forEach(row=>combined.set(row.id,row));state.rows=[...combined.values()].sort((a,b)=>a.created_at.localeCompare(b.created_at)||(a._order||0)-(b._order||0));state.range++;
   // A newer poll may have run while this older page was in flight. Its version
   // covered only the previous range; recheck the expanded range if snapshots differ.
   state.revision=Math.min(state.revision??0,payload.history?.revision??0);
   if(payload.history?.oldest_cursor)state.oldest=payload.history.oldest_cursor;state.hasOlder=Boolean(payload.history?.has_older);
  }else{state.rows=payload.messages||[];state.revision=payload.history?.revision;state.oldest=payload.history?.oldest_cursor;state.hasOlder=Boolean(payload.history?.has_older);}
  return state.rows;
 }
 function install(host,load){const state=pages.get(host);if(!state)return;if(!state.hasOlder){state.button?.remove();return;}
  const button=state.button||(state.button=document.createElement('button'));button.type='button';button.className='history-load-older';button.textContent=state.loading?'正在加载更早记录…':'↑ 加载更早的对话';button.disabled=Boolean(state.loading);
  button.onclick=async()=>{if(state.loading||pages.get(host)!==state)return;state.loading=true;install(host,load);try{await load();}finally{state.loading=false;if(pages.get(host)===state)install(host,load);}};
  if(host.firstChild!==button)host.prepend(button);
 }
 window.studyforgeHistoryPages={begin,request,apply,install,state:host=>pages.get(host)};
 window.studyforgeMessageHistory={sync,matches,ids:host=>new Set(histories.get(host)?.order||[]),reset:host=>{histories.delete(host);pages.delete(host);}};
})();
