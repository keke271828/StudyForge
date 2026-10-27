// Static data, JavaScript and math checks for the offline review artifact.
// Does not control Edge, call a model, or claim visual/browser verification.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const target = path.resolve(process.argv[2]);
const html = fs.readFileSync(target, 'utf8');
const block = html.match(/<script type="application\/json" id="samples">([\s\S]*?)<\/script>/);
if (!block) throw new Error('Missing sample data');
const data = JSON.parse(block[1]);
let scripts = 0;
for (const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
  if (/application\/json/.test(match[1])) continue;
  new vm.Script(match[2], {filename:'offline-comparison.js'});
  scripts++;
}
if (/<script[^>]+src=|<link[^>]+href=|url\(fonts\//i.test(html)) throw new Error('External dependency remained');
const katex = require(path.join(root, 'web', 'vendor', 'katex.js'));
const context = vm.createContext({});
new vm.Script(fs.readFileSync(path.join(root, 'web', 'lesson_render.js'), 'utf8')).runInContext(context);
let samples = 0, formulas = 0, plainCopies = 0;
const mathErrors = [];
for (const group of data.groups) {
  for (const row of group.rows) {
    samples++;
    const digest = crypto.createHash('sha256').update(row.text).digest('hex');
    if (digest !== row.sha256) throw new Error('Output hash changed');
    if (row.text !== fs.readFileSync(row.output, 'utf8')) throw new Error('Output was rewritten');
    // Broken formula copies are displayed as original plaintext, not rendered
    // math. Validate their bytes without treating copy damage as model quality.
    if (row.render_plain) { plainCopies++; continue; }
    context.textToCheck = row.text;
    const parsed = vm.runInContext('protectLessonMath(textToCheck)', context);
    for (const formula of parsed.formulas) {
      formulas++;
      try { katex.renderToString(formula.latex, {displayMode:formula.display, throwOnError:true, trust:false,
        strict:'ignore', maxExpand:1000, maxSize:30}); }
      catch (error) { mathErrors.push({case:row.case,arm:row.arm,latex:formula.latex,error:error.message}); }
    }
  }
}
if (samples !== data.count) throw new Error('Sample count does not match');
const report = {ok:!mathErrors.length,samples,failed_requests:data.failures.length,groups:data.groups.length,
  scripts_parsed:scripts,formulas_checked:formulas,math_errors:mathErrors,
  verbatim_outputs:true,plaintext_copies:plainCopies,external_dependencies:false,visual_preview:false,
  scope:'Static syntax, original text hashes and KaTeX parsing; no semantic correctness inferred.'};
fs.writeFileSync(path.join(path.dirname(target), '页面静态核验.json'), JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
if (mathErrors.length) process.exitCode=1;
