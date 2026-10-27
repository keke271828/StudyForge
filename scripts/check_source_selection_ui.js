/* Runs inside a real browser with the production renderer and selection API. */
module.exports=async function(win){
 return await win.webContents.executeJavaScript('('+function(){
  const host=document.createElement('div');host.style.cssText='max-width:700px;padding:20px;background:white;color:black';document.body.append(host);
  const cases=[];
  function pickText(needle,which=0){
   const walker=document.createTreeWalker(host,NodeFilter.SHOW_TEXT);let count=0;
   while(walker.nextNode()){
    const node=walker.currentNode;if(node.parentElement.closest('.katex'))continue;
    let index=node.textContent.indexOf(needle);
    while(index>=0){if(count++===which){const range=document.createRange();range.setStart(node,index);range.setEnd(node,index+needle.length);const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);return;}index=node.textContent.indexOf(needle,index+needle.length);}
   }
   throw Error('Visible text not found: '+needle);
  }
  function check(name,raw,needle,expected,which=0){
   studyforgeSourceSelection.render(host,raw);pickText(needle,which);
   const selected=studyforgeSourceSelection.selection(host);
   if(selected.text!==expected||raw.slice(selected.start,selected.end)!==expected)throw Error(name+': '+JSON.stringify(selected));
   cases.push(name);
  }
  try{
   check('plain repeated sentence','重复原句。重复原句。','重复原句。','重复原句。',1);
   const repeated='重复原句。**重复原句。**';studyforgeSourceSelection.render(host,repeated);pickText('重复原句。',1);
   const last=studyforgeSourceSelection.selection(host);if(last.start!==repeated.lastIndexOf('重复原句。'))throw Error('Repeated formatted sentence mapped to earlier occurrence');cases.push('formatted repeat exact location');
   check('heading','## 定理内容','定理内容','定理内容');
   check('strong','说明 **关键条件**。','关键条件','关键条件');
   check('Unicode','🔎 𝑁 与 😀 都是字符。','𝑁','𝑁');
   check('CRLF','第一行\r\n第二行','第一行\n第二行','第一行\r\n第二行');
   check('HTML entity','A &amp; B &#x1F600; C','&','&amp;');
   check('Unicode entity','A &amp; B &#x1F600; C','😀','&#x1F600;');
   check('escaped punctuation','这里用 \\* 表示星号。','*','\\*');
   check('escaped angle','比较 \\< 与大于。','<','\\<');
   check('link label versus URL','[同名](https://example.com/同名) 后面的同名','同名','同名',1);
   check('multiline blockquote','> 第一行\n> 第二行','第二行','第二行');
   check('list strong','- 第一项\n- **第二项**','第二项','第二项');
   check('nested list','- 外层\n  - 内层条目','内层条目','内层条目');
   check('inline code is complete','说明 `a < b && b < c`。','b','`a < b && b < c`');
   const code='```python\nx = 1\nprint(x)\n```\n';check('code block is complete',code,'print',code);
   for(const formula of ['$x^2$','\\(A_{ij}=(-1)^{i+j}M_{ij}\\)','$$x=\\frac{a}{b}$$','\\[\\mathbb{Q}(\\sqrt{2})\\]']){
    const raw='定义：'+formula+'。';studyforgeSourceSelection.render(host,raw);
    const math=host.querySelector('.katex-html .mord')||host.querySelector('.katex-html');if(!math)throw Error('Formula not rendered: '+formula);
    const range=document.createRange();range.selectNodeContents(math);const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);
    const result=studyforgeSourceSelection.selection(host);if(result.text!==formula)throw Error('Partial formula lost source: '+JSON.stringify(result));cases.push('atomic formula '+formula.slice(0,12));
   }
   studyforgeSourceSelection.render(host,'左 **中间** 右。');
   const spans=[...host.querySelectorAll('[data-source-fragment]')],range=document.createRange();range.setStart(spans[0].firstChild,0);range.setEnd(spans.at(-1).firstChild,2);window.getSelection().removeAllRanges();window.getSelection().addRange(range);
   if(studyforgeSourceSelection.selection(host).text!=='左 **中间** 右')throw Error('Cross-format range changed');cases.push('range across emphasis');
   studyforgeSourceSelection.render(host,'| 项目 | 含义 |\n| --- | --- |\n| 甲 | 乙 |');pickText('甲');
   let refused=false;try{studyforgeSourceSelection.selection(host);}catch(e){refused=e.message.includes('切换');}if(!refused)throw Error('Unmapped table selection guessed its location');cases.push('unmapped syntax requests source mode');
   studyforgeSourceSelection.render(host,'<script>window.focusSelectionInjected=true</script>\n\n<img src="https://example.invalid/x" onerror="window.focusSelectionInjected=true">');
   if(window.focusSelectionInjected||host.querySelector('script,img'))throw Error('Untrusted markup executed or loaded');cases.push('markup remains inert');
   studyforgeSourceSelection.render(host,'正文 '+('字'.repeat(3001)));pickText('字'.repeat(3001));refused=false;try{studyforgeSourceSelection.selection(host);}catch(e){refused=e.message.includes('3000');}if(!refused)throw Error('Selection length bypassed');cases.push('original character limit preserved');
   return {passed:true,cases};
  }finally{window.getSelection()?.removeAllRanges();host.remove();}
 }.toString()+')()');
};
