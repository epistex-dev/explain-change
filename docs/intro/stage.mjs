// node docs/intro/stage.mjs <out-dir> <path to gsap.min.js>
// Writes a ready-to-render HyperFrames project: index.html with the icon sprite inlined, data.js, assets and a local GSAP.
import fs from 'node:fs'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const [outArg, gsap] = process.argv.slice(2);
if (!outArg || !gsap) throw new Error('usage: stage.mjs <out-dir> <gsap.min.js>');
const out = path.resolve(outArg);
fs.mkdirSync(out, {recursive: true});
fs.cpSync(path.join(here, 'assets'), path.join(out, 'assets'), {recursive: true});
fs.copyFileSync(gsap, path.join(out, 'assets/gsap.min.js'));
fs.copyFileSync(path.join(here, 'data.js'), path.join(out, 'data.js'));
const sprite = fs.readFileSync(path.join(here, 'assets/icons.svg'), 'utf8');
fs.writeFileSync(path.join(out, 'index.html'), fs.readFileSync(path.join(here, 'index.html'), 'utf8').replace('<!--SPRITE-->', sprite));
console.log('staged', out);
