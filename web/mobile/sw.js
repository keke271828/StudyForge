/* Cache only the public application shell. Learning content and authenticated
   responses must never enter a service-worker cache. */
const SHELL='studyforge-mobile-shell-v90';
const ASSETS=['/','/app.js','/homework.js','/lesson-feedback.js','/style.css','/source_scope.js','/source_scope.css','/user_guide.js','/user_guide.css','/help/guide.html','/help/guide.js','/help/guide.css','/icon.svg','/manifest.webmanifest','/vendor/marked.js','/vendor/purify.js','/vendor/katex.js','/vendor/katex.css'];
ASSETS.push('/operation_errors.js','/operation_errors.css');
ASSETS.push('/library.js','/library_models.js','/task_retry.js','/library.css','/library_policy.js','/library_mentions.js','/library_mentions.css','/lesson_render.js');
ASSETS.push('/document_exports.js','/document_exports.css');
ASSETS.push('/message_focus.js','/message_focus.css','/source_selection.js');
ASSETS.push('/message_history.js');
ASSETS.push('/learning-check.js');
ASSETS.push('/source_evidence.js','/source_evidence.css');
ASSETS.push('/teaching_review.js','/teaching_review.css');
ASSETS.push('/lesson_passage.js','/lesson_passage.css');
ASSETS.push('/refresh_state.js');
ASSETS.push('/task_timing.js','/task_timing.css');
ASSETS.push('/homework_reader.js','/homework_reader.css');
ASSETS.push('/repair_picker.js','/repair_picker.css');
ASSETS.push('/practice_hints.js','/practice_hints.css');
self.addEventListener('install',event=>event.waitUntil(caches.open(SHELL).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('studyforge-mobile-shell-')&&key!==SHELL).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;
  event.respondWith(fetch(event.request).then(response=>{
    if(response.ok){const copy=response.clone();caches.open(SHELL).then(cache=>cache.put(event.request,copy));}
    return response;
  }).catch(()=>caches.match(event.request)));
});
