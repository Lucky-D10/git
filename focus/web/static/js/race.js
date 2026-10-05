// Locally bundled car sprites; gameplay motion remains owned by backend snapshots.
export function car(color='#148cff',prefix='car'){
 const orange=['#ed982f','#ed922f','#f39a32','#ff8b16'].includes(color);
 return `<img class="sports-car" src="/static/assets/cars/${orange?'orange':'blue'}-v3.png" alt="" aria-hidden="true" draggable="false" width="160" height="80">`;
}
function shrub(x,y,scale=1){return `<g transform="translate(${x} ${y}) scale(${scale})"><ellipse cy="8" rx="17" ry="6" fill="#72a65a" opacity=".4"/><path d="M-15 5Q-22-4-11-6Q-10-18 0-12Q12-17 14-6Q26-1 14 7Z" fill="#659b4b"/><path d="M-10-6Q-11-14 0-11Q11-16 12-6Q6-1 0-4Q-8 2-10-6" fill="#83b867"/><circle cx="9" cy="4" r="2.2" fill="#f4c946"/></g>`;}
function garden(){
 const bushes=[[65,17,.75],[191,16,.65],[320,18,.7],[462,17,.7],[596,17,.8],[696,16,.55],[116,221,.75],[252,222,.6],[393,222,.7],[546,221,.8],[671,224,.7]];
 return `<svg class="garden-art" viewBox="0 0 760 242" preserveAspectRatio="none" aria-hidden="true">
 <defs><linearGradient id="lawn" x2="0" y2="1"><stop stop-color="#bce899"/><stop offset="1" stop-color="#93cd76"/></linearGradient></defs>
 <rect width="760" height="242" rx="12" fill="url(#lawn)"/>
 ${bushes.map(args=>shrub(...args)).join('')}
 <g stroke="#91be63" stroke-width="2" fill="none">${[135,262,381,511,639].map(x=>`<path d="m${x} 18-4-5m4 5 4-7m-4 7v-8M${x-30} 226l-3-5m3 5 4-7"/>`).join('')}</g>
 <g fill="#f7ee9c">${[160,284,420,529,619].map(x=>`<circle cx="${x}" cy="17" r="2"/><circle cx="${x+4}" cy="14" r="2"/><circle cx="${x+8}" cy="18" r="2"/>`).join('')}</g>
 </svg>`;
}
export function mountRace(node){
 node.innerHTML=`<div class="track-scenery">${garden()}<span class="track-label start-label">起点</span><span class="track-label finish-label">终点</span><div class="curb curb-top"></div><div class="curb curb-bottom"></div><div class="road"><svg class="road-texture" aria-hidden="true"><defs><pattern id="asphalt" width="39" height="31" patternUnits="userSpaceOnUse"><path d="M2 5h1m13 3h1m14 7h1M5 23h1m13 2h1m16-21h1M10 15h1m16 12h1" stroke="#eef3f8" stroke-width=".7"/><path d="M4 11h1m19-6h1m7 17h1M11 28h1m4-8h1" stroke="#43596d" stroke-width=".7"/></pattern></defs><rect width="100%" height="100%" fill="url(#asphalt)"/></svg><div class="start-line"></div><div class="finish-line"></div><div class="lane-separator"></div><div class="race-car blue" data-lane="0"><i class="speed-trail"></i>${car('#148cff','race-blue')}<span></span></div><div class="race-car orange" data-lane="1"><i class="speed-trail"></i>${car('#ff8b16','race-orange')}<span></span></div></div><i class="tires top-left"></i><i class="tires top-right"></i><i class="tires bottom-left"></i><i class="tires bottom-right"></i></div>`;
}
export class Race{
 constructor(node){this.node=node;mountRace(node);this.sid='';this.current=[0,0];this.frame=null;}
 update(snapshot,names,reduced=false,fresh=true){
  if(snapshot.session_id!==this.sid){this.sid=snapshot.session_id;this.current=[0,0];}
  cancelAnimationFrame(this.frame);
  const previous=[...this.current],target=snapshot.players.map(p=>Math.max(0,Math.min(1,p.position/snapshot.distance)));
  const moving=snapshot.state==='running'&&fresh;
  const nodes=[...this.node.querySelectorAll('.race-car')];
  nodes.forEach((el,i)=>{
   const p=snapshot.players[i],driving=moving&&p.valid&&p.power>.02&&!reduced;
   // The backend owns the boost threshold and continuous hold time.
   const boosting=driving&&p.boost_active===true;
   const progress=Number.isFinite(p.boost_progress)?Math.max(0,Math.min(1,p.boost_progress)):0;
   el.querySelector('span').textContent=names[i];
   el.classList.toggle('waiting',!p.valid);
   el.classList.toggle('driving',driving);
   el.classList.toggle('boosting',boosting);
   el.style.setProperty('--boost-progress',boosting?progress:0);
  });
  const travel=Math.max(0,this.node.querySelector('.road').clientWidth-34-nodes[0].offsetWidth-18),started=performance.now(),ms=reduced||!moving?0:90;
  const draw=t=>{
   const alpha=ms?Math.min(1,(t-started)/ms):1;
   nodes.forEach((el,i)=>{
    const p=snapshot.players[i],ratio=(!p.valid||!moving)?target[i]:previous[i]+(target[i]-previous[i])*alpha;
    this.current[i]=ratio;el.style.transform=`translateX(${travel*ratio}px)`;
    el.classList.toggle('near-start',ratio<.12);
   });
   if(alpha<1)this.frame=requestAnimationFrame(draw);
  };
  draw(started);
 }
 stop(){cancelAnimationFrame(this.frame);this.node.querySelectorAll('.race-car').forEach(el=>{el.classList.remove('driving','boosting');el.style.setProperty('--boost-progress',0);});}
}
