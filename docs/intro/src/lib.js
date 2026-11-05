/* Deterministic timeline. Every animation is a paused Web Animation; window.seek(ms) sets them all, so a re-record is identical.
   Without ?record the page loops in real time for a live preview. */
const EASE_OUT='cubic-bezier(.16,1,.3,1)',EASE_IO='cubic-bezier(.65,0,.35,1)',EASE_SOFT='cubic-bezier(.33,1,.68,1)';
const anims=[],ticks=[];
/* Section clock: every at/dur given to A(), T() and scene() is local to the section and is mapped to the global timeline as TO + t*TS. */
let TO=0,TS=1;const sect=(offset,scale=1)=>{TO=offset;TS=scale};
const q=(s,r=document)=>r.querySelector(s),qsa=(s,r=document)=>[...r.querySelectorAll(s)];
const el=(tag,cls,html,st)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;if(st)for(const k in st)k.startsWith('--')?e.style.setProperty(k,st[k]):(e.style[k]=st[k]);return e};
const svgEl=(tag,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e};
const icon=(id,cls='ic')=>`<svg class="${cls}" viewBox="0 0 24 24"><use href="#${id}"/></svg>`;
/* A(target, keyframes, {at, dur, ease}): a paused animation positioned on the global timeline (ms) */
function A(t,kf,o){const e=typeof t==='string'?q(t):t;const a=e.animate(kf,{delay:TO+o.at*TS,duration:Math.max(1,o.dur*TS),easing:o.ease||EASE_OUT,fill:o.fill||'both'});a.pause();anims.push(a);return a}
const cl=x=>Math.max(0,Math.min(1,x)),eo=p=>1-Math.pow(1-p,3),lin=p=>p;
/* T(at, dur, fn(p)): value-driven (counters, text) */
function T(at,dur,fn,ease=eo){ticks.push({at:TO+at*TS,dur:dur*TS,fn,ease})}
/* fade a scene in/out with a soft rise, no hard cut. inAt < 0 means the scene is already shown at t=0 */
function scene(s,inAt,outAt,d=700){A(s,[{opacity:0,transform:'translateY(14px) scale(.985)'},{opacity:1,transform:'none'}],{at:inAt,dur:d});
  if(outAt!=null)A(s,[{opacity:1,transform:'none'},{opacity:0,transform:'translateY(-10px) scale(1.01)'}],{at:outAt,dur:d,ease:EASE_IO,fill:'forwards'});
  if(outAt!=null)A(s,[{visibility:'visible'},{visibility:'hidden'}],{at:outAt+d,dur:1,fill:'forwards'})}
function popIn(e,at,dur=420){A(e,[{opacity:0,transform:'scale(.4)'},{opacity:1,transform:'scale(1.12)',offset:.6},{opacity:1,transform:'scale(1)'}],{at,dur,ease:EASE_SOFT})}
function draw(path,at,dur,ease=EASE_IO){const L=path.getTotalLength();path.style.strokeDasharray=L;A(path,[{strokeDashoffset:L},{strokeDashoffset:0}],{at,dur,ease})}
function seek(t){anims.forEach(a=>a.currentTime=t);ticks.forEach(k=>k.fn(k.ease(cl((t-k.at)/k.dur))))}
window.seek=seek;
function start(duration){window.DURATION=duration;seek(0);window.__ready=document.fonts.ready.then(()=>true);
  const at=new URLSearchParams(location.search).get('at');  // ?at=<ms> freezes one frame (for the design checker)
  if(at!==null){seek(Number(at));return}
  if(!location.search.includes('record')){const t0=performance.now();(function f(n){seek((n-t0)%(duration+700));requestAnimationFrame(f)})(t0)}}

if(location.search.includes('gif'))document.documentElement.classList.add('gif');
