// Builds one self-contained intro.html (fonts, icons and the pearl screenshot inlined) from src/.
// Usage: node build.mjs [outFile]   (default: <tmp>/explain-change-intro/intro.html). Run from anywhere inside the repo checkout.
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const ui=path.join(root,'skills/explain-change/assets/ui');
const rd=(...p)=>fs.readFileSync(path.join(...p),'utf8');
const sprite=rd(ui,'icons.svg')+rd(ui,'session-icons.svg');
const need=['i-message','i-sparkles','i-circle-check','i-upload','i-circle-dashed','i-triangle-alert','i-shield-check','i-list','i-layout','i-branch','i-user','i-ban','i-redirect'];
const syms=need.map(id=>{const m=sprite.match(new RegExp('<symbol id="'+id+'"[\\s\\S]*?</symbol>'));if(!m)throw new Error('missing icon '+id);return m[0]}).join('');
const font=(f,fam,range)=>`@font-face{font-family:"${fam}";font-weight:100 900;src:url(data:font/woff2;base64,${fs.readFileSync(path.join(ui,'fonts',f)).toString('base64')}) format("woff2");unicode-range:${range}}`;
const fonts=font('inter-latin.woff2','Inter','U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD')+font('jetbrains-mono-latin.woff2','JetBrains Mono','U+0000-00FF,U+0131,U+0152-0153,U+2000-206F,U+2122,U+2190-2193,U+2212');
const img='data:image/png;base64,'+fs.readFileSync(path.join(root,'docs/images/themes/pearl-1440x900.png')).toString('base64');
export function build(out=path.join(os.tmpdir(),'explain-change-intro','intro.html')){
  const h=rd(here,'src/intro.src.html').replace('/*FONTS*/',()=>fonts).replace('/*LIB_CSS*/',()=>rd(here,'src/lib.css')).replace('/*LIB_JS*/',()=>rd(here,'src/lib.js'))
    .replace('<!--ICONS-->',()=>`<svg width="0" height="0" style="position:absolute" aria-hidden="true">${syms}</svg>`).replaceAll('__PEARL_IMG__',()=>img);
  fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,h);return out;
}
if(process.argv[1]===fileURLToPath(import.meta.url)){const o=build(process.argv[2]);console.log('built',o,(fs.statSync(o).size/1024|0)+' KB')}
