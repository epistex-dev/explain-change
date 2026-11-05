/* explain-flow page: one step at a time in the panel. Without this script every step stays in the page, in order. */
(function(){
var D=JSON.parse(document.getElementById('data').textContent),N=D.mod.length,stage=document.getElementById('stage'),svg=document.getElementById('edges'),cur=1;
var sk=document.getElementById('skin'),T=D.t;
sk.value=document.documentElement.getAttribute('data-theme');
sk.addEventListener('change',function(){var v=sk.value;document.documentElement.setAttribute('data-theme',v);try{localStorage.setItem(D.key,v)}catch(e){}document.dispatchEvent(new Event('themechange'))});
function q(s,r){return[].slice.call((r||document).querySelectorAll(s))}
function box(m){var n=stage.querySelector('[data-mod="'+m+'"]');if(!n)return null;var r=n.getBoundingClientRect(),s=stage.getBoundingClientRect();return{x:r.left-s.left,y:r.top-s.top,w:r.width,h:r.height}}
function clip(a,b){var cx=a.x+a.w/2,cy=a.y+a.h/2,dx=b.x+b.w/2-cx,dy=b.y+b.h/2-cy,k=Math.min(dx?(a.w/2+4)/Math.abs(dx):1e9,dy?(a.h/2+4)/Math.abs(dy):1e9);return[cx+dx*k,cy+dy*k]}
function draw(){
  q('path.e',svg).forEach(function(p){p.remove()});
  if(getComputedStyle(svg).display==='none')return;
  D.edges.forEach(function(e){var a=box(e[0]),b=box(e[1]);if(!a||!b)return;var p=clip(a,b),r=clip(b,a),el=document.createElementNS('http://www.w3.org/2000/svg','path');
    el.setAttribute('d','M'+p[0]+' '+p[1]+'L'+r[0]+' '+r[1]);el.setAttribute('marker-end','url(#'+(e[3]?'fl-ahb':'fl-ah')+')');
    el.setAttribute('class','e'+(e[3]?' bad':'')+(e[2].indexOf(cur)>-1?' on':''));svg.appendChild(el)})}
function show(n,fromHash){cur=n=Math.max(1,Math.min(N,n));
  q('.a-pb article').forEach(function(a){a.hidden=a.id!=='step-'+n});
  q('[data-step]').forEach(function(b){if(b.tagName!=='BUTTON')return;if(+b.dataset.step===n)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current')});
  q('.a-route li').forEach(function(li,i){li.firstChild.classList.toggle('done',i+1<n)});
  q('.node',stage).forEach(function(nd){nd.classList.toggle('lit',nd.dataset.mod===D.mod[n-1])});
  document.getElementById('pcount').textContent=T.of.replace('%d',n).replace('%d',N);
  document.getElementById('prev').setAttribute('aria-disabled',n<2);document.getElementById('next').setAttribute('aria-disabled',n>=N);q('.a-pb')[0].scrollTop=0;
  if(!fromHash&&history.replaceState){try{history.replaceState(null,'','#step-'+n)}catch(e){}}
  draw()}
function fromHash(){var m=/^#step-(\d+)$/.exec(location.hash);return m?+m[1]:1}
document.addEventListener('click',function(ev){
  var b=ev.target.closest('[data-step]');
  if(!b){var nd=ev.target.closest('.node[data-has]');if(nd&&stage.contains(nd)){var first=nd.querySelector('[data-step]'),have=D.mod[cur-1]===nd.dataset.mod;if(first&&!have)show(+first.dataset.step)}return}
  ev.preventDefault();show(+b.dataset.step);
  if(matchMedia('(max-width:1100px)').matches&&b.closest('.f-pills,.a-route'))document.querySelector('.a-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'})});
document.getElementById('prev').onclick=function(){show(cur-1)};document.getElementById('next').onclick=function(){show(cur+1)};
document.addEventListener('keydown',function(ev){
  if(ev.altKey||ev.ctrlKey||ev.metaKey||ev.shiftKey||/^(SELECT|INPUT|TEXTAREA)$/.test(ev.target.tagName))return;
  if(ev.key==='ArrowRight'){ev.preventDefault();show(cur+1)}else if(ev.key==='ArrowLeft'){ev.preventDefault();show(cur-1)}});
addEventListener('hashchange',function(){show(fromHash(),true)});
addEventListener('resize',draw);document.addEventListener('themechange',draw);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(draw);
show(fromHash(),true);
addEventListener('load',function(){setTimeout(function(){if(/^#step-/.test(location.hash)&&!matchMedia('(max-width:1100px)').matches)scrollTo(0,0)},60)});
})();
