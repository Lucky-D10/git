import {finite,describe} from './ui.js';
export const charts=new Map();
const palette=['#148cff','#ff8b16'];
const observers=new Map();
const densities=new Map();
const density=()=>devicePixelRatio*(window.focusLayout?.scale||1);
const timeLabel=v=>{const seconds=Math.max(0,Math.round(v));return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');};
const tooltip={trigger:'axis',confine:true,backgroundColor:'#fffffff5',borderColor:'#dce9f7',textStyle:{color:'#243e66',fontSize:12}};
const emptyGraphic=(text,show)=>[{id:'empty',type:'text',left:'center',top:'middle',silent:true,invisible:!show,z:30,style:{text,fill:'#6881a1',font:'13px "Microsoft YaHei",sans-serif',backgroundColor:'#f8fcfff0',padding:12}}];
export function chart(id){
 const node=document.getElementById(id);if(!node)return null;
 if(charts.has(id)&&charts.get(id).getDom()!==node)dispose([id]);
 if(!node.clientWidth||!node.clientHeight)return null;
 if(!charts.has(id)){
  const dpr=density(),c=echarts.init(node,null,{renderer:'canvas',devicePixelRatio:dpr});charts.set(id,c);densities.set(id,dpr);
  const observer=new ResizeObserver(()=>{if(node.clientWidth&&node.clientHeight&&!c.isDisposed())c.resize();});observer.observe(node);observers.set(id,observer);
 }
 return charts.get(id);
}
export function dispose(ids){for(const id of ids){observers.get(id)?.disconnect();observers.delete(id);densities.delete(id);charts.get(id)?.dispose();charts.delete(id);}}
export function resize(){for(const [id,c] of [...charts]){
 const n=document.getElementById(id);if(!n?.offsetWidth)continue;
 if(Math.abs(densities.get(id)-density())>.01){const option=c.getOption();dispose([id]);chart(id)?.setOption(option);}
 else c.resize();
}}
export function gauge(id,p,lane=0,paused=false,thresholds=[20,70]){
 const existed=charts.has(id),c=chart(id);if(!c)return;
 const color=palette[lane],valid=p.valid&&finite(p.smoothed),value=valid?Math.max(0,Math.min(100,p.smoothed)):0;
 const target=Math.max(0,Math.min(100,finite(p.reference)?p.reference:50));
 const w=c.getWidth(),h=c.getHeight(),radius=Math.min(w*.42,h*.67),cx=w/2,cy=h*.77;
 const width=Math.max(14,Math.min(26,radius*.18));
 // Fixed zones use the session's configured thresholds, never the current value.
 const [low,high]=thresholds;
 const zoneColors=['#cbdcf0',lane?'#ffa33b':'#2997ff','#82d7c4'];
 const zones=[[low/100,zoneColors[0]],[high/100,zoneColors[1]],[1,zoneColors[2]]];
 const theta=Math.PI*(1-value/100),u=[Math.cos(theta),-Math.sin(theta)];
 const needle={x1:cx+u[0]*(radius-width-3),y1:cy+u[1]*(radius-width-3),x2:cx+u[0]*(radius+4),y2:cy+u[1]*(radius+4)};
 document.getElementById(id).setAttribute('aria-label',`平滑读数 ${valid?Math.round(value):'缺测'}，个人目标 ${target}；起步区 0 至 ${low}，专注区 ${low} 至 ${high}，高专注区 ${high} 至 100。分区不代表个人达标结果。`);
 const motion=!matchMedia('(prefers-reduced-motion: reduce)').matches&&!document.body.classList.contains('reduced-motion');
 // The needle represents the actual smoothed reading; the goal remains a separate label.
 // Missing data hides the needle instead of pointing to a misleading zero.
 c.setOption({
  animation:motion&&valid&&!paused&&existed,animationDuration:150,animationEasing:'cubicOut',animationDurationUpdate:150,animationEasingUpdate:'cubicOut',
  graphic:[
   {id:'goal-label',type:'text',silent:true,x:cx,y:Math.max(1,cy-radius-18),style:{text:'目标 '+target,fill:'#142453',font:'600 13px "Microsoft YaHei",sans-serif',align:'center',verticalAlign:'top'}},
   {id:'scale-zero',type:'text',silent:true,x:cx-radius,y:cy+5,style:{text:'0',fill:'#36567f',font:'11px sans-serif',align:'center',verticalAlign:'top'}},
   {id:'scale-max',type:'text',silent:true,x:cx+radius,y:cy+5,style:{text:'100',fill:'#36567f',font:'11px sans-serif',align:'center',verticalAlign:'top'}},
   ...['起步','专注','高专注'].map((text,i)=>({id:'zone-'+i,type:'text',silent:true,x:w*(.18+i*.32),y:h-6,style:{text:'{dot|●} '+text,fill:'#627c9c',font:`${w<200?9:11}px "Microsoft YaHei",sans-serif`,rich:{dot:{fill:zoneColors[i]}},align:'center',verticalAlign:'bottom'}})),
   {id:'attention-pointer',type:'line',silent:true,invisible:!valid,z:10,shape:needle,style:{stroke:paused?'#708aa0':'#183d56',lineWidth:3.5,lineCap:'round'},transition:motion&&valid&&!paused?['shape']:[]}
  ],
  series:[{
   id:'gauge',type:'gauge',startAngle:180,endAngle:0,center:[cx,cy],radius,
   min:0,max:100,splitNumber:2,
   axisLine:{roundCap:false,lineStyle:{width,color:zones}},
   progress:{show:false},pointer:{show:false},anchor:{show:false},
   axisTick:{show:false},splitLine:{show:false},
   axisLabel:{show:false},
   title:{show:false},
   detail:{valueAnimation:false,offsetCenter:[0,'-29%'],fontSize:Math.min(66,h*.39,w*.23),fontFamily:'Arial, "Microsoft YaHei", sans-serif',fontWeight:800,color:valid?'#0e194b':'#99a9bd',formatter:()=>valid?Math.round(value)+'':'—'},
   data:[{value}]
  }]
 });
}
export function trend(id,points,target,lane=0,now=30){
 const c=chart(id);if(!c)return;
 const data=points.filter(p=>p[0]>=now-30&&p[0]<=now).map(p=>[p[0],finite(p[2])?p[2]:null]);
 c.setOption({
  animation:false,grid:{left:30,right:32,top:7,bottom:19},
  tooltip:{trigger:'axis',confine:true,backgroundColor:'#ffffffef',borderColor:'#d5e6f7',textStyle:{color:'#19345a',fontSize:12},valueFormatter:v=>finite(v)?Math.round(v):'缺测'},
  xAxis:{type:'value',min:Math.max(0,now-30),max:Math.max(30,now),splitNumber:c.getWidth()<250?3:6,
   axisLabel:{show:true,fontSize:9,color:'#7890ab',hideOverlap:true,formatter:timeLabel},splitLine:{show:true,lineStyle:{color:'#e2edf8',width:1}},
   axisLine:{lineStyle:{color:'#b7cce8'}},axisTick:{show:false}},
  yAxis:{type:'value',min:0,max:100,interval:50,axisLabel:{fontSize:11,color:'#315584'},axisLine:{show:true,lineStyle:{color:'#afc6e4'}},splitLine:{lineStyle:{color:'#dce9f7'}},axisTick:{show:false}},
  series:[{
   id:'feedback',name:'平滑值',type:'line',smooth:.3,smoothMonotone:'x',showSymbol:data.filter(p=>p[1]!==null).length===1,symbolSize:5,connectNulls:false,data,
   lineStyle:{color:palette[lane],width:3,cap:'round',join:'round'},itemStyle:{color:palette[lane]},
   areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:lane?'#ff9d3538':'#258eff30'},{offset:1,color:'#ffffff00'}])},
   endLabel:{show:data.length>0&&data.at(-1)[1]!==null,formatter:v=>Math.round(v.value[1])+'',color:'#142457',fontSize:12,fontWeight:700,distance:6},
   labelLayout:{hideOverlap:true},
   markLine:{silent:true,symbol:'none',label:{show:false},lineStyle:{color:'#35ab93',width:1,type:'dashed'},data:[{yAxis:target}]},
   markArea:{silent:true,itemStyle:{color:lane?'#ffebc952':'#a9e7d956'},data:[[{yAxis:target},{yAxis:100}]]}
  }]
 });
}
export function review(id,report,lane=0){
 const c=chart(id);if(!c)return;
 const p=report.base.players[lane],data=report.charts[lane]?.points||[];
 const events=report.events.filter(e=>(e.event==='state_transition'&&['paused','running'].includes(e.new))||(e.event==='device_transition'&&e.lane===lane+1)).slice(-40);
 const bands=[];let paused=null,missing=null;
 for(const e of report.events){
  if(e.event==='state_transition'){
   if(e.new==='paused'&&paused===null)paused=e.t;
   else if(['running','finished','aborted'].includes(e.new)&&paused!==null){bands.push([{name:'暂停',xAxis:paused,itemStyle:{color:'#c7d5e433'}},{xAxis:e.t}]);paused=null;}
  }
  if(e.event==='device_transition'&&e.lane===lane+1){
   if(e.new!=='valid'&&missing===null)missing=e.t;
   else if(e.new==='valid'&&missing!==null){bands.push([{name:'信号中断',xAxis:missing,itemStyle:{color:'#ffe0d866'}},{xAxis:e.t}]);missing=null;}
  }
 }
 if(paused!==null)bands.push([{name:'暂停',xAxis:paused,itemStyle:{color:'#c7d5e433'}},{xAxis:report.base.now}]);
 if(missing!==null)bands.push([{name:'信号中断',xAxis:missing,itemStyle:{color:'#ffe0d866'}},{xAxis:report.base.now}]);
 const end=Math.max(1,report.base.now||0,...data.map(v=>v[0]));
 const hasData=data.some(v=>finite(v[1])||finite(v[2]));
 const tint=lane?'#ffcc92':'#b8d9ff';
 c.setOption({
  animation:false,color:[tint,palette[lane],'#17a58c'],tooltip:{...tooltip,axisPointer:{type:'cross'},valueFormatter:v=>finite(v)?Number(v).toFixed(1):'缺测'},
  graphic:emptyGraphic('暂无有效读数 · 请检查头环后再练习',!hasData),
  legend:{top:0,right:0,itemWidth:17,itemHeight:7,textStyle:{color:'#506b8f',fontSize:11},data:['原始值','平滑值','目标 '+p.reference]},grid:{left:36,right:18,top:35,bottom:51},
  xAxis:{type:'value',min:0,max:end,minInterval:end<10?.1:1,splitNumber:c.getWidth()<400?3:6,axisPointer:{label:{formatter:v=>Number(v.value).toFixed(1)+' 秒'}},axisLabel:{formatter:v=>end<10?Number(v).toFixed(1)+'s':timeLabel(v),hideOverlap:true,color:'#5876a2',fontSize:10},splitLine:{show:true,lineStyle:{color:'#e8f0fa'}}},
  yAxis:{type:'value',min:0,max:100,interval:50,axisLabel:{color:'#5876a2'},splitLine:{lineStyle:{color:'#e2edf9'}}},
  dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',filterMode:'none',showDataShadow:false,brushSelect:false,height:12,bottom:5,handleSize:'150%',borderColor:'#d8e7f9',backgroundColor:'#edf4fc',fillerColor:'#95caff88',labelFormatter:timeLabel}],
  series:[
   {id:'raw',name:'原始值',type:'line',showSymbol:true,symbolSize:(_,p)=>data.length<15||(!finite(data[p.dataIndex-1]?.[1])&&!finite(data[p.dataIndex+1]?.[1]))?4:0,connectNulls:false,data:data.map(v=>[v[0],v[1]]),lineStyle:{width:1.5,color:tint}},
   {id:'smooth',name:'平滑值',type:'line',smooth:.2,smoothMonotone:'x',showSymbol:true,symbolSize:(_,p)=>data.length<15||(!finite(data[p.dataIndex-1]?.[2])&&!finite(data[p.dataIndex+1]?.[2]))?6:0,connectNulls:false,data:data.map(v=>[v[0],v[2]]),lineStyle:{width:3},
    areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:lane?'#ffa73e26':'#2798ff26'},{offset:1,color:'#ffffff00'}])},
    markArea:{silent:true,label:{fontSize:10,color:'#9b6870',position:'insideBottom'},data:bands.slice(-40)},
    markLine:{silent:true,symbol:'none',label:{show:false},lineStyle:{width:1,type:'dashed'},data:events.slice(-16).map(e=>({name:describe(e.reason||e.new),xAxis:e.t,lineStyle:{color:e.new==='paused'?'#8094b2':'#e2aa8b'}}))}},
   {id:'goal',name:'目标 '+p.reference,type:'line',showSymbol:false,silent:true,data:[[0,p.reference],[end,p.reference]],lineStyle:{color:'#17a58c',width:1.5,type:'dashed'},itemStyle:{color:'#17a58c'}}
  ]
 },{replaceMerge:['series']});
}
export function distribution(id,report,lane=0){
 const d=report.charts[lane],c=chart(id);if(!c||!d)return;
 const total=d.distribution_seconds.reduce((a,b)=>a+b,0),colors=lane?['#ffead1','#ffce90','#ffb356','#ff9525','#ec7715']:['#d6e7fb','#accef7','#7ab7f7','#429efa','#1685f1'];
 c.setOption({animation:false,graphic:emptyGraphic('暂无有效时长 · 分布将在有数据后显示',total<=0),grid:{left:36,right:12,top:27,bottom:27},
  tooltip:{...tooltip,valueFormatter:v=>Number(v).toFixed(1)+' 秒 · '+(total?100*v/total:0).toFixed(1)+'%'},
  xAxis:{type:'category',data:d.labels,axisTick:{show:false},axisLine:{lineStyle:{color:'#ceddef'}},axisLabel:{color:'#5876a2',fontSize:10,interval:0}},
  yAxis:{type:'value',name:'有效秒',min:0,max:total?null:1,splitNumber:3,nameTextStyle:{color:'#7890aa',fontSize:10},axisLabel:{color:'#7890aa',fontSize:10},splitLine:{lineStyle:{color:'#e5eef9'}}},
  series:[{id:'distribution',type:'bar',data:d.distribution_seconds.map((value,i)=>({value,itemStyle:{color:colors[i]}})),itemStyle:{borderRadius:[7,7,0,0]},label:{show:total>0,position:'top',fontSize:11,color:'#42638b',formatter:p=>p.value>0?(100*p.value/total).toFixed(0)+'%':''},barMaxWidth:46}],
 },{replaceMerge:['series']});
}
export function historyTrend(id,rows,pid,metric='best_streak'){
 const c=chart(id);if(!c)return;const data=[...rows].sort((a,b)=>Date.parse(a.started_utc)-Date.parse(b.started_utc));
 const labels={best_streak:['最长连续','秒'],stable_ratio:['达标时间占比','%'],valid_seconds:['有效练习时长','秒']},[name,unit]=labels[metric]||labels.best_streak;
 const values=data.map(s=>{const p=s.players.find(p=>p.player_id===pid);return s.complete&&s.status==='finished'&&p?.sample_count>=2&&finite(p[metric])?p[metric]:null;});
 const enough=values.filter(finite).length>=2;
 c.setOption({animation:false,grid:{left:41,right:20,top:29,bottom:rows.length>6?60:35},
  graphic:emptyGraphic(rows.length?'暂无足够数据 · 至少两次完整练习可比较趋势':'选择训练条件，查看自己的积累',!enough),
  tooltip:{...tooltip,valueFormatter:v=>finite(v)?Number(v).toFixed(1)+' '+unit:'记录不足'},
  xAxis:{type:'category',data:data.map(s=>new Date(s.started_utc).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})),axisLabel:{color:'#5876a2',fontSize:10,hideOverlap:true,formatter:v=>v.replace(' ','\n')},axisTick:{show:false},splitLine:{show:true,lineStyle:{color:'#e6effa'}}},
  yAxis:{type:'value',name:name+' / '+unit,min:0,max:metric==='stable_ratio'?100:null,nameTextStyle:{color:'#567497',fontSize:11},axisLabel:{color:'#7890aa',fontSize:10},splitLine:{lineStyle:{color:'#e2edf9'}}},
  dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',show:rows.length>6,showDataShadow:false,brushSelect:false,height:12,bottom:4,start:rows.length>12?100-1200/rows.length:0,end:100}],
  series:[{id:'history',name,type:'line',smooth:.18,connectNulls:false,data:values,lineStyle:{color:palette[0],width:3},itemStyle:{color:palette[0],borderColor:'#fff',borderWidth:2},areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'#b3d9ff70'},{offset:1,color:'#fafdff00'}])},symbolSize:8,
   markPoint:{symbol:'circle',symbolSize:10,label:{show:enough,position:'top',fontSize:10,color:'#267fcd',formatter:v=>'最佳 '+Number(v.value).toFixed(1)},data:enough?[{type:'max'}]:[]}}],
 },{notMerge:true});
}
