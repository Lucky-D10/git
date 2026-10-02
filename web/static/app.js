import {$,escapeHtml as esc,finite,number,clock,duration,icon,avatar,headband,describe,setText,setHtml} from './js/ui.js';
import {Connection,api} from './js/connection.js';
import * as plots from './js/charts.js';
import {Race,car} from './js/race.js';
import {portrait,calmArt} from './js/illustrations.js';
import {dialArt,award,steps} from './js/design.js';

const client=new Connection();
let page='home',routeEpoch=0,reportId='',report=null,reportRetry,noticeTimer,layoutKey='',plotKey='',race=null,historyRows=[],profileId='local-1';
let preset={duration:180,distance:100,references:[50,60],bindings:[1,2],session_kind:'experience',reduced_motion:false};
let profiles=[{id:'local-1',nickname:'小蓝',avatar:'wave'},{id:'local-2',nickname:'小橙',avatar:'star'}];
let draft={activity:'training',players:1,player_ids:['local-1','local-2']};
const liveCharts=['gauge-0','gauge-1','live-plot-0','live-plot-1'];
const names={home:'专注时光',choose:'专注训练',players:'选择玩家',prepare:'佩戴头环',live:'一起专注',result:'本次收获',report:'练习详情',history:'成长记录',teacher:'老师设置',maintenance:'设备与维护'};
const state=()=>client.snapshot;
const active=s=>s&&['countdown','running','paused'].includes(s.state);
const profile=id=>profiles.find(p=>p.id===id)||{id,nickname:id||'玩家',avatar:'wave'};
const playerName=(s,i)=>profile(s.player_ids?.[i]).nickname;
const idle=()=>state()&&['preparing','finished','aborted'].includes(state().state)&&state().safety==='inhibited'&&!state().record_incomplete;
const canEdit=()=>client.allowed&&idle();
const plainSeconds=v=>finite(v)?number(v,1)+' 秒':'暂无足够数据';
const ready=()=>state()?.players.every(p=>p.valid);
window.focusDiagnostics={charts:plots.charts,observed:client.observed,get fresh(){return client.fresh;},get reportReady(){return report?.status==='ready';},disconnect:()=>client.socket?.close()};
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
document.querySelector('.app-header').insertBefore(document.querySelector('.session-clock'),$('mode'));
setHtml('home-dial',dialArt());
document.querySelectorAll('[data-stepper]').forEach(el=>el.innerHTML=steps(+el.dataset.stepper));
setHtml('home-cars',car('#248df4','home-blue')+car('#ed982f','home-orange'));

