// Deterministic recorder: steps the timeline with seek(t), screenshots every frame over raw CDP (Node's built-in WebSocket, no npm packages),
// pipes the frames to ffmpeg for the MP4, and packs the 800 px GIF with ffmpeg (one palette for the clip, lossless frame diff). gifski's lossy diff keeps faint pixels
// of the previous frame, which showed as ghosting of the old scene in every cross-fade, so it is not used.
// Usage: systemd-run --user --scope -p MemoryMax=3G -- node record.mjs [outDir]      (default outDir: <tmp>/explain-change-intro/out)
// Env: SHOTS=1000,5000 writes shot-<ms>.png only; NO_GIF=1 / ONLY_GIF=1 skip a part; KEEP_FRAMES=1 keeps the GIF frames, GIF_FRAMES_DIR=<dir> packs a kept frame folder without re-rendering.
import {spawn,spawnSync} from 'node:child_process';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {build} from './build.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
const out=process.argv[2]||path.join(os.tmpdir(),'explain-change-intro','out');
const FPS=30,GIF_FPS=12,POSTER_MS=12000,GIF_W=800,GIF_MAX=3*1024*1024;
/* stretches where every pixel moves (the zoom on the screenshot): the GIF holds each frame longer there to stay small */
const SLOW=[[21950,25650]];
fs.mkdirSync(out,{recursive:true});
const html=build(path.join(os.tmpdir(),'explain-change-intro','intro.html'));

async function record(gif=false){
  const prof=fs.mkdtempSync(path.join(os.tmpdir(),'ec-intro-prof-'));
  const chrome=spawn('chromium',['--headless=new','--no-sandbox','--disable-gpu','--hide-scrollbars','--force-color-profile=srgb','--remote-debugging-port=0',`--user-data-dir=${prof}`,'--window-size=1280,720','about:blank'],{stdio:'ignore'});
  try{
    const portFile=path.join(prof,'DevToolsActivePort');
    for(let i=0;i<100&&!fs.existsSync(portFile);i++)await new Promise(r=>setTimeout(r,100));
    const port=fs.readFileSync(portFile,'utf8').split('\n')[0];
    const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
    let id=0;const wait=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&wait.has(m.id)){wait.get(m.id)(m);wait.delete(m.id)}};
    const send=(method,params={})=>new Promise((res,rej)=>{const i=++id;wait.set(i,m=>m.error?rej(new Error(method+': '+m.error.message)):res(m.result));ws.send(JSON.stringify({id:i,method,params}))});
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:1280,height:720,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:'file://'+html+(gif?'?record&gif':'?record')});
    for(let i=0;i<100;i++){const r=await send('Runtime.evaluate',{expression:'window.DURATION&&window.__ready?1:0'});if(r.result.value===1)break;await new Promise(r=>setTimeout(r,100))}
    await send('Runtime.evaluate',{expression:'window.__ready',awaitPromise:true});
    const dur=(await send('Runtime.evaluate',{expression:'window.DURATION'})).result.value;
    const shot=async(opts={})=>Buffer.from((await send('Page.captureScreenshot',{format:'png',...opts})).data,'base64');
    const at=async t=>send('Runtime.evaluate',{expression:`seek(${t})`});
    if(process.env.SHOTS){for(const t of process.env.SHOTS.split(',')){await at(t);fs.writeFileSync(path.join(out,`shot-${t}.png`),await shot())}return null}
    if(gif){  // flat variant (no dot grid, soft shadows or blur), rendered natively at GIF_W so the text stays crisp
      const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ec-intro-gif-'));const frames=Math.round(dur/1000*GIF_FPS);
      for(let f=0;f<frames;f++){await at((f*1000/GIF_FPS).toFixed(3));fs.writeFileSync(path.join(dir,String(f).padStart(4,'0')+'.png'),await shot({clip:{x:0,y:0,width:1280,height:720,scale:GIF_W/1280}}))}
      ws.close();return dir}
    const mp4=path.join(out,'intro.mp4');
    const ff=spawn('ffmpeg',['-y','-loglevel','error','-f','image2pipe','-framerate',String(FPS),'-i','-','-c:v','libx264','-preset','slow','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',mp4],{stdio:['pipe','inherit','inherit']});
    const done=new Promise(r=>ff.on('close',r));const frames=Math.round(dur/1000*FPS);
    for(let f=0;f<frames;f++){await at((f*1000/FPS).toFixed(3));if(!ff.stdin.write(await shot()))await new Promise(r=>ff.stdin.once('drain',r))}
    ff.stdin.end();await done;ws.close();
    console.log(`intro: ${frames} frames, ${(dur/1000).toFixed(1)} s, ${(fs.statSync(mp4).size/1024)|0} KB`);return mp4;
  }finally{chrome.kill('SIGKILL');fs.rmSync(prof,{recursive:true,force:true})}
}
function poster(mp4){const r=spawnSync('ffmpeg',['-y','-loglevel','error','-ss',String(POSTER_MS/1000),'-i',mp4,'-frames:v','1',path.join(out,'intro-poster.png')]);if(r.status)throw new Error(String(r.stderr))}
function makeGif(dir){  // ffmpeg, one 256-colour palette for the whole clip, lossless frame diff: unlike gifski's lossy diff it leaves no ghost of the old scene in a cross-fade
  const gif=path.join(out,'intro.gif');const frames=fs.readdirSync(dir).sort().map(f=>path.join(dir,f));
  const seq=fs.mkdtempSync(path.join(os.tmpdir(),'ec-intro-seq-'));
  for(const fps of (process.env.GIF_TRY?JSON.parse(process.env.GIF_TRY):[12,10,8,6])){
    fs.readdirSync(seq).forEach(f=>fs.rmSync(path.join(seq,f)));
    const n=Math.floor(frames.length*fps/GIF_FPS);
    for(let k=0;k<n;k++){let f=Math.floor(k*GIF_FPS/fps);const t=f*1000/GIF_FPS;if(SLOW.some(([a,b])=>t>=a&&t<b))f=Math.floor(f/3)*3;fs.symlinkSync(frames[f],path.join(seq,String(k).padStart(4,'0')+'.png'))}
    const r=spawnSync('ffmpeg',['-y','-loglevel','error','-framerate',String(fps),'-i',path.join(seq,'%04d.png'),'-vf','split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle','-loop','0',gif]);
    if(r.status)throw new Error(String(r.stderr));
    const size=fs.statSync(gif).size;console.log(`  gif ${fps} fps: ${(size/1024)|0} KB`);if(size<=GIF_MAX)break;
  }
  fs.rmSync(seq,{recursive:true,force:true});
  if(!process.env.KEEP_FRAMES)fs.rmSync(dir,{recursive:true,force:true});else console.log('frames kept in',dir);
}
const busy=spawnSync('ps',['-eo','pid=,comm=,args=']).stdout.toString().split('\n').filter(l=>/^\s*\d+\s+\S*chrom\S*\s/.test(l)&&l.includes('--headless'));
if(busy.length){console.error('another headless browser is running, stop:\n'+busy.join('\n'));process.exit(2)}
if(!process.env.ONLY_GIF){const v=await record();if(v)poster(v)}
if(!process.env.NO_GIF&&!process.env.SHOTS)makeGif(process.env.GIF_FRAMES_DIR||await record(true));
