(()=>{
const $=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
const D=JSON.parse($('#data').textContent),T=D.t;
const root=document.documentElement,mq=matchMedia('(min-width:1000px)');
/* colour theme: the head script already applied the stored pick; the picker changes it and stores it (a blocked storage only skips the store) */
const skin=$('#skin');
if(skin){
  skin.value=root.getAttribute('data-theme');
  skin.addEventListener('change',()=>{
    root.setAttribute('data-theme',skin.value);
    try{localStorage.setItem('explain-change-theme',skin.value)}catch(e){}
  });
}
const TABS=['req','logic','why','evidence'];
let tab='req',node=null;

/* panel open/close */
function setPanel(open){
  root.dataset.panel=open?'open':'closed';
  $('#toggle').setAttribute('aria-expanded',open);$('#toggle span').textContent=open?T.hide:T.show;
  $('#toggle .ic use').setAttribute('href',open?'#i-panel-right-close':'#i-panel-right');
  $('#grab').setAttribute('aria-expanded',open);
  requestAnimationFrame(drawEdges);setTimeout(drawEdges,460);
}
const isOpen=()=>root.dataset.panel==='open';
$('#toggle').onclick=()=>setPanel(!isOpen());
$('#hide').onclick=()=>setPanel(false);
$('#grab').onclick=()=>setPanel(!isOpen());

/* tabs */
function setTab(t,focus){
  tab=t;
  qa('.tab').forEach(b=>{const on=b.dataset.tab===t;b.setAttribute('aria-selected',on);b.tabIndex=on?0:-1;if(on&&focus)b.focus()});
  qa('.tp').forEach(p=>p.hidden=p.id!=='p-'+t);
  $('#p-body').scrollTop=0;sync();
}
qa('.tab').forEach(b=>{
  b.onclick=()=>{setTab(b.dataset.tab);if(!isOpen())setPanel(true)};
  b.onkeydown=e=>{const i=TABS.indexOf(tab);let n=null;
    if(e.key==='ArrowRight')n=(i+1)%4;else if(e.key==='ArrowLeft')n=(i+3)%4;else if(e.key==='Home')n=0;else if(e.key==='End')n=3;
    if(n!==null){e.preventDefault();setTab(TABS[n],true)}};
});
document.addEventListener('click',e=>{
  const g=e.target.closest('[data-goto]');
  if(g){setTab(g.dataset.goto);if(!isOpen())setPanel(true);
    const t=g.dataset.target&&document.getElementById(g.dataset.target);
    if(t){if(t.hidden)setNode(null);t.scrollIntoView({block:'center'});t.classList.remove('flash');void t.offsetWidth;t.classList.add('flash')}}
  if(e.target.closest('[data-clear]'))setNode(null);
});

/* node filter */
const info={};
qa('.node').forEach(n=>{
  info[n.dataset.id]={name:$('.n-name',n).textContent,state:n.dataset.state,real:n.dataset.real,sum:n.dataset.sum||''};
  $('.hit',n).onclick=()=>{setNode(node===n.dataset.id?null:n.dataset.id);if(node&&!isOpen())setPanel(true)};
});
function setNode(id){
  node=id;
  const rel=new Set(id?EDGES.filter(E=>E.a===id||E.b===id).flatMap(E=>[E.a,E.b]):[]);
  qa('.node').forEach(n=>{const on=n.dataset.id===id;n.classList.toggle('sel',on);n.classList.toggle('rel',!!id&&!on&&rel.has(n.dataset.id));$('.hit',n).setAttribute('aria-pressed',on)});
  $('#stage').classList.toggle('filtering',!!id);
  const c=$('#nodecard');c.classList.toggle('on',!!id);
  const fb=$('#filterbar');fb.hidden=!id;
  if(id){const i=info[id];$('#nc-name').textContent=i.name;$('#fb-name').textContent=i.name;
    const ch=$('#nc-chip');ch.className='chip '+(i.state==='changed'?'acc':'mut');
    ch.textContent=T.state[i.state];
    $('#nc-sum').textContent=i.sum;$('#nc-sum').hidden=!i.sum;
    $('#nc-note').textContent=T.note[i.state];
    const ul=$('#nc-edges');ul.textContent='';
    EDGES.filter(E=>E.label&&(E.a===id||E.b===id)).forEach(E=>{const li=document.createElement('li');li.textContent=info[E.a].name+' → '+info[E.b].name+': '+E.label;ul.append(li)});
    ul.hidden=!ul.children.length;
    c.style.animation='none';c.offsetWidth;c.style.animation='';
    if(!mq.matches)byId[id].scrollIntoView({block:'nearest',behavior:'smooth'})}
  sync();drawEdges();hash();
}
function sync(){
  qa('[data-nodes]').forEach(el=>{el.hidden=!!node&&!el.dataset.nodes.split(' ').includes(node)});
  qa('.grp').forEach(g=>g.hidden=!!node&&!qa('[data-nodes]',g).some(x=>!x.hidden));
  const cnt={};qa('.tp').forEach(p=>{cnt[p.id.slice(2)]=qa('[data-nodes]',p).filter(x=>!x.hidden).length});
  qa('.tp').forEach(p=>{const t=p.id.slice(2),e=$('[data-empty]',p);e.classList.toggle('on',!!node&&!cnt[t]);
    const o=TABS.find(x=>cnt[x]);const hint=$('[data-hint]',e);hint.innerHTML='';
    if(node&&!cnt[t]&&o){hint.append(T.has.replace('{n}',cnt[o])+' ');const b=document.createElement('button');b.className='golink';b.type='button';b.dataset.goto=o;b.textContent=T.tabs[o];hint.append(b,'.')}});
  qa('.concl').forEach(c=>c.hidden=!!node);
  qa('[data-g]').forEach(h=>{const it=qa('.g-'+h.dataset.g),v=it.filter(x=>!x.hidden).length;$('.cnt',h).textContent=v===it.length?it.length:v+'/'+it.length;h.hidden=!v});
  hash();
}
function hash(){const h=[tab!=='req'?'tab='+tab:'',node?'node='+encodeURIComponent(info[node].real):''].filter(Boolean).join('&');history.replaceState(null,'',h?'#'+h:location.pathname+location.search)}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&node&&e.target!==skin)setNode(null)});
$('#fb-clear').onclick=()=>setNode(null);

