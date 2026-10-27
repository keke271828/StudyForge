// Bundle rendering assets so Markdown and equations work without a CDN.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'web', 'vendor');
fs.mkdirSync(output, { recursive: true });
for (const [source, target] of [
  ['marked/lib/marked.umd.js', 'marked.js'],
  ['dompurify/dist/purify.min.js', 'purify.js'],
  ['katex/dist/katex.min.js', 'katex.js'],
  ['katex/dist/katex.min.css', 'katex.css'],
  ['marked/LICENSE', 'marked-LICENSE'],
  ['dompurify/LICENSE', 'dompurify-LICENSE'],
  ['katex/LICENSE', 'katex-LICENSE'],
]) fs.copyFileSync(path.join(root, 'node_modules', source), path.join(output, target));
fs.cpSync(path.join(root, 'node_modules/katex/dist/fonts'), path.join(output, 'fonts'), { recursive: true });