function notify(message,persistent=false){
 clearTimeout(noticeTimer);$('notice').replaceChildren(document.createTextNode(message));$('notice').hidden=false;
 if(!persistent)noticeTimer=setTimeout(()=>$('notice').hidden=true,4500);
}
function showRetry(){
 const pending=client.urgentPending||client.pending;if(!pending)return;
 notify((client.urgentPending?'急停请求':'操作')+'结果尚未确认，请重试同一请求。',true);
 const b=document.createElement('button');b.textContent='重试同一操作';b.onclick=()=>act(pending.body.action,{},true);$('notice').append(b);
}
function navigate(to){if(location.hash.slice(1)===to)route();else location.hash=to;}
let settleDialog=null;
function ask(title,text,ending=false){
 if(settleDialog)settleDialog(false);
 setText('confirm-title',title);setText('confirm-text',text);$('confirm-yes').textContent=ending?'结束并查看':'确认';$('confirm-no').textContent=ending?'继续体验':'再想一想';setHtml('confirm-icon',icon(ending?'flag':'info'));
 $('confirm-no').hidden=false;$('confirm').showModal();
 return new Promise(resolve=>{settleDialog=yes=>{$('confirm').close();settleDialog=null;resolve(yes);};});
}
$('confirm-yes').onclick=()=>settleDialog?.(true);
$('confirm-no').onclick=()=>settleDialog?.(false);
$('confirm').oncancel=e=>{e.preventDefault();settleDialog?.(false);};
async function takeControl(){if(client.allowed)return true;try{await client.claim();return true;}catch(e){notify(e.message);return false;}}
async function begin(activity){
 if(!state()||!client.fresh)return notify('请等待页面连接恢复。');
 if(active(state())||state().safety!=='inhibited'){navigate('live');return notify('请先结束当前体验，或处理当前锁定状态。');}
 if(!await takeControl())return;
 draft={activity,players:activity==='racing'?2:1,player_ids:['local-1','local-2']};
 document.querySelectorAll('[data-players]').forEach(b=>{const selected=+b.dataset.players===draft.players;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));});
 navigate(activity==='racing'?'players':'choose');
}
async function act(action,options={},retry=false){
 if(action==='emergency'){settleDialog?.(false);}
 if(!retry&&action==='end'&&!await ask('结束这次练习？','本次有效记录会保留下来。结束后可以查看收获，或再练习一次。',true))return;
 if(!retry&&action==='reset'){
  if(!await ask('确认可以重新准备？','请先排除急停原因。复位后动力仍然关闭，需要重新准备并主动开始。'))return;
  options={confirmed:true};
 }
 try{
  const sid=state()?.session_id,result=await client.command(action,options,retry);
  if(!result)return;
  if(result.reason==='result_pending_retry_same_id'){showRetry();return;}
  if(!result.ok){notify(describe(result.reason));return;}
  $('notice').hidden=true;
  if(action==='prepare')navigate('prepare');
  if(action==='start'||action==='resume'||action==='emergency')navigate('live');
  if(action==='end')navigate('result/'+sid);
  if(action==='reset'){draft.activity=state().activity;draft.players=state().players.length;navigate('players');notify('已复位，请重新准备。');}
  render();return result;
 }catch(e){notify(e.message);if(client.pending||client.urgentPending)showRetry();}
}
function route(){
 const parts=location.hash.slice(1).split('/');page=Object.hasOwn(names,parts[0])?parts[0]:'home';
 routeEpoch++;clearTimeout(reportRetry);race?.stop();
 for(const el of document.querySelectorAll('.page'))el.hidden=el.id!==page;
 setText('page-title',names[page]);document.body.dataset.page=page;window.scrollTo(0,0);
 if(page==='players')renderPlayerSelectors();
 if(page==='teacher'){fillSettings();fillProfiles();}
 if(page==='maintenance'){fillSettings();loadMaintenance();}
 if(page==='history'){fillHistoryPlayers();loadHistory();}
 if(page==='result'||page==='report'){
  const next=parts[1]||state()?.session_id||'';
  if(reportId!==next){report=null;plots.dispose(['review-chart','distribution-chart']);setText('result-title','正在整理本次记录');setText('report-status','读取中…');setHtml('result-metrics','');setHtml('detail-metrics','');setHtml('review-summary','');setHtml('review-event-key','');setText('report-insight','');setText('detail-status','读取中…');}
  reportId=next;loadReport();
 }
 render();requestAnimationFrame(plots.resize);
}
function renderPlayerSelectors(){
 const n=draft.players;const node=$('player-selectors');node.classList.toggle('single',n===1);
 setHtml('player-selectors',Array.from({length:n},(_,i)=>'<article class="card player-select-card '+(i?'orange':'blue')+'"><div class="player-heading">'+avatar(i?'star':'wave',i)+'<div><h2>'+(i?'橙色玩家':'蓝色玩家')+'</h2><small>头环 '+preset.bindings[i]+' · 个人目标 '+preset.references[i]+'</small></div></div>'+portrait(i)+'<label><span class="sr-only">选择昵称</span><select id="draft-player-'+i+'" aria-label="玩家 '+(i+1)+'">'+profiles.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===draft.player_ids[i]?'selected':'')+'>'+esc(p.nickname)+'</option>').join('')+'</select></label></article>').join(''));
 for(let i=0;i<n;i++)$('draft-player-'+i).onchange=e=>draft.player_ids[i]=e.target.value;
 setText('draft-summary',(draft.activity==='racing'?'双人虚拟竞速':n===1?'单人训练':'双人训练')+' · '+duration(preset.duration)+' · '+(preset.session_kind==='formal'?'正式规则':'轻松体验'));
}
function renderDevices(s){
 $('devices').classList.toggle('single',s.players.length===1);
 setHtml('devices',s.players.map((p,i)=>{
  const facts=[['头环连接',p.connected===true],['正确佩戴',p.worn===true],['设备校准',p.calibration==='normal'||p.valid],['收到新信号',p.valid]];
  return '<article class="card device-card '+(i?'orange':'blue')+'"><div class="player-heading">'+avatar(profile(s.player_ids[i]).avatar,i)+'<div><h2>'+esc(playerName(s,i))+'</h2><small>头环 '+s.bindings[i]+'</small></div><span class="status-tag '+(p.valid?'':'waiting')+'">'+(p.valid?'已就绪':'准备中')+'</span></div><div class="device-body">'+headband(i)+'<div class="device-facts">'+facts.map(([label,ok])=>'<span class="'+(ok?'':'waiting')+'">'+icon(ok?'check':'clock')+label+(label==='设备校准'&&finite(p.calibration_progress)&&!p.valid?' '+Math.round(p.calibration_progress*100)+'%':'')+'</span>').join('')+'</div></div><p class="device-tip">'+esc(p.valid?'准备好了，保持轻松':describe(p.reason))+'</p></article>';
 }).join(''));
 setText('prepare-title',s.players.length===2?'两位玩家都准备好了吗？':'戴好头环，准备出发');
 setText('start',ready()?'准备好了，开始！':'等待'+s.players.map((p,i)=>p.valid?'':'玩家 '+(i+1)).filter(Boolean).join('、'));
 setText('prepare-summary',(s.players.length===2?'两位玩家都准备好后，一起倒计时':'调整头环接触点，等待状态检查完成')+' · '+duration(s.duration));
 setText('prepare-hint',ready()?'所有玩家已就绪':s.players.filter(p=>!p.valid).map(p=>describe(p.reason)).join(' / '));
}
function gaugeMarkup(i){
 return '<div id="gauge-'+i+'" class="gauge" role="img" aria-label="当前平滑读数与动态指针"></div><div class="signal-help">'+headband(i)+'<div><strong>请检查头环</strong><small id="signal-help-'+i+'"></small></div></div>';
}
function buildLive(s){
 const key=s.activity+':'+s.players.length;
 if(key===layoutKey)return;
 plots.dispose(liveCharts);layoutKey=key;plotKey='';race?.stop();
 $('training-panels').hidden=s.activity==='racing';$('race-panel').hidden=s.activity!=='racing';
 if(s.activity==='racing'){race=new Race($('race-track'));return;}
 const heading=i=>'<div class="player-heading">'+avatar(i?'star':'wave',i)+'<h2 id="live-name-'+i+'"></h2><span id="live-target-'+i+'" class="target-pill"></span></div>';
 const trend=i=>'<div class="live-chart-shell"><div class="plot-heading"><span>最近 30 秒</span><span>平滑值 · 目标区</span></div><div id="live-plot-'+i+'" class="mini-plot" role="img" aria-label="最近三十秒读数曲线，缺测显示断点"></div></div>';
 if(s.players.length===1){
  $('training-panels').innerHTML='<div class="solo-layout"><article class="solo-main blue">'+heading(0)+''+gaugeMarkup(0)+'<p class="gauge-caption" id="gauge-caption-0"></p></article><div class="solo-side"><div class="solo-summary"><div class="stat-tile"><small>'+icon('clock')+'剩余时间</small><strong id="solo-time"></strong></div><div class="stat-tile"><small>'+icon('star')+'连续达标</small><strong id="streak-0"></strong></div></div><div class="calm-card">'+calmArt()+icon('leaf')+'<strong>保持自然，继续体验</strong></div></div><article class="solo-plot">'+trend(0)+'</article></div>';
 }else{
  $('training-panels').innerHTML='<div class="training-duo">'+s.players.map((p,i)=>'<article class="training-card '+(i?'orange':'blue')+'">'+heading(i)+''+gaugeMarkup(i)+'<p id="gauge-caption-'+i+'" class="gauge-caption"></p><div class="streak-line">'+icon('star')+'本次连续达标<strong id="streak-'+i+'"></strong><span>秒</span></div>'+trend(i)+'</article>').join('')+'</div>';
 }
}
function renderLive(s){
 buildLive(s);document.body.dataset.liveLayout=s.activity==='racing'?'race':s.players.length===1?'solo':'duo';
 setText('live-title',s.activity==='racing'?'双人小车竞速':s.players.length===2?'双人专注训练':'单人专注训练');
 setText('page-title',$('live-title').textContent);
 setText('state-label',describe(s.state));setText('timer-caption',s.activity==='racing'?'比赛时间':'剩余时间');setText('timer',clock(s.activity==='racing'?s.elapsed:Math.max(0,s.duration-s.elapsed)));
 if(s.activity==='racing'){
  race.update(s,s.players.map((_,i)=>playerName(s,i)),preset.reduced_motion||matchMedia('(prefers-reduced-motion: reduce)').matches,client.fresh);
  setHtml('race-status',s.players.map((p,i)=>'<div class="race-lane-status '+(i?'orange':'blue')+'">'+avatar(profile(s.player_ids[i]).avatar,i)+'<div><strong>'+esc(playerName(s,i))+'</strong><small>'+(p.valid?'动力等级 '+number(p.power*100)+'%':esc(describe(p.reason)))+'</small></div><span class="lane-progress">'+number(100*p.position/s.distance)+'%<small>虚拟进度</small></span></div>').join(''));
 }else{
  s.players.forEach((p,i)=>{
   setText('live-name-'+i,playerName(s,i));setText('live-target-'+i,'目标 '+p.reference);
   setText('gauge-caption-'+i,p.valid?(s.state==='paused'?'已暂停':p.smoothed>=p.reference?'已进入目标区':'保持自然，慢慢来'):describe(p.reason));
   $('gauge-caption-'+i).classList.toggle('waiting',!p.valid);
   $('gauge-'+i).parentElement.classList.toggle('signal-missing',!p.valid);
   setText('signal-help-'+i,describe(p.reason)+(p.valid?'':p.power===0?' · 本路已停止输出':' · 等待停止确认'));
   setText('streak-'+i,number(p.current_streak,1));setText('solo-time',clock(s.duration-s.elapsed));
  });
  const signature=s.session_id+JSON.stringify(s.players.map(p=>[p.sequence,p.generation,p.valid,p.smoothed,p.reference]))+s.state+JSON.stringify(s.chart_points.map(p=>p.slice(-1)));
  if(plotKey!==signature){plotKey=signature;s.players.forEach((p,i)=>{plots.gauge('gauge-'+i,p,i,s.state!=='running',s.attention_thresholds);plots.trend('live-plot-'+i,s.chart_points[i],p.reference,i,s.now);});}
 }
 let warning='';
 if(s.record_incomplete||!s.storage.healthy)warning='记录故障 · 请老师检查';
 else if(s.state==='running'&&s.players.some(p=>!p.valid))setText('state-label','等待信号的玩家已停止输出');
 setText('live-warning',warning);
 renderOverlay(s);
}
function renderOverlay(s){
 const buttons=['overlay-end','resume','reconnect','overlay-claim','reset','cancel-countdown','view-result','fault-maintenance','go-ready'];buttons.forEach(id=>$(id).hidden=true);
 let title='',text='',note='',symbol='',kind='';
 if(!client.fresh){title='连接暂时中断';text='正在重新连接，请稍等。';note='后台会在心跳超时后停止输出；恢复后需主动继续。';symbol=icon('signal');$('reconnect').hidden=false;}
 else if(s.safety==='emergency_locked'){kind='emergency';title='已急停 · 动力关闭';text='请老师检查原因，再确认复位。';note='旧操作不会重新启动本场。复位后需要重新准备。';symbol=icon('hand');$('reset').hidden=false;$('view-result').hidden=false;}
 else if(s.safety==='fault_locked'){kind='emergency';title='已停止 · 需要检查';text=describe(s.reason);note='故障未解决前无法恢复输出。';symbol=icon('info');$('fault-maintenance').hidden=false;$('view-result').hidden=false;}
 else if(s.state==='countdown'){kind='countdown';title='准备好，一起出发';text='保持轻松，跟随自己的节奏';symbol=String(s.countdown||'');$('cancel-countdown').hidden=false;}
 else if(s.state==='paused'){kind='paused';title=s.reason==='operator_heartbeat_timeout'?'页面重新连接，已暂停':'休息一下';$('overlay-end').hidden=false;text=ready()?'暂停时间不计入练习，连续达标会重新累计。':'请调整头环，等待每一位玩家重新就绪。';note=s.reason==='operator_heartbeat_timeout'?'刷新或关闭操作页后会暂停。请接管操作，再手动继续。':describe(s.reason);symbol=icon('pause');$('resume').hidden=false;}
 else if(s.state==='preparing'){title='先准备好头环';text='检查佩戴和连接，然后主动开始。';symbol=icon('signal');$('go-ready').hidden=false;}
 else if(['finished','aborted'].includes(s.state)){title=s.state==='finished'?'本次体验已结束':'本次体验已中断';text=describe(s.reason);symbol=icon('flag');$('view-result').hidden=false;}
 if(title&&!client.token&&client.fresh)$('overlay-claim').hidden=false;
 const countdown=kind==='countdown'&&s.activity==='training';
 $('countdown-players').hidden=!countdown;
 if(countdown)setHtml('countdown-players',s.players.map((p,i)=>'<article class="countdown-player '+(i?'orange':'blue')+'"><strong>'+esc(playerName(s,i))+'</strong>'+headband(i)+'<span>'+icon('check')+' 已就绪 · 目标 '+p.reference+'</span></article>').join(''));
 $('emergency-steps').hidden=s.safety!=='emergency_locked';
 $('state-overlay').dataset.kind=kind;
 $('state-overlay').hidden=!title;$('overlay-card').className='overlay-card '+kind;
 setHtml('overlay-icon',symbol);setText('overlay-title',title);setText('overlay-text',text);setText('overlay-note',note);
}
function renderPermissions(){
 const s=state(),normal=client.allowed&&!client.busy&&!client.pending&&!client.urgentPending;
 setText('connection',client.fresh?(s?.players.every(p=>p.valid)?'头环正常':'等待头环'):'连接中');
 $('claim').classList.toggle('owned',!!client.token);$('claim').disabled=!client.fresh||!!client.token;setText('claim',client.token?'已接管':'接管操作');
 for(const b of document.querySelectorAll('[data-action]')){
  const a=b.dataset.action,legal=s&&({start:s.state==='preparing'&&ready()&&s.safety==='inhibited',resume:s.state==='paused'&&ready()&&s.safety==='inhibited',pause:s.state==='running',end:!['finished','aborted'].includes(s.state),reset:s.safety==='emergency_locked',emergency:true})[a];
  b.disabled=a==='emergency'?!client.allowed||client.urgentBusy:!normal||!legal;
 }
 for(const id of ['prepare-submit','choose-next'])$(id).disabled=!normal||!idle();
 $('cancel-countdown').disabled=!normal||s?.state!=='countdown';
 $('overlay-claim').disabled=!client.fresh||!!client.token;
 $('again').disabled=!client.fresh||!idle();
 $('export').disabled=!client.allowed||report?.status!=='ready';
 for(const form of ['teacher-form','profile-form','bindings-form'])for(const el of $(form).elements)el.disabled=!canEdit();
 setText('settings-hint',!idle()?'请先结束本场，再调整下一场设置。':!client.allowed?'请点击右上角“接管操作”后修改。':'设置仅用于下一场，当前会话规则保持不变。');
 $('release').disabled=!client.allowed;
}
function render(){
 const s=state();
 $('connection-overlay').hidden=client.fresh||page==='live';
 setText('connection-text',s?'实时连接已中断，正在重试本地服务。':'请稍候，正在检查本地服务。');
 if(s){
  const simulation=s.mode==='simulation';setText('mode',simulation?'模拟体验':'实机采集');$('mode').classList.toggle('simulation',simulation);
  $('current-session').hidden=!active(s)&&s.safety==='inhibited';
  setText('current-label',(s.activity==='racing'?'小车竞速':'专注训练')+' · '+describe(s.state));
  if(page==='prepare')renderDevices(s);
  if(page==='live')renderLive(s);
  if(page==='maintenance')renderMaintenance(s);
 }
 renderPermissions();
}
async function prepare(){
 for(let i=0;i<draft.players;i++)draft.player_ids[i]=$('draft-player-'+i).value;
 if(new Set(draft.player_ids.slice(0,draft.players)).size!==draft.players)return notify('请选择两位不同的玩家。');
 await act('prepare',{activity:draft.activity,players:draft.players,duration:preset.duration,distance:preset.distance,references:preset.references.slice(0,draft.players),bindings:preset.bindings.slice(0,draft.players),player_ids:draft.player_ids.slice(0,draft.players),session_kind:preset.session_kind});
}
function eventText(e){return (finite(e.t)?number(e.t,1)+' 秒 · ':'')+(e.lane?'玩家 '+e.lane+' · ':'')+describe(e.reason||e.new||e.event);}
function reportStateText(r){return (r.base.mode==='simulation'?'模拟数据':'实机采集')+' · '+(r.status==='ready'?'基础记录已保存':r.status==='pending'?'正在保存，请稍候':'记录不完整，请老师检查')+' · '+describe(r.base.reason);}
async function loadReport(){
 if(!reportId){setText('report-status','请先选择一份记录。');return;}
 const epoch=routeEpoch;
 try{
  const r=(await api('/api/sessions/'+encodeURIComponent(reportId)+'/report')).report;
  if(epoch!==routeEpoch)return;report=r;
  if(page==='result')renderResult(r);else if(page==='report')renderReport(r);
  renderPermissions();
  if(r.status==='pending')reportRetry=setTimeout(loadReport,1000);
 }catch(e){if(epoch!==routeEpoch)return;setText('report-status',e.message);setText('detail-status',e.message);}
}
function renderResult(r){
 const s=r.base,rs={...s,player_ids:r.config.player_ids||[]},raceMode=s.activity==='racing',finished=s.state==='finished',enough=s.players.every(p=>p.sample_count>=2);
 setText('result-page-title',raceMode?'本次虚拟竞速':'本次专注练习');setText('result-mode',s.mode==='simulation'?'模拟记录':'实机记录');$('result-mode').classList.toggle('simulation',s.mode==='simulation');
 setHtml('result-symbol',finished?award(raceMode):icon('info'));$('result').classList.toggle('race-result',raceMode);
 let title=finished?(s.players.length===2?'一起完成，各有收获':'完成了一次专注练习！'):'本次记录已结束';
 if(raceMode&&finished&&s.result)title=s.result==='tie'?'一起抵达，平局！':playerName(rs,s.result==='player_1'?0:1)+'先到达虚拟终点';
 if(raceMode&&finished&&!s.result)title='本次虚拟竞速已结束';
 if(!finished)title='本次体验已中断';
 setText('result-title',title);
 setText('result-subtitle',raceMode?'这是一场虚拟赛程，未使用圈数传感器测量成绩':'关注自己的积累，不用和别人比较');
 setText('report-status',reportStateText(r));
 $('result-metrics').classList.toggle('single',s.players.length===1);
 $('result-race').hidden=!raceMode;
 if(raceMode){const finalRace=new Race($('result-race'));finalRace.update({...s,state:'finished'},s.players.map((_,i)=>playerName(rs,i)),true);}
 $('result-metrics').classList.toggle('solo-result',s.players.length===1);
 setHtml('result-metrics',s.players.map((p,i)=>{
  const values=raceMode?[[icon('clock')+'本场用时',clock(s.elapsed)],[icon('flag')+'虚拟进度',number(100*p.position/s.distance)+'<span> %</span>']]:[[icon('clock')+'有效训练',duration(p.valid_seconds)],[icon('chart')+'最长连续达标',p.sample_count>=2?number(p.best_streak,1)+'<span> 秒</span>':'—']];
  if(!raceMode&&s.players.length===1)values.push([icon('settings')+'本轮目标',number(p.reference)]);
  return '<article class="result-card '+(i?'orange':'blue')+'"><div class="player-heading">'+avatar(profile(rs.player_ids[i]).avatar,i)+'<h2>'+esc(playerName(rs,i))+'</h2></div><div class="result-numbers">'+values.map(([label,value])=>'<div><small>'+label+'</small><strong>'+value+'</strong></div>').join('')+'</div></article>';
 }).join(''));
 setText('result-note-text',!enough?'暂无足够数据，可以调整头环后再练习。':r.status==='incomplete'?'部分数据未保存，指标仅作参考。':'读数是本次练习反馈，不代表智力或学习成绩。');
 $('details-link').href='#report/'+reportId;
 $('result-refresh').hidden=r.status==='ready';
}
function renderReport(r){
 const ids=r.config.player_ids||[];
 const select=$('report-player'),old=select.value;
 select.replaceChildren(...r.base.players.map((_,i)=>new Option(profile(ids[i]).nickname,String(i))));
 select.value=Number(old)<r.base.players.length?old:'0';if(select.selectedIndex<0)select.value='0';
 setText('detail-status',reportStateText(r)+' · '+r.measurement_note);showReportLane();
 setHtml('report-events',r.events.slice(-100).map(e=>'<p>'+esc(eventText(e))+'</p>').join('')||'<p>没有额外事件</p>');
 $('downloads').replaceChildren();
}
function showReportLane(){
 if(!report)return;const lane=+$('report-player').value||0,p=report.base.players[lane],enough=p.sample_count>=2;
 const metrics=[['有效时长',plainSeconds(p.valid_seconds),'clock'],['达标时间占比',enough&&finite(p.stable_ratio)?number(p.stable_ratio,1)+'%':'暂无足够数据','leaf'],['最长连续达标',enough?plainSeconds(p.best_streak):'暂无足够数据','star']];
 $('report').dataset.lane=lane;
 setHtml('detail-metrics',metrics.map(([k,v,symbol])=>'<article class="card"><small>'+icon(symbol)+k+'</small><strong>'+v+'</strong></article>').join(''));
 setHtml('review-summary','<span>达标时长 <strong>'+plainSeconds(p.target_seconds)+'</strong></span><span>本轮目标 <strong>'+number(p.reference)+'</strong></span><span>平均原始值 <strong>'+(enough?number(p.average,1):'—')+'</strong></span>');
 const events=report.events.filter(e=>(e.event==='state_transition'&&['paused','running'].includes(e.new))||(e.event==='device_transition'&&e.lane===lane+1&&e.new!=='valid'));
 setHtml('review-event-key',events.slice(-8).map(e=>'<span class="event-chip '+(e.event==='device_transition'?'missing':'')+'">'+esc(clock(e.t)+' '+describe(e.reason||e.new))+'</span>').join(''));
 setText('distribution-note','按有效时长计算占比；缺测、暂停不计入分布。');
 setText('report-insight',enough?'共记录 '+p.sample_count+' 个有效样本，累计有效练习 '+plainSeconds(p.valid_seconds)+'。保持自己的节奏，看看哪些时段更接近本轮目标。':'本次有效样本不足，暂不评价趋势。图中的单个读数仍保留，继续完成一次练习后再来看。');
 plots.review('review-chart',report,lane);plots.distribution('distribution-chart',report,lane);plots.resize();
}
function fillHistoryPlayers(){
 const old=$('history-player').value;
 $('history-player').replaceChildren(...profiles.map(p=>new Option(p.nickname,p.id)));
 $('history-player').value=profiles.some(p=>p.id===old)?old:profiles[0].id;
}
function recordHtml(s){
 const p=s.players.find(p=>p.player_id===$('history-player').value),valid=s.complete&&s.status==='finished'&&p?.sample_count>=2;
 const summary=s.status==='aborted'?'本次已中断':valid?'最长连续 '+plainSeconds(p.best_streak):'暂无足够数据';
 return '<article class="record"><span class="record-symbol '+(s.activity==='racing'?'race':s.players.length===2?'duo':'')+'">'+icon(s.activity==='racing'?'flag':s.players.length===2?'people':'person')+'</span><div><strong>'+esc(new Date(s.started_utc).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}))+' · '+(s.activity==='racing'?'小车竞速':s.players.length===2?'双人训练':'单人训练')+'</strong><small>'+esc(summary)+'<br>'+esc(s.players.map(p=>profile(p.player_id).nickname).join(' / '))+' · '+(s.mode==='simulation'?'模拟':'实机')+' · '+(s.complete?'已保存':'未完整保存')+'</small></div><a aria-label="查看本次收获" href="#result/'+encodeURIComponent(s.session_id)+'">›</a></article>';
}
async function loadHistory(){
 const epoch=routeEpoch;
 try{
  const form=$('history-form'),q=new URLSearchParams({limit:'100'});
  for(const key of ['player_id','date_from','date_to'])if(form.elements[key].value)q.set(key,form.elements[key].value);
  const data=await api('/api/sessions?'+q);if(epoch!==routeEpoch)return;historyRows=data.sessions;
  const select=$('history-condition'),previous=select.value,conditions=[...new Set(historyRows.map(s=>s.condition))];
  select.replaceChildren(new Option('选择同条件记录，查看趋势',''),...conditions.map((k,i)=>{
   const row=historyRows.find(s=>s.condition===k),c=row.settings;
   const text=c?(row.activity==='training'?'训练':'竞速')+' · '+duration(c.duration)+' · 目标 '+c.references.join('/')+' · '+(row.mode==='simulation'?'模拟':'实机')+' · '+(c.session_kind==='formal'?'正式':'体验')+' · 条件 '+(i+1):'相同条件 '+(i+1)+' · '+(row.activity==='training'?'训练':'竞速')+' · '+(row.mode==='simulation'?'模拟':'实机');
   return new Option(text,k);
  }));
  select.value=conditions.includes(previous)?previous:'';renderHistory();
 }catch(e){setText('history-list',e.message);}
}
function renderHistory(){
 const condition=$('history-condition').value,rows=historyRows.filter(s=>!condition||s.condition===condition);
 setHtml('history-list',rows.map(recordHtml).join('')||'<div class="empty-state">'+icon('leaf')+'<p>这里等着记录你的第一次练习</p></div>');
 setText('history-hint',condition?'只比较同一玩家、相同条件的完整记录；中断或样本不足处保留断点。':'先选择上方条件，再看看自己的积累。');
 const metric=document.querySelector('[data-trend][aria-pressed="true"]').dataset.trend;
 const comparable=condition?rows.filter(s=>s.complete&&s.status==='finished').map(s=>s.players.find(p=>p.player_id===$('history-player').value)).filter(p=>p?.sample_count>=2):[];
 setHtml('history-summary',icon('star')+'<div><small>同条件最长连续达标</small><strong>'+(comparable.length?plainSeconds(Math.max(...comparable.map(p=>p.best_streak))):'—')+'</strong></div><span>'+comparable.length+' 次完整记录</span>');
 plots.historyTrend('trend-chart',condition?rows:[],$('history-player').value,metric);
}
function selectDuration(){const value=+$('teacher-form').elements.duration.value;document.querySelectorAll('[data-duration]').forEach(b=>{const selected=+b.dataset.duration===value;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));});}
function fillSettings(){
 const f=$('teacher-form');f.elements.duration.value=preset.duration;f.elements.distance.value=preset.distance;f.elements.reference1.value=preset.references[0];f.elements.reference2.value=preset.references[1];f.elements.session_kind.value=preset.session_kind;f.elements.reduced_motion.checked=preset.reduced_motion;
 selectDuration();
 $('bindings-form').elements.binding1.value=preset.bindings[0];$('bindings-form').elements.binding2.value=preset.bindings[1];
}
function fillProfiles(){
 const select=$('profile-select');select.replaceChildren(...profiles.map(p=>new Option(p.nickname,p.id)));
 if(!profiles.some(p=>p.id===profileId))profileId=profiles[0].id;
 select.value=profileId;fillProfile();
}
function fillProfile(){const p=profile(profileId);$('profile-form').elements.nickname.value=p.nickname;$('profile-form').elements.avatar.value=p.avatar;}
async function savePreset(next,status){
 try{const r=await api('/api/preferences',{token:client.token,preset:next});preset=r.preset;document.body.classList.toggle('reduced-motion',preset.reduced_motion);setText(status,'已保存，下次准备时生效。');}
 catch(e){setText(status,e.message);}
}
async function loadPreferences(){
 try{
  const [a,b]=await Promise.all([api('/api/preferences'),api('/api/players')]);preset=a.preset;profiles=b.players;
  document.body.classList.toggle('reduced-motion',preset.reduced_motion);
  if(page==='players')renderPlayerSelectors();
  if(page==='teacher'){fillSettings();fillProfiles();}
  if(page==='history'){fillHistoryPlayers();loadHistory();}
 }catch(e){notify('设置读取失败：'+e.message);}
}
function renderMaintenance(s){
 const row=(symbol,label,value,ok)=>'<div class="health-row">'+icon(symbol)+'<strong>'+esc(label)+'</strong><span class="health-value '+(ok?'':'needs-check')+'">'+icon(ok?'check':'info')+esc(value)+'</span></div>';
 setHtml('maintenance-status','<article class="card">'+row('settings','后台服务',s.control_alive?'正常':'需要检查',s.control_alive)+row('download','记录存储',s.storage.healthy&&!s.record_incomplete?'正常':'需要检查',s.storage.healthy&&!s.record_incomplete)+'</article><article class="card">'+s.players.map((p,i)=>row('signal','头环 '+s.bindings[i],p.valid?(s.mode==='simulation'?'模拟设备 · 就绪':'信号正常'):describe(p.reason),p.valid)).join('')+'</article>');

}
async function loadMaintenance(){
 try{const data=await api('/api/maintenance');setText('config',JSON.stringify({version:data.version,environment:data.environment,config:data.config},null,2));}
 catch(e){notify(e.message);}
}
function reconnect(){if(client.socket?.readyState===WebSocket.OPEN)return render();client.connect();}
$('teacher-form').elements.duration.addEventListener('input',selectDuration);
$('review-reset').onclick=()=>plots.charts.get('review-chart')?.dispatchAction({type:'dataZoom',start:0,end:100});
document.querySelectorAll('[data-trend]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-trend]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderHistory();});
$('choose-next').onclick=()=>navigate('players');
$('players-back').onclick=()=>navigate(draft.activity==='racing'?'home':'choose');
$('prepare-submit').onclick=prepare;
$('claim').onclick=takeControl;$('overlay-claim').onclick=takeControl;
$('retry-connection').onclick=reconnect;$('reconnect').onclick=reconnect;
$('cancel-countdown').onclick=()=>act('end');
$('view-result').onclick=()=>navigate('result/'+state().session_id);
$('again').onclick=()=>begin(report?.base.activity||'training');
$('result-refresh').onclick=loadReport;
$('report-back').onclick=()=>navigate('result/'+reportId);
$('report-player').onchange=showReportLane;
$('history-form').onsubmit=e=>{e.preventDefault();loadHistory();};
$('history-condition').onchange=renderHistory;
$('teacher-form').onsubmit=e=>{
 e.preventDefault();const f=e.target;savePreset({...preset,duration:+f.elements.duration.value,distance:+f.elements.distance.value,references:[+f.elements.reference1.value,+f.elements.reference2.value],session_kind:f.elements.session_kind.value,reduced_motion:f.elements.reduced_motion.checked},'settings-status');
};
$('bindings-form').onsubmit=e=>{e.preventDefault();const f=e.target;savePreset({...preset,bindings:[+f.elements.binding1.value,+f.elements.binding2.value]},'bindings-status');};
$('profile-select').onchange=e=>{profileId=e.target.value;fillProfile();};
$('add-player').onclick=()=>{
 profileId='p-'+crypto.randomUUID();$('profile-select').append(new Option('新玩家',profileId));$('profile-select').value=profileId;
 $('profile-form').elements.nickname.value='';$('profile-form').elements.avatar.value='leaf';$('profile-form').elements.nickname.focus();
};
$('profile-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target;
 try{const r=await api('/api/players',{token:client.token,player:{id:profileId,nickname:f.elements.nickname.value,avatar:f.elements.avatar.value}});profiles=profiles.some(p=>p.id===r.player.id)?profiles.map(p=>p.id===r.player.id?r.player:p):[...profiles,r.player];fillProfiles();setText('profile-status','昵称已保存。');}
 catch(error){setText('profile-status',error.message);}
};
$('export').onclick=async()=>{
 try{const r=await api('/api/sessions/'+encodeURIComponent(reportId)+'/export',{token:client.token});$('downloads').replaceChildren(...r.files.map(url=>{const a=document.createElement('a');a.href=url;a.download='';a.textContent=url.endsWith('.csv')?'逐路样本 CSV':'基础报告 JSON';return a;}));}
 catch(e){notify(e.message);}
};
$('refresh-maintenance').onclick=loadMaintenance;
$('version-button').onclick=()=>{$('version-details').open=true;$('version-details').scrollIntoView({block:'nearest'});};
$('diagnostics').onclick=()=>ask('当前头环状态',state().players.map((p,i)=>'头环 '+state().bindings[i]+'：'+describe(p.reason)+'；连接'+(p.connected?'正常':'未建立')+'，佩戴'+(p.worn===true?'确认':'待确认')+'，设备校准 '+p.calibration).join('。')+'。此页仅查看状态，不会占用采集端口。');
$('release').onclick=()=>client.release().catch(e=>notify(e.message));
$('maintenance-exit').onclick=async()=>{
 if(!client.allowed)return notify('请先接管操作。');
 if(!['finished','aborted'].includes(state().state)){const r=await act('end');if(!r?.ok)return;}
 await client.release();notify('已退出操作模式。可按 Alt+F4 返回桌面维护。');navigate('maintenance');
};
document.addEventListener('click',event=>{
 const action=event.target.closest('[data-action]');if(action&&!action.disabled)act(action.dataset.action,{},action.dataset.action==='emergency'&&!!client.urgentPending);
 const nav=event.target.closest('[data-nav]');if(nav)navigate(nav.dataset.nav);
 const prep=event.target.closest('[data-prepare]');if(prep)begin(prep.dataset.prepare);
 const count=event.target.closest('[data-players]');if(count){draft.players=+count.dataset.players;document.querySelectorAll('[data-players]').forEach(b=>{b.classList.toggle('selected',b===count);b.setAttribute('aria-pressed',String(b===count));});}
 const d=event.target.closest('[data-duration]');if(d&&!d.disabled){$('teacher-form').elements.duration.value=d.dataset.duration;selectDuration();}
 const step=event.target.closest('[data-step]');if(step&&!step.disabled){const [name,amount]=step.dataset.step.split(':');const input=$('teacher-form').elements[name];input.value=Math.max(0,Math.min(100,+input.value+Number(amount)));}
});
client.addEventListener('change',render);
client.addEventListener('snapshot',({detail:{previous,packet}})=>{
 const s=packet.snapshot;
 if(previous&&previous.session_id===s.session_id&&!['finished','aborted'].includes(previous.state)&&['finished','aborted'].includes(s.state)&&page==='live'&&!['emergency_locked','fault_locked'].includes(s.safety))navigate('result/'+s.session_id);
 // Only acknowledge samples after the actual live canvas has had a paint opportunity.
 if(page==='live'&&s.state==='running')requestAnimationFrame(()=>requestAnimationFrame(()=>{if(page==='live')client.ack(packet);}));
});
window.addEventListener('hashchange',route);
window.addEventListener('resize',()=>{plots.resize();plotKey='';render();if(page==='result'&&report)renderResult(report);});
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('confirm').open&&client.allowed){e.preventDefault();act('emergency',{},!!client.urgentPending);}});
window.addEventListener('beforeunload',()=>client.socket?.close());
route();client.start();loadPreferences();

