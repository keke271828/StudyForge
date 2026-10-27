/* Render saved Markdown while retaining exact source coordinates for selections.
   Math/code are atomic. Unmappable syntax stays readable and asks for source mode;
   it is never located by searching for the first matching sentence globally. */
(() => {
 'use strict';
 const models=new WeakMap();
 function normalise(raw){
  let text='',map=[];
  for(let i=0;i<raw.length;i++){
   const start=i;if(raw[i]==='\r'&&raw[i+1]==='\n')i++;
   text+=raw[start]==='\r'?'\n':raw[start];map.push({start,end:i+1});
  }
  return {text,map};
 }
 function decode(value){const area=document.createElement('textarea');area.innerHTML=value;return area.value;}
 function sourceScope(value,scope,from=0){
  const at=scope.text.indexOf(value,from);
  if(at>=0)return {text:value,map:scope.map.slice(at,at+value.length),after:at+value.length};
  // Blockquotes and continued list items strip structural line prefixes.
  let cursor=from,map=[],lines=value.split('\n');
  for(let i=0;i<lines.length;i++){
   const line=lines[i],end=scope.text.indexOf('\n',cursor),lineEnd=end<0?scope.text.length:end;
   let begin=scope.text.indexOf(line,cursor);
   if(begin<cursor||begin+line.length>lineEnd)return null;
   if(i&& !/^[ \t]*(?:>[ \t]*)*(?:(?:[*+-]|\d+[.)])[ \t]+)?[ \t]*$/.test(scope.text.slice(cursor,begin)))return null;
   map.push(...scope.map.slice(begin,begin+line.length));cursor=begin+line.length;
   if(i<lines.length-1){const next=scope.text.indexOf('\n',cursor);if(next<0)return null;map.push(scope.map[next]);cursor=next+1;}
  }
  return {text:value,map,after:cursor};
 }
 function locate(tokens,scope){
  let cursor=0;
  for(const token of tokens||[]){
   const child=typeof token.raw==='string'?sourceScope(token.raw,scope,cursor):null;
   if(!child)continue;cursor=child.after;token.focusSource=child;
   if(token.type==='table')continue; // Preserve rendering; source mode handles ambiguous cell syntax.
   if(token.items)locate(token.items,child);
   else if(token.tokens)locate(token.tokens,child);
  }
 }
 function textUnits(value,map){
  const units=[];let shown='';
  for(let i=0;i<value.length;){
   const entity=value[i]==='&'?value.slice(i).match(/^&(?:#[xX][\da-fA-F]+|#\d+|[a-zA-Z][\da-zA-Z]+);/):null;
   const size=entity?entity[0].length:1,part=entity?decode(entity[0]):value[i];
   if(!map[i]||!map[i+size-1])return null;
   const span={start:map[i].start,end:map[i+size-1].end};
   shown+=part;for(let n=0;n<part.length;n++)units.push(span);i+=size;
  }
  return {shown,units};
 }
 function render(host,raw){
  models.delete(host);host.replaceChildren();
  host.dataset.rawText=raw;
  if(!window.marked||!window.DOMPurify||!window.katex){host.textContent=raw;models.delete(host);return;}
  const normalized=normalise(raw),protectedText=protectLessonMath(normalized.text);
  let text='',map=[],cursor=0;
  for(const formula of protectedText.formulas){
   text+=normalized.text.slice(cursor,formula.sourceStart);map.push(...normalized.map.slice(cursor,formula.sourceStart));
   const span={start:normalized.map[formula.sourceStart].start,end:normalized.map[formula.sourceEnd-1].end};
   text+=formula.token;for(let i=0;i<formula.token.length;i++)map.push(span);cursor=formula.sourceEnd;
  }
  text+=normalized.text.slice(cursor);map.push(...normalized.map.slice(cursor));
  const tokens=marked.lexer(text,{gfm:true,breaks:false});locate(tokens,{text,map});
  const entries=[],renderer=lessonRenderer(),baseText=marked.Renderer.prototype.text;
  function wrap(html,entry,block=false){const id=entries.push(entry)-1,tag=block?'div':'span';return '<'+tag+' data-source-fragment="'+id+'">'+html+'</'+tag+'>';}
  function atomic(token,html,block=false){
   const source=token.focusSource;
   return source?.map.length?wrap(html,{atomic:true,start:source.map[0].start,end:source.map.at(-1).end},block):html;
  }
  renderer.text=function(token){
   if(token.tokens)return this.parser.parseInline(token.tokens);
   if(token.type==='escape')return atomic(token,baseText.call(this,token));
   const source=token.focusSource;if(!source)return baseText.call(this,token);
   const pattern=new RegExp(protectedText.prefix+'(\\d+)Q','g');let html='',offset=0;
   function plain(end){
    if(end<=offset)return;
    const part=source.text.slice(offset,end),result=textUnits(part,source.map.slice(offset,end));
    const value=baseText.call(renderer,{...token,raw:part,text:part});
    html+=result?wrap(value,{...result,atomic:false}):value;
   }
   for(const match of source.text.matchAll(pattern)){
    plain(match.index);const end=match.index+match[0].length;
    html+=wrap(match[0],{atomic:true,start:source.map[match.index].start,end:source.map[end-1].end});offset=end;
   }
   plain(source.text.length);return html;
  };
  for(const name of ['codespan','code']){
   renderer[name]=function(token){return atomic(token,marked.Renderer.prototype[name].call(this,token),name==='code');};
  }
  const originalHtml=renderer.html,originalImage=renderer.image;
  renderer.html=function(token){return atomic(token,originalHtml.call(this,token));};
  renderer.image=function(token){return atomic(token,originalImage.call(this,token));};
  const html=marked.parser(tokens,{gfm:true,breaks:false,renderer});
  host.replaceChildren(lessonFragment(html,protectedText));
  host.querySelectorAll('[data-source-fragment]').forEach(element=>{
   const entry=entries[Number(element.dataset.sourceFragment)];
   if(!entry?.atomic&&element.textContent!==entry?.shown)element.removeAttribute('data-source-fragment');
  });
  models.set(host,{raw,entries});
 }
 function intersect(range,node){
  if(!range.intersectsNode(node))return null;
  const part=document.createRange();part.selectNodeContents(node);
  if(range.compareBoundaryPoints(Range.START_TO_START,part)>0)part.setStart(range.startContainer,range.startOffset);
  if(range.compareBoundaryPoints(Range.END_TO_END,part)<0)part.setEnd(range.endContainer,range.endOffset);
  return part.collapsed?null:part;
 }
 function selection(host){
  const model=models.get(host),chosen=window.getSelection();
  if(!model||!chosen?.rangeCount||chosen.isCollapsed)throw Error('请先拖选或长按选择正文中的原句。');
  const range=chosen.getRangeAt(0);
  if(!host.contains(range.startContainer)||!host.contains(range.endContainer))throw Error('请只在这份回答的正文中选取原句。');
  const bounds=[];let atoms=false;
  for(const element of host.querySelectorAll('[data-source-fragment]')){
   const part=intersect(range,element);if(!part)continue;
   const entry=model.entries[Number(element.dataset.sourceFragment)];if(!entry)continue;
   if(entry.atomic){bounds.push([entry.start,entry.end]);atoms=true;continue;}
   const before=document.createRange();before.selectNodeContents(element);before.setEnd(part.startContainer,part.startOffset);
   const start=before.toString().length,end=start+part.toString().length;
   if(end>start&&entry.units[start]&&entry.units[end-1])bounds.push([entry.units[start].start,entry.units[end-1].end]);
  }
  const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
   const node=walker.currentNode,part=intersect(range,node);
   if(part?.toString().trim()&&!node.parentElement.closest('[data-source-fragment]'))
    throw Error('这段表格或公式无法准确选中。请切换到“查看排版原文”，再选要追问的部分。');
  }
  if(!bounds.length)throw Error('先选中想追问的句子；不好选时，可切到“查看排版原文”。');
  let start=Math.min(...bounds.map(x=>x[0])),end=Math.max(...bounds.map(x=>x[1]));
  // Browser DOM ranges count UTF-16. Never cut a stored Unicode code point.
  if(start>0&&/[\uDC00-\uDFFF]/.test(model.raw[start])&&/[\uD800-\uDBFF]/.test(model.raw[start-1]))start--;
  if(end<model.raw.length&&/[\uD800-\uDBFF]/.test(model.raw[end-1])&&/[\uDC00-\uDFFF]/.test(model.raw[end]))end++;
  const text=model.raw.slice(start,end);
  if(!text.trim()||Array.from(text).length>3000)throw Error('请选取 1–3000 个原文字符；公式和代码会按完整内容引用。');
  return {start,end,text,atoms};
 }
 window.studyforgeSourceSelection={render,selection};
})();
