/* explain-flow page: one step at a time in the panel. Without this script every step stays in the page, in order. */
(function(){
var D=JSON.parse(document.getElementById('data').textContent),N=D.mod.length,stage=document.getElementById('stage'),svg=document.getElementById('edges'),cur=1;
var sk=document.getElementById('skin'),T=D.t;
sk.value=document.documentElement.getAttribute('data-theme');
sk.addEventListener('change',function(){var v=sk.value;document.documentElement.setAttribute('data-theme',v);try{localStorage.setItem(D.key,v)}catch(e){}document.dispatchEvent(new Event('themechange'))});
function q(s,r){return[].slice.call((r||document).querySelectorAll(s))}
function box(m){var n=stage.querySelector('[data-mod="'+m+'"]');if(!n)return null;var r=n.getBoundingClientRect(),s=stage.getBoundingClientRect();return{x:r.left-s.left,y:r.top-s.top,w:r.width,h:r.height}}
/* The lines: a path on a grid of G px that keeps PAD px clear of every card and label, bends as little as it can, and avoids the cells earlier lines took. */
var G=10,PAD=10,BEND=5,SIDES=[[1,0],[0,1],[-1,0],[0,-1]];
function ports(r,blocked,cols,rows){
  /* one cell wide ring just outside the clear zone of the card: a line leaves or enters there, straight to the card edge */
  var res=[];
  for(var d=0;d<4;d++){
    var horiz=d%2===0,lo=horiz?r.y+8:r.x+8,hi=horiz?r.y+r.h-8:r.x+r.w-8,mid=horiz?r.y+r.h/2:r.x+r.w/2,edge=d===0?r.x+r.w:d===1?r.y+r.h:d===2?r.x:r.y,
        a=d<2?Math.floor((edge+PAD-G/2)/G)+1:Math.ceil((edge-PAD-G/2)/G)-1;
    for(var u=Math.ceil((lo-G/2)/G);u*G+G/2<=hi;u++){
      var c=horiz?a:u,k=horiz?u:a;if(c<0||k<0||c>=cols||k>=rows||blocked[k*cols+c])continue;
      var cx=c*G+G/2,cy=k*G+G/2;
      res.push({cell:k*cols+c,d:d,ax:horiz?edge:cx,ay:horiz?cy:edge,pen:Math.abs((horiz?cy:cx)-mid)/G*.3})}}
  return res}
function route(A,B,o){
  var cols=o.cols,rows=o.rows,blocked=o.blocked,occ=o.occ,N=cols*rows*4,dist=new Float32Array(N).fill(1e9),par=new Int32Array(N).fill(-1),heap=[],goal={};
  function push(f,st){heap.push([f,st]);var i=heap.length-1;while(i>0){var p=(i-1)>>1;if(heap[p][0]<=heap[i][0])break;var t=heap[p];heap[p]=heap[i];heap[i]=t;i=p}}
  function pop(){var top=heap[0],last=heap.pop();if(heap.length){heap[0]=last;var i=0;for(;;){var l=2*i+1,r=l+1,m=i;if(l<heap.length&&heap[l][0]<heap[m][0])m=l;if(r<heap.length&&heap[r][0]<heap[m][0])m=r;if(m===i)break;var t=heap[m];heap[m]=heap[i];heap[i]=t;i=m}}return top}
  var tx=B.x+B.w/2,ty=B.y+B.h/2;
  function h(c,k){var cx=c*G+G/2,cy=k*G+G/2;return(Math.max(Math.abs(cx-tx)-B.w/2,0)+Math.max(Math.abs(cy-ty)-B.h/2,0))/G}
  o.src.forEach(function(p){var st=p.cell*4+p.d,c=p.cell%cols,k=(p.cell/cols)|0;if(p.pen<dist[st]){dist[st]=p.pen;push(p.pen+h(c,k),st)}});
  o.dst.forEach(function(p){goal[p.cell]=goal[p.cell]||[];goal[p.cell].push(p)});
  var done=-1,donePort=null,doneCost=1e9;
  while(heap.length){
    var it=pop(),st=it[1],g=dist[st];if(it[0]-0>doneCost)break;
    var cell=st>>2,d=st&3,c=cell%cols,k=(cell/cols)|0;
    if(it[0]>dist[st]+h(c,k)+1e-3)continue;
    if(goal[cell])goal[cell].forEach(function(p){var inward=(p.d+2)&3,f=g+(d===inward?0:BEND)+p.pen;if(f<doneCost){doneCost=f;done=st;donePort=p}});
    for(var nd=0;nd<4;nd++){
      if(((nd+2)&3)===d)continue;
      var nc=c+SIDES[nd][0],nk=k+SIDES[nd][1];if(nc<0||nk<0||nc>=cols||nk>=rows)continue;
      var ncell=nk*cols+nc;if(blocked[ncell])continue;
      var use=occ[ncell],pen=use&&o.to[ncell]===o.id?0:nd%2===0?(use&1?25:use&2?6:0):(use&2?25:use&1?6:0),f=g+1+pen+(nd===d?0:BEND),ns=ncell*4+nd;
      if(f<dist[ns]){dist[ns]=f;par[ns]=st;push(f+h(nc,nk),ns)}}}
  if(done<0)return null;
  var cells=[],s=done,root=done;while(s>=0){cells.push(s>>2);root=s;s=par[s]}cells.reverse();
  return{cells:cells,startDir:root&3,to:donePort}}
function simplify(p){var o=[p[0]];for(var i=1;i<p.length-1;i++){var a=o[o.length-1],b=p[i],c=p[i+1];if((a[0]===b[0]&&b[0]===c[0])||(a[1]===b[1]&&b[1]===c[1]))continue;o.push(b)}o.push(p[p.length-1]);return o}
function rounded(p){var d='M'+p[0][0]+' '+p[0][1];
  for(var i=1;i<p.length-1;i++){var a=p[i-1],b=p[i],c=p[i+1],l1=Math.abs(b[0]-a[0])+Math.abs(b[1]-a[1]),l2=Math.abs(c[0]-b[0])+Math.abs(c[1]-b[1]),r=Math.min(8,l1/2-1,l2/2-1);
    if(r<1){d+='L'+b[0]+' '+b[1];continue}
    var u1=[Math.sign(b[0]-a[0]),Math.sign(b[1]-a[1])],u2=[Math.sign(c[0]-b[0]),Math.sign(c[1]-b[1])];
    d+='L'+(b[0]-u1[0]*r)+' '+(b[1]-u1[1]*r)+'Q'+b[0]+' '+b[1]+' '+(b[0]+u2[0]*r)+' '+(b[1]+u2[1]*r)}
  var e=p[p.length-1];return d+'L'+e[0]+' '+e[1]}
function straight(a,b){var cx=a.x+a.w/2,cy=a.y+a.h/2,dx=b.x+b.w/2-cx,dy=b.y+b.h/2-cy,k=Math.min(dx?(a.w/2+4)/Math.abs(dx):1e9,dy?(a.h/2+4)/Math.abs(dy):1e9);return[[cx+dx*k,cy+dy*k]]}
function draw(){
  q('path.e',svg).forEach(function(p){p.remove()});
  if(getComputedStyle(svg).display==='none')return;
  var sr=stage.getBoundingClientRect(),W=sr.width,H=sr.height,cols=Math.ceil(W/G),rows=Math.ceil(H/G),blocked=new Uint8Array(cols*rows),occ=new Uint8Array(cols*rows),toOf=[];
  function block(r,pad){for(var k=Math.max(0,Math.floor((r.y-pad)/G));k<=Math.min(rows-1,Math.floor((r.y+r.h+pad)/G));k++)for(var c=Math.max(0,Math.floor((r.x-pad)/G));c<=Math.min(cols-1,Math.floor((r.x+r.w+pad)/G));c++){var cx=c*G+G/2,cy=k*G+G/2;if(cx>r.x-pad&&cx<r.x+r.w+pad&&cy>r.y-pad&&cy<r.y+r.h+pad)blocked[k*cols+c]=1}}
  var boxes={};q('[data-mod]',stage).forEach(function(n){var m=n.dataset.mod;if(!boxes[m]){boxes[m]=box(m);block(boxes[m],PAD)}});
  q('.zone',stage).forEach(function(n){var r=n.getBoundingClientRect(),x0=r.left-sr.left,y0=r.top-sr.top;for(var k=0;k<rows;k++)for(var c=0;c<cols;c++){var cx=c*G+G/2,cy=k*G+G/2;if(cx<x0-6||cx>x0+r.width+6||cy<y0-6||cy>y0+r.height+6)continue;if(Math.min(Math.abs(cx-x0),Math.abs(cx-x0-r.width),Math.abs(cy-y0),Math.abs(cy-y0-r.height))<6)occ[k*cols+c]|=3}});
  q('.zone-label',stage).forEach(function(n){var r=n.getBoundingClientRect();block({x:r.left-sr.left,y:r.top-sr.top,w:r.width,h:r.height},4)});
  var list=D.edges.filter(function(e){return boxes[e[0]]&&boxes[e[1]]});
  list.sort(function(a,b){function m(e){var p=boxes[e[0]],r=boxes[e[1]];return Math.abs(p.x-r.x)+Math.abs(p.y-r.y)}return m(a)-m(b)});
  var made=[];
  list.forEach(function(e){
    var a=boxes[e[0]],b=boxes[e[1]],o_src=ports(a,blocked,cols,rows),res=route(a,b,{cols:cols,rows:rows,blocked:blocked,occ:occ,to:toOf,id:e[1],src:o_src,dst:ports(b,blocked,cols,rows)}),pts;
    if(res){
      var cs=res.cells.map(function(c){return[(c%cols)*G+G/2,((c/cols)|0)*G+G/2]});
      var P=res.to,startPort=null;
      o_src.some(function(p){if(p.cell===res.cells[0]&&p.d===res.startDir){startPort=p;return true}});
      pts=[[startPort.ax,startPort.ay]].concat(cs,[[P.ax,P.ay]]);
      pts=simplify(pts);
      res.cells.forEach(function(c){toOf[c]=e[1]});
      for(var i=0;i<res.cells.length;i++){var c=res.cells[i],nx=res.cells[i+1];if(nx===undefined){occ[c]|=3;break}occ[c]|=(Math.abs(nx-c)===1?1:2);occ[nx]|=(Math.abs(nx-c)===1?1:2)}}
    else{var s0=straight(a,b)[0],s1=straight(b,a)[0];pts=[s0,s1]}
    made.push({e:e,d:rounded(pts)})});
  made.sort(function(x,y){return (x.e[2].indexOf(cur)>-1)-(y.e[2].indexOf(cur)>-1)}).forEach(function(m){var e=m.e,on=e[2].indexOf(cur)>-1,mk='url(#'+(e[3]?'fl-ahb':on?'fl-aho':'fl-ah')+')',el=document.createElementNS('http://www.w3.org/2000/svg','path');
    el.setAttribute('d',m.d);el.setAttribute('marker-end',mk);if(e[4])el.setAttribute('marker-start',mk);
    el.setAttribute('class','e'+(e[3]?' bad':'')+(on?' on':''));svg.appendChild(el)})}
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
