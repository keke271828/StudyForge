/* Decorative backgrounds never enter the material uploader or AI context. */
const backgroundDefaults={ui_background:'none',ui_background_asset:'',ui_background_name:'',
  ui_background_transparency:35,ui_background_blur:8,ui_background_x:50,ui_background_y:50,
  ui_background_quiet_focus:true};
const backgroundPaints={
  none:'none',
  mist:'radial-gradient(ellipse at 8% 18%,#87b3a5 0,transparent 55%),radial-gradient(ellipse at 86% 82%,#d7b993 0,transparent 52%),linear-gradient(135deg,#e9eee4,#bccfc4)',
  dusk:'radial-gradient(ellipse at 88% 15%,#627eab 0,transparent 58%),radial-gradient(ellipse at 12% 85%,#6c678c 0,transparent 56%),linear-gradient(140deg,#17283f,#436575)',
  aurora:'radial-gradient(ellipse at 78% 5%,#b3d4bf 0,transparent 60%),radial-gradient(ellipse at 4% 70%,#b7b8d9 0,transparent 55%),linear-gradient(120deg,#dbe6dc,#eadbcc)',
};
let backgroundLoadingAsset='',backgroundImageGeneration=0;
const backgroundRanges=[['backgroundTransparency','ui_background_transparency','%'],['backgroundBlur','ui_background_blur',' px'],
  ['backgroundX','ui_background_x','%'],['backgroundY','ui_background_y','%']];

function applyBackgroundPreferences(next){
  const root=document.documentElement,mode=next.ui_background||'none',asset=next.ui_background_asset||'';
  root.dataset.background=mode;root.dataset.quietBackground=String(next.ui_background_quiet_focus);
  root.style.setProperty('--background-alpha',String((100-next.ui_background_transparency)/100));
  root.style.setProperty('--background-blur',next.ui_background_blur+'px');
  root.style.setProperty('--background-x',next.ui_background_x+'%');root.style.setProperty('--background-y',next.ui_background_y+'%');
  if(mode!=='image')root.style.setProperty('--background-paint',backgroundPaints[mode]||'none');
  if(asset!==backgroundLoadingAsset){
    backgroundLoadingAsset=asset;const generation=++backgroundImageGeneration;
    if(/^[a-f0-9]{64}$/.test(asset)){
      const url='/api/appearance/background/'+asset,picture=new Image();
      picture.onload=()=>{
        if(generation!==backgroundImageGeneration)return;
        root.style.setProperty('--background-image',`url("${url}")`);
        if(studioPreferences.ui_background==='image')root.style.setProperty('--background-paint','var(--background-image)');
        const notice=document.getElementById('backgroundImageNotice');if(notice)notice.textContent='已保存在本机，原图片不改动';
      };
      picture.onerror=()=>{
        if(generation!==backgroundImageGeneration)return;
        root.style.setProperty('--background-image','none');if(studioPreferences.ui_background==='image')root.style.setProperty('--background-paint','none');
        const notice=document.getElementById('backgroundImageNotice');if(notice)notice.textContent='背景图片不可用，请重新选择图片；学习内容不受影响';
      };
      picture.src=url;
    }else{
      root.style.setProperty('--background-image','none');
      const notice=document.getElementById('backgroundImageNotice');if(notice)notice.textContent='PNG / JPEG / WebP · 最大 20 MB · 可拖入这里';
    }
  }
  if(mode==='image')root.style.setProperty('--background-paint','var(--background-image,none)');
  for(const [id,key,suffix] of backgroundRanges){
    const input=document.getElementById(id);if(input)input.value=next[key];
    const output=document.getElementById(id+'Value');if(output)output.value=next[key]+suffix;
  }
  for(const button of document.querySelectorAll('[data-background-choice]')){
    button.setAttribute('aria-pressed',String(button.dataset.backgroundChoice===mode));
    if(button.dataset.backgroundChoice==='image')button.disabled=!asset;
  }
  const quiet=document.getElementById('backgroundQuietFocus');if(quiet)quiet.checked=next.ui_background_quiet_focus;
  const name=document.getElementById('backgroundFilename');if(name)name.textContent=next.ui_background_name||'还没有选择图片';
  const remove=document.getElementById('removeBackgroundImage');if(remove)remove.disabled=!asset;
  const positions=document.getElementById('backgroundPosition');if(positions)positions.hidden=mode!=='image';
  const preview=document.getElementById('backgroundPreview');if(preview)preview.dataset.background=mode;
  const caption=document.getElementById('backgroundPreviewCaption');
  if(caption)caption.textContent=mode==='none'?'纯净背景 · 各区域的透明效果在下方“各区域外观”调整':
    '背景透明度 '+next.ui_background_transparency+'% · 模糊 '+next.ui_background_blur+' px';
}