/* edges: routed by EdgeRouter (route.js) through the gaps between boxes, drawn here */
const EDGES=D.edges;
const NS='http://www.w3.org/2000/svg';
const byId={};qa('.node').forEach(n=>byId[n.dataset.id]=n);
const paths=[],labels=[];let built=false;
/* box of an element in the stage's own pixels (layout position, not affected by transforms mid-animation) */
function box(el,stage){let l=0,t=0,e=el;while(e&&e!==stage){l+=e.offsetLeft;t+=e.offsetTop;e=e.offsetParent}
  return{l,t,r:l+el.offsetWidth,b:t+el.offsetHeight}}
function drawEdges(){
  const stage=$('#stage'),svg=$('#edges'),lsvg=$('#elabels');
  if(!EDGES.length||getComputedStyle(svg).display==='none'||!stage.clientWidth)return;
  if(!built){built=true;EDGES.forEach((E,i)=>{
    const k=E.k;
    const p=document.createElementNS(NS,'path');p.setAttribute('marker-end','url(#ah)');p.setAttribute('class','e '+k+(k==='test'?'':' draw'));p.style.setProperty('--i',i);
    if(k!=='test')p.setAttribute('pathLength','1');svg.appendChild(p);paths.push(p);
    if(E.label&&E.mono){const t=document.createElementNS(NS,'text');t.setAttribute('class','elabel');t.setAttribute('text-anchor','middle');t.setAttribute('dominant-baseline','central');t.textContent=E.label;lsvg.appendChild(t);labels[i]=t}});
    setTimeout(()=>{stage.classList.add('ready');paths.forEach(p=>{p.classList.remove('draw');p.removeAttribute('pathLength');p.style.strokeDasharray=p.classList.contains('test')?'':'none';p.style.strokeDashoffset=0})},2400)}
  const boxes=Object.keys(byId).map(id=>({id,...box(byId[id],stage)}));
  const titles=qa('.zone-label',stage).map(el=>box(el,stage));
  const zones=qa('.zone',stage).map(el=>box(el,stage));
  const jobs=EDGES.map((E,i)=>({a:E.a,b:E.b,lw:labels[i]?labels[i].getComputedTextLength():0,lh:13}));
  const res=EdgeRouter.route(boxes,titles,jobs,stage.clientWidth,stage.clientHeight,zones);
  window.__edges={boxes,obstacles:titles,zones,edges:jobs,W:stage.clientWidth,H:stage.clientHeight,paths:res.paths,labels:res.labels}; /* read by tests and audits */
  EDGES.forEach((E,i)=>{
    const p=paths[i],pts=res.paths[i];
    p.setAttribute('d',EdgeRouter.toPath(pts));p.style.visibility=pts?'':'hidden';
    p.classList.toggle('dim',!!node&&E.a!==node&&E.b!==node);
    const lb=res.labels[i];
    if(labels[i]){const l=lb;labels[i].style.visibility=l?'':'hidden';
      if(l){labels[i].setAttribute('x',(l.l+l.r)/2);labels[i].setAttribute('y',(l.t+l.b)/2);
        labels[i].style.opacity=!node||E.a===node||E.b===node?1:.5}}
  });
}
addEventListener('resize',drawEdges);
new ResizeObserver(()=>drawEdges()).observe($('#stage'));
document.fonts.ready.then(drawEdges);
addEventListener('load',drawEdges);

/* init from hash and screen size */
const h=new URLSearchParams(location.hash.slice(1));
if(!mq.matches&&innerWidth<600)setPanel(false);
if(TABS.includes(h.get('tab')))setTab(h.get('tab'));
const want=h.get('node');
if(want){const k=Object.keys(info).find(x=>info[x].real===want);if(k)setNode(k)}
sync();drawEdges();
})();
