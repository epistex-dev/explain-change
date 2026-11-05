(()=>{
const $=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
const D=JSON.parse($('#data').textContent),T=D.t,root=document.documentElement;
root.classList.add('js');
/* ---- colour theme: the head script already applied the stored pick; the picker changes it and stores it (a blocked storage only skips the store) */
const skin=$('#skin');
if(skin){
  skin.value=root.getAttribute('data-theme');
  skin.addEventListener('change',()=>{
    root.setAttribute('data-theme',skin.value);
    try{localStorage.setItem('explain-change-theme',skin.value)}catch(e){}
  });
}
const wide=matchMedia('(min-width:1001px)');
const panel=$('#panel'),home=panel.parentNode;
const laneOf=id=>qa('.lane').find(l=>l.dataset.id===id);
const px=n=>parseFloat(getComputedStyle(root).getPropertyValue(n));
let cur=null,opener=null,span=null;  // span: [lane id, from, to] of the cluster bubble that opened the panel

/* ---- lane layout: markers keep --mk size and --mk-gap spacing; a lane with more events than fit shows count bubbles */
function layoutLane(lane){
  const th=D.themes.find(t=>t.id===lane.dataset.id),track=$('.track',lane);
  const mk=px('--mk'),gap=px('--mk-gap'),W=track.clientWidth;
  if(!th||!W)return;
  qa('.cl',track).forEach(b=>b.remove());
  const btns=qa('.mk[data-i]',track);
  btns.forEach(b=>{b.hidden=false});
  const {cap,items}=SessionFit.fit(th.ev.map(e=>e.o),W,mk,gap,D.lo,D.hi),last=items.length-1;
  items.forEach(it=>{
    let el;
    if(it.i.length===1){el=btns[it.i[0]]}
    else{
      el=document.createElement('button');
      el.type='button';el.className='mk cl';el.textContent=it.i.length;
      el.dataset.from=it.i[0];el.dataset.to=it.i[it.i.length-1];
      el.setAttribute('aria-label',T.cl.replace('%d',it.i.length));el.title=el.getAttribute('aria-label');
      el.setAttribute('aria-pressed','false');el.setAttribute('aria-controls','panel');
      btns[it.i[0]].before(el);
      it.i.forEach(k=>{btns[k].hidden=true});
    }
    el.style.left=it.x+'px';
  });
  const ln=$('.ln',track);
  ln.style.left=(items[0].x+mk/2)+'px';ln.style.width=(items[last].x-items[0].x)+'px';
  lane.dataset.cap=cap;lane.dataset.items=items.length;
}
const layoutAll=()=>{
  const focused=!!opener&&document.activeElement===opener;
  qa('.lane').forEach(layoutLane);
  if(span&&opener&&(!opener.isConnected||opener.hidden)){
    opener=bubbleFor(span[0],span[1],span[2]);
    if(focused){const l=laneOf(span[0]),f=opener||(l&&$('.lh',l));if(f)f.focus({preventScroll:true})}
  }else if(opener&&!opener.isConnected)opener=null;
  mark();
};
/* the count bubble (or the marker) now showing events from..to of a lane: a relayout rebuilds the bubbles, so the one that opened the panel is found again */
function bubbleFor(id,from,to){
  const l=laneOf(id);
  if(!l)return null;
  return qa('.cl',l).find(c=>+c.dataset.from<=from&&to<=+c.dataset.to)||(from===to?qa('.mk[data-i]',l).find(b=>+b.dataset.i===from&&!b.hidden):null)||null;
}

/* ---- selection and the panel */
function place(){
  const l=cur&&laneOf(cur);
  if(wide.matches||!l){if(panel.parentNode!==home)home.appendChild(panel)}
  else if(panel.previousElementSibling!==l)l.after(panel);
}
function mark(){
  qa('.mk').forEach(b=>b.setAttribute('aria-pressed','false'));
  if(opener&&opener.classList.contains('mk')&&opener.isConnected&&!opener.hidden)opener.setAttribute('aria-pressed','true');
}
function show(id,from,to,by,focus){
  cur=id;opener=by||null;span=by&&by.classList.contains('mk')?[id,from,to]:null;
  qa('.lane').forEach(l=>l.classList.toggle('sel',l.dataset.id===id));
  qa('.tp').forEach(p=>p.classList.toggle('on',p.dataset.id===id));
  $('.empty-panel').classList.remove('on');
  panel.hidden=false;place();mark();
  const tp=$('.tp.on'),lis=qa('.ev li',tp),note=$('.cl-note',tp);
  lis.forEach(li=>li.classList.remove('hit'));
  note.hidden=true;
  if(from!=null){
    for(let k=from;k<=to;k++)lis[k]&&lis[k].classList.add('hit');
    if(to>from){note.textContent=T.cl_note.replace('%d',from+1).replace('%d',to+1).replace('%d',lis.length);note.hidden=false}
    lis[from]&&lis[from].scrollIntoView({block:'nearest'});
  }
  if(focus){panel.focus({preventScroll:true});if(!wide.matches)panel.scrollIntoView({block:'nearest'})}
  history.replaceState(null,'','#theme-'+id);
}
function close(){
  if(!cur)return;
  const by=opener,l=laneOf(cur),lh=l&&$('.lh',l);
  cur=null;opener=null;span=null;
  qa('.lane').forEach(x=>x.classList.remove('sel'));
  qa('.tp').forEach(p=>p.classList.remove('on'));
  qa('.mk').forEach(b=>b.setAttribute('aria-pressed','false'));
  $('.empty-panel').classList.add('on');place();
  history.replaceState(null,'',location.pathname+location.search);
  const back=by&&by.isConnected&&!by.hidden?by:(by&&by.dataset.i!=null&&l&&qa('.cl',l).find(c=>+c.dataset.from<=+by.dataset.i&&+by.dataset.i<=+c.dataset.to))||lh;
  if(back)back.focus();
}
document.addEventListener('click',e=>{
  const mk=e.target.closest('.mk'),lh=e.target.closest('.lh'),th=e.target.closest('[data-lane]'),g=e.target.closest('[data-goto]'),x=e.target.closest('[data-close]');
  if(mk){
    const id=mk.closest('.lane').dataset.id;
    if(mk.classList.contains('cl'))show(id,+mk.dataset.from,+mk.dataset.to,mk,true);
    else show(id,+mk.dataset.i,+mk.dataset.i,mk,true);
  }else if(lh){show(lh.closest('.lane').dataset.id,null,null,lh,true)}
  else if(th){
    e.preventDefault();
    const l=laneOf(th.dataset.lane),h=l&&$('.lh',l);
    if(h){show(th.dataset.lane,null,null,h,false);l.scrollIntoView({block:'center'});h.focus({preventScroll:true})}
  }else if(g){
    e.preventDefault();
    const t=document.getElementById(g.dataset.goto);
    if(t){if(cur&&t.closest('.empty-panel'))close();const dd=t.closest('details');if(dd)dd.open=true;t.scrollIntoView({block:'center'});t.classList.remove('flash');void t.offsetWidth;t.classList.add('flash')}
  }else if(x)close();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&cur&&!e.defaultPrevented&&!(e.target.closest&&e.target.closest('select'))){e.preventDefault();close()}});
wide.addEventListener('change',()=>{place();layoutAll()});

/* ---- start */
if(window.ResizeObserver)new ResizeObserver(layoutAll).observe($('.lanes'));
layoutAll();
const m=/^#theme-(.+)$/.exec(location.hash),start=m&&D.themes.find(t=>t.id===decodeURIComponent(m[1]));
if(start){show(start.id,null,null,null,false);laneOf(start.id).scrollIntoView({block:'center'})}
else{$('.empty-panel').classList.add('on');place()}
history.replaceState(null,'',start?location.hash:location.pathname+location.search);
})();
