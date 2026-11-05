(()=>{
const $=(s,r=document)=>r.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
const D=JSON.parse($('#data').textContent),T=D.t,root=document.documentElement;
root.classList.add('js');
const wide=matchMedia('(min-width:1001px)');
const panel=$('#panel'),home=panel.parentNode;
const laneOf=id=>qa('.lane').find(l=>l.dataset.id===id);
const px=n=>parseFloat(getComputedStyle(root).getPropertyValue(n));
let cur=null,opener=null;

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
const layoutAll=()=>{qa('.lane').forEach(layoutLane);if(opener&&!opener.isConnected)opener=null;mark()};

/* ---- selection and the panel */
function place(){
  const l=cur&&laneOf(cur);
  if(wide.matches){if(panel.parentNode!==home)home.appendChild(panel)}
  else if(l&&panel.previousElementSibling!==l)l.after(panel);
}
function mark(){
  qa('.mk').forEach(b=>b.setAttribute('aria-pressed','false'));
  if(opener&&opener.classList.contains('mk')&&opener.isConnected&&!opener.hidden)opener.setAttribute('aria-pressed','true');
}
function show(id,from,to,by,focus){
  cur=id;opener=by||null;
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
  cur=null;opener=null;
  qa('.lane').forEach(x=>x.classList.remove('sel'));
  qa('.tp').forEach(p=>p.classList.remove('on'));
  qa('.mk').forEach(b=>b.setAttribute('aria-pressed','false'));
  if(wide.matches){$('.empty-panel').classList.add('on')}else{panel.hidden=true}
  history.replaceState(null,'',location.pathname+location.search);
  const back=by&&by.isConnected&&!by.hidden?by:(by&&by.dataset.i!=null&&l&&qa('.cl',l).find(c=>+c.dataset.from<=+by.dataset.i&&+by.dataset.i<=+c.dataset.to))||lh;
  if(back)back.focus();
}
document.addEventListener('click',e=>{
  const mk=e.target.closest('.mk'),lh=e.target.closest('.lh'),th=e.target.closest('[data-theme]'),g=e.target.closest('[data-goto]'),x=e.target.closest('[data-close]');
  if(mk){
    const id=mk.closest('.lane').dataset.id;
    if(mk.classList.contains('cl'))show(id,+mk.dataset.from,+mk.dataset.to,mk,true);
    else show(id,+mk.dataset.i,+mk.dataset.i,mk,true);
  }else if(lh){show(lh.closest('.lane').dataset.id,null,null,lh,true)}
  else if(th){
    e.preventDefault();
    const l=laneOf(th.dataset.theme),h=l&&$('.lh',l);
    if(h){show(th.dataset.theme,null,null,h,false);l.scrollIntoView({block:'center'});h.focus({preventScroll:true})}
  }else if(g){
    e.preventDefault();
    const t=document.getElementById(g.dataset.goto);
    if(t){t.scrollIntoView({block:'center'});t.classList.remove('flash');void t.offsetWidth;t.classList.add('flash')}
  }else if(x)close();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&cur){e.preventDefault();close()}});
wide.addEventListener('change',()=>{
  if(wide.matches){panel.hidden=false;if(!cur)$('.empty-panel').classList.add('on')}
  else if(!cur)panel.hidden=true;
  place();layoutAll();
});

/* ---- start */
if(window.ResizeObserver)new ResizeObserver(layoutAll).observe($('.lanes'));
layoutAll();
const m=/^#theme-(.+)$/.exec(location.hash),start=m&&D.themes.find(t=>t.id===decodeURIComponent(m[1]));
if(start){show(start.id,null,null,null,false);laneOf(start.id).scrollIntoView({block:'center'})}
else if(wide.matches)show(D.themes[0].id,null,null,null,false);
else{panel.hidden=true}
history.replaceState(null,'',start?location.hash:location.pathname+location.search);
})();