async function uploadBackgroundFile(file){
  if(!file)return;
  if(file.size>20*1024*1024)return toast('请选择不超过 20 MB 的图片');
  if(!/\.(png|jpe?g|webp)$/i.test(file.name))return toast('背景支持 PNG、JPEG 和 WebP 图片');
  const body=new FormData();body.append('file',file);
  const button=document.getElementById('chooseBackgroundImage');button.disabled=true;
  try{await saveStudioAction(()=>api('/api/appearance/background',{method:'POST',body}));}
  finally{button.disabled=false;}
}

function initializeBackground(){
  const layer=document.createElement('div');layer.id='workspaceBackdrop';layer.className='workspace-backdrop';layer.setAttribute('aria-hidden','true');
  document.body.prepend(layer);
  const card=document.createElement('div');card.className='settings-card background-settings-card';
  card.innerHTML=`<div class="settings-card-head background-card-head"><div><span>你的学习空间</span><h3>给思考留一处喜欢的背景</h3><p>轻轻调整氛围，让文字、公式与原文始终站在前面。</p></div><button id="resetBackground" type="button">恢复背景默认</button></div>
    <div class="background-layout"><div class="background-controls">
      <div class="background-presets" role="group" aria-label="背景方案">
        <button type="button" data-background-choice="none"><i class="background-swatch swatch-none"></i><span>纯净</span><small>留白与专注</small></button>
        <button type="button" data-background-choice="mist"><i class="background-swatch swatch-mist"></i><span>山岚</span><small>柔和青绿</small></button>
        <button type="button" data-background-choice="dusk"><i class="background-swatch swatch-dusk"></i><span>暮蓝</span><small>沉静夜读</small></button>
        <button type="button" data-background-choice="aurora"><i class="background-swatch swatch-aurora"></i><span>晨光</span><small>淡彩与暖意</small></button>
        <button type="button" data-background-choice="image"><i class="background-swatch swatch-image"></i><span>我的图片</span><small>本地自定义</small></button>
      </div>
      <div id="backgroundImageDrop" class="background-upload"><div><strong id="backgroundFilename">还没有选择图片</strong><small id="backgroundImageNotice">PNG / JPEG / WebP · 最大 20 MB · 可拖入这里</small></div><div class="background-upload-actions"><button id="chooseBackgroundImage" type="button">选择图片</button><button id="removeBackgroundImage" type="button" disabled>删除图片</button></div><input id="backgroundImageFile" type="file" accept=".png,.jpg,.jpeg,.webp" hidden></div>
      <div class="background-sliders">
        <label for="backgroundTransparency"><span>背景透明度 <output id="backgroundTransparencyValue">35%</output></span><input id="backgroundTransparency" type="range" min="0" max="100" step="1"><small>越高越淡；100% 时完全隐藏背景</small></label>
        <label for="backgroundBlur"><span>背景模糊度 <output id="backgroundBlurValue">8 px</output></span><input id="backgroundBlur" type="range" min="0" max="24" step="1"><small>柔化细节，减少阅读时的视觉干扰</small></label>
        <p class="small-note">想分别调整侧栏、阅读区或输入区？请打开下方“各区域外观”。每个区域都可单独变透明。</p>
      </div>
      <details id="backgroundPosition"><summary>调整图片取景</summary><div class="background-sliders"><label for="backgroundX"><span>水平位置 <output id="backgroundXValue">50%</output></span><input id="backgroundX" type="range" min="0" max="100" step="1"></label><label for="backgroundY"><span>垂直位置 <output id="backgroundYValue">50%</output></span><input id="backgroundY" type="range" min="0" max="100" step="1"></label></div><p class="small-note">图片覆盖窗口，按窗口比例裁切；把主体移到你想保留的位置。</p></details>
      <label class="setting-check background-quiet"><input id="backgroundQuietFocus" type="checkbox"> 专注模式自动淡化背景</label>
      <p id="backgroundSaveStatus" class="small-note" role="status">立即预览，自动保存到本机</p>
    </div><div class="background-preview-column"><div id="backgroundPreview" class="background-preview" aria-label="当前背景与阅读样式预览"><div class="background-preview-paint"></div><div class="background-preview-panel"><span class="background-preview-eyebrow">阅读预览</span><h4>把问题想清楚，再往前走。</h4><p>先说明概念与条件，再解释为什么选择这种方法。清晰来自推理的衔接。</p><blockquote>原文引用与导师讲解保持区分。</blockquote><div id="backgroundPreviewMath"></div><span class="background-preview-tag">文字与公式优先</span></div></div><p id="backgroundPreviewCaption" class="small-note"></p><p class="background-local-note">背景只用于外观，单独保存在本机；不会导入资料库、发送给 AI 或进入学习画像。</p></div></div>`;
  document.getElementById('settings-appearance').prepend(card);
  for(const [mode,paint] of Object.entries(backgroundPaints)){
    const swatch=card.querySelector('.swatch-'+mode);if(swatch)swatch.style.backgroundImage=paint;
  }
  for(const button of card.querySelectorAll('[data-background-choice]'))button.onclick=()=>saveStudioPreferences({ui_background:button.dataset.backgroundChoice});
  for(const [id,key] of backgroundRanges){
    document.getElementById(id).oninput=event=>previewStudioPreferences({[key]:Number(event.target.value)});
    document.getElementById(id).onchange=()=>flushStudioDraft();
  }
  document.getElementById('backgroundQuietFocus').onchange=event=>saveStudioPreferences({ui_background_quiet_focus:event.target.checked});
  document.getElementById('chooseBackgroundImage').onclick=()=>document.getElementById('backgroundImageFile').click();
  document.getElementById('backgroundImageFile').onchange=async event=>{await uploadBackgroundFile(event.target.files[0]);event.target.value='';};
  document.getElementById('removeBackgroundImage').onclick=()=>saveStudioAction(()=>api('/api/appearance/background',{method:'DELETE'}));
  document.getElementById('resetBackground').onclick=()=>saveStudioAction(()=>api('/api/appearance/background/reset',{method:'POST'}));
  const drop=document.getElementById('backgroundImageDrop');
  drop.ondragover=event=>{event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='copy';drop.classList.add('drag');};
  drop.ondragleave=()=>drop.classList.remove('drag');
  drop.ondrop=event=>{event.preventDefault();event.stopPropagation();drop.classList.remove('drag');if(event.dataTransfer.files.length>1)toast('背景一次选择一张图片');uploadBackgroundFile(event.dataTransfer.files[0]);};
  if(window.katex)katex.render(String.raw`\sum_{i=1}^{n} a_i^2\geqslant\frac{(\sum_{i=1}^{n}a_i)^2}{n}`,document.getElementById('backgroundPreviewMath'),{throwOnError:false});
  applyBackgroundPreferences(backgroundDefaults);
}
