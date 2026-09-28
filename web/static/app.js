'use strict';
const $ = id => document.getElementById(id);
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {preparing:'准备中',countdown:'统一倒计时',running:'进行中',paused:'已暂停',finished:'已结束',aborted:'已中断',valid:'信号正常',not_connected:'未连接',not_worn:'未佩戴',calibrating:'校准中',calibration_timeout:'校准超时',stale:'数据停止更新',not_ready:'指定玩家尚未就绪',illegal_state:'当前状态不允许此操作',operator_required:'请先成为操作端',operator_busy_or_disconnected:'已有操作端，或实时连接尚未就绪',operator_heartbeat_timeout:'操作端失联，已暂停，请手动继续',stale_session:'忽略上一场操作，请刷新当前状态',unverified_identity:'SDK 无可靠更新标识',all_signals_lost:'全部信号丢失，本场中断',countdown_signal_lost:'倒计时中信号丢失',manual_pause:'手动暂停',manual_end:'手动结束',duration_complete:'训练完成',virtual_finish:'抵达虚拟终点',emergency:'急停锁定',sdk_zero_unverified:'SDK 零值定义未确认',storage_buffer_timeout:'记录积压超时',result_pending_retry_same_id:'结果待确认，可重试同一操作',report_not_ready:'报告正在保存，请稍后刷新'};
const describe = x => labels[x] || x || '等待新一场';
const num = (x, unit='') => typeof x === 'number' && Number.isFinite(x) ? x.toFixed(1)+unit : '暂无足够数据';
const uuid = () => crypto.randomUUID();
let state, socket, connection, token='', page='', reportId='', lastSnapshot=0, busy=false, pending=null, retryTimer, routeEpoch=0;
let lastPlot='', message='正在连接本地服务。', selectedCondition='', reportRetry;
const charts = new Map(), latency = [], observed = new Map();
window.focusDiagnostics = {latency, charts, observed};
function chart(id) {
  if (!charts.has(id)) charts.set(id, echarts.init($(id), null, {renderer:'canvas'}));
  return charts.get(id);
}
function baseChart() {return {animation:false,color:['#6cbaff','#ffab73','#83d5bc','#e8ca87'],tooltip:{trigger:'axis'},legend:{textStyle:{color:'#b1c2d6'},top:0},grid:{left:42,right:22,top:32,bottom:46},xAxis:{type:'value',name:'秒',axisLabel:{color:'#9db1c8'}},yAxis:{type:'value',min:0,max:100,axisLabel:{color:'#9db1c8'},splitLine:{lineStyle:{color:'#24374b'}}},dataZoom:[{type:'inside'},{type:'slider',height:16,bottom:0}],series:[]};}
function fresh() {return !!(socket && socket.readyState === WebSocket.OPEN && connection && performance.now()-lastSnapshot<700);}
async function api(url, options={}) {
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),4000);
  try {
    const response=await fetch(url,{...options,headers:{'Content-Type':'application/json','X-Focus-Client':'web',...options.headers},signal:controller.signal});
    const result=await response.json();
    if (!response.ok) throw new Error(describe(result.reason || result.detail || response.status));
    return result;
  } finally {clearTimeout(timeout);}
}
function notify(text) {message=text;$('notice').textContent=text;}
function navigate(to) {if(location.hash.slice(1)===to)route();else location.hash=to;}
function route() {
  const parts=location.hash.slice(1).split('/');
  page=['home','prepare','live','report','history','maintenance'].includes(parts[0])?parts[0]:'home';
  routeEpoch++;
  clearTimeout(reportRetry);
  for(const el of document.querySelectorAll('.page'))el.hidden=el.id!==page;
  for(const a of document.querySelectorAll('nav a'))a.classList.toggle('active',a.hash==='#'+page);
  if(page==='home')loadRecent();
  if(page==='history')loadHistory();
  if(page==='report'){reportId=parts[1]||state?.session_id||'';loadReport();}
  if(page==='maintenance')loadMaintenance();
  if(page==='live')lastPlot='';
  renderState();
  requestAnimationFrame(()=>charts.forEach(c=>c.resize()));
}
function connect() {
  clearTimeout(retryTimer);
  socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
  socket.onmessage=event=>{
    const packet=JSON.parse(event.data);
    if(packet.type==='hello'){connection=packet.connection;return;}
    if(packet.type==='heartbeat'){if(!packet.ok){token='';notify('操作权限已失效，请重新领取。');}return;}
    if(packet.type!=='snapshot')return;
    const old=state;
    state=packet.snapshot;lastSnapshot=performance.now();
    if(!old)notify('已连接。请选择训练，并领取操作权限。');
    renderState();
    if(old && old.session_id===state.session_id && !['finished','aborted'].includes(old.state) && ['finished','aborted'].includes(state.state) && page==='live')navigate('report/'+state.session_id);
    // Age starts at adapter receive time, not headband acquisition. Add half a local RTT estimate below.
    requestAnimationFrame(()=>{const keys=[];packet.snapshot.players.forEach((p,i)=>{
      const key=packet.snapshot.session_id+':'+i+':'+p.generation+':'+p.sequence;
      if(p.valid && !observed.has(key)){
        observed.set(key,true);
        keys.push(key);
        const age=packet.sample_ages_ms[i];
        if(Number.isFinite(age)){latency.push(age+performance.now()-lastSnapshot+(window.focusDiagnostics.rtt||0)/2);if(latency.length>2000)latency.shift();}
        if(observed.size>2000)observed.delete(observed.keys().next().value);
      }
    });if(keys.length && socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'rendered',packet_id:packet.packet_id,keys}));});
  };
  socket.onclose=()=>{connection=null;token='';lastSnapshot=0;notify('实时连接断开，操作已禁用。后台将暂停输出。');renderState();retryTimer=setTimeout(connect,1000);};
  socket.onerror=()=>socket.close();
}
setInterval(()=>{
  if(token && fresh())socket.send(JSON.stringify({type:'heartbeat',token}));
  renderPermissions();
},400);
setInterval(async()=>{const t=performance.now();try{await api('/api/health');window.focusDiagnostics.rtt=performance.now()-t;}catch{}},5000);
async function claim() {
  if(!fresh())return notify('先等待实时连接恢复。');
  try {const x=await api('/api/control/claim',{method:'POST',body:JSON.stringify({connection,request_id:uuid()})});token=x.token;socket.send(JSON.stringify({type:'heartbeat',token}));notify('本页面现在是操作端；其他页面只读观看。');renderPermissions();}catch(e){notify(e.message);}
}
function ask(text) {return new Promise(resolve=>{$('confirm-text').textContent=text;$('confirm').showModal();const done=yes=>{$('confirm').close();resolve(yes);};$('confirm-yes').onclick=()=>done(true);$('confirm-no').onclick=()=>done(false);$('confirm').oncancel=()=>resolve(false);});}
async function perform(action, options={}, usePending=false) {
  if(!fresh()||!token||busy)return notify('当前不可操作：请连接并领取操作权限。');
  if(!usePending && pending)return notify('上一操作结果尚未确认，请先点击通知中的“重试”。');
  if(!usePending && action==='reset' && !await ask('确认已排除急停原因？复位后仍需创建新一场，不会自动输出。'))return;
  if(!usePending && action==='end' && !await ask('结束本场并保存基础报告？'))return;
  busy=true;renderPermissions();
  const envelope=usePending?pending:{sid:state.session_id,body:{action,request_id:uuid(),token,...options,...(action==='reset'?{confirmed:true}:{})}};
  pending=envelope;
  try {
    let result=await api('/api/session/'+encodeURIComponent(envelope.sid)+'/action',{method:'POST',body:JSON.stringify(envelope.body)});
    if(result.reason==='result_pending_retry_same_id'){showRetry();return result;}
    pending=null;
    if(!result.ok){notify(describe(result.reason));return result;}
    // Fetch post-operation snapshot before allowing a second command.
    const latest=await api('/api/session');state=latest.snapshot;
    notify('操作已确认 · '+describe(result.state));
    if(action==='start'||action==='resume')navigate('live');
    if(action==='prepare')navigate('prepare');
    if(action==='end')navigate('report/'+envelope.sid);
    renderState();return result;
  } catch(e) {notify('结果尚未确认：'+e.message);showRetry();}
  finally {busy=false;renderPermissions();}
}
function showRetry() {
  $('notice').textContent='操作结果尚未确认，请保持原请求编号重试。';
  const button=document.createElement('button');button.textContent='重试同一操作';button.onclick=()=>perform(pending.body.action,{},true);$('notice').append(button);
}
function deviceCard(p,i) {
  return '<article class="card '+(i?'orange':'')+'"><h3>'+ (i?'◆':'●')+' 玩家 '+(i+1)+' · '+escapeHtml(state.player_ids[i])+'</h3><p>绑定头环 '+state.bindings[i]+' · '+escapeHtml(describe(p.reason))+'</p><p>连接 '+(p.connected?'✓':'—')+' / 佩戴 '+(p.worn===true?'✓':p.worn===false?'否':'待确认')+' / 设备校准 '+escapeHtml(p.calibration)+' '+(p.calibration_progress==null?'':Math.round(p.calibration_progress*100)+'%')+'</p></article>';
}
function metricCard(p,i) {
  return '<article class="card '+(i?'orange':'')+'"><h3>'+(i?'◆':'●')+' 玩家 '+(i+1)+' · '+escapeHtml(describe(p.reason))+'</h3><div class="metric-row"><div><small>原始 Attention</small><strong>'+num(p.raw)+'</strong></div><div><small>平滑值 / 动力</small><span>'+num(p.smoothed)+' / '+num(p.power*100,'%')+'</span></div><div><small>有效时间 / 达标</small><span>'+num(p.valid_seconds,'s')+' / '+num(p.stable_ratio,'%')+'</span></div></div><p>目标 '+p.reference+' · 当前连续 '+num(p.current_streak,'s')+' · 最长 '+num(p.best_streak,'s')+' · '+p.sample_count+' 个运行中有效样本</p></article>';
}
function eventText(e){return (e.t==null?'':num(e.t,'s')+' · ')+(e.lane?'玩家 '+e.lane+' · ':'')+describe(e.reason||e.new||e.event);}
function renderPermissions(){
  $('connection').textContent=fresh()?(token?'● 本页操作端':'○ 只读观看'):'○ 连接中 / 过期';
  $('claim').disabled=!fresh()||!!token||busy;$('claim').textContent=token?'本页操作端':'成为操作端';
  const enabled=fresh()&&!!token&&!busy&&!pending;
  document.querySelectorAll('.controlled').forEach(b=>b.disabled=!enabled);
  if(!state)return;
  document.querySelectorAll('[data-action]').forEach(b=>{
    const ready=state.players.every(p=>p.valid), a=b.dataset.action;
    const allowed={start:state.state==='preparing'&&ready,pause:state.state==='running',resume:state.state==='paused'&&ready,end:!['finished','aborted'].includes(state.state),emergency:true,reset:state.safety==='emergency_locked'}[a];
    b.hidden=!allowed && ['start','resume','reset'].includes(a);
    b.disabled=!enabled||!allowed;
  });
  $('export').disabled=!enabled||!window.focusDiagnostics.reportReady;
  const prep=$('prepare-form').querySelector('button');
  prep.disabled=!enabled||!['preparing','finished','aborted'].includes(state.state)||state.safety!=='inhibited'||state.record_incomplete;
}
function renderState(){
  renderPermissions();if(!state)return;
  $('mode').textContent=state.mode==='simulation'?'模拟数据':'实机采集';
  $('devices').innerHTML=state.players.map(deviceCard).join('');
  $('prepare-hint').textContent=state.players.every(p=>p.valid)?'已就绪，可统一倒计时':'未就绪：'+state.players.map(p=>describe(p.reason)).join(' / ');
  $('live-title').textContent=state.activity==='racing'?'双人竞速 · 虚拟赛程':'专注训练';
  $('timer').textContent=num(state.elapsed,' s');
  $('state-label').textContent=describe(state.state)+(state.countdown?' · '+state.countdown:'');
  $('metrics').innerHTML=state.players.map(metricCard).join('');
  $('race-progress').hidden=state.activity!=='racing';
  $('race-progress').innerHTML=state.players.map((p,i)=>'<div class="track '+(i?'orange':'')+'"><span>玩家 '+(i+1)+'</span><progress max="'+state.distance+'" value="'+p.position+'"></progress><span>'+num(p.position)+' / '+state.distance+'</span></div>').join('')+'<p>'+escapeHtml(state.result?({tie:'平局',player_1:'玩家 1 获胜',player_2:'玩家 2 获胜'}[state.result]):'虚拟位置由后台计算，未使用圈数传感器')+'</p>';
  $('events').innerHTML=state.events.slice(-5).map(e=>'<p>'+escapeHtml(eventText(e))+'</p>').join('');
  if(state.storage.error || state.record_incomplete)notify('记录故障：'+(state.storage.error||'记录不完整'));
  else if(state.reason==='operator_heartbeat_timeout')notify(describe(state.reason));
  if(page==='live'){
    const signature=state.session_id+JSON.stringify(state.chart_points.map(p=>p.slice(-1)))+state.state;
    if(signature!==lastPlot){
      lastPlot=signature;
      const c=chart('live-chart'),op=baseChart(),series=[];
      state.players.forEach((p,i)=>{
        const data=state.chart_points[i].filter(v=>v[0]>=state.now-60);
        for(let column=1;column<=2;column++)series.push({id:i+'-'+column,name:'玩家'+(i+1)+(column===1?' 原始':' 平滑'),type:'line',showSymbol:false,connectNulls:false,data:data.map(v=>[v[0],v[column]]),lineStyle:{color:i?'#ffab73':'#6cbaff',type:column===1?'solid':'dashed'},itemStyle:{color:i?'#ffab73':'#6cbaff'}});
      });
      op.xAxis.min=Math.max(0,state.now-60);op.xAxis.max=Math.max(10,state.now);
      op.series=series;c.setOption(op,{replaceMerge:['series']});
    }
  }
}
function formChanged(){const f=$('prepare-form');if(f.elements.activity.value==='racing')f.elements.players.value='2';$('second-player').hidden=f.elements.players.value==='1';}
$('prepare-form').onchange=formChanged;
$('prepare-form').onsubmit=event=>{
  event.preventDefault();
  const f=event.target,n=+f.elements.players.value,bindings=[],references=[],player_ids=[];
  for(let i=1;i<=n;i++){bindings.push(+f.elements['binding'+i].value);references.push(+f.elements['reference'+i].value);player_ids.push(f.elements['player'+i].value.trim());}
  if(new Set(bindings).size!==n || new Set(player_ids).size!==n)return notify('头环绑定和玩家编号必须各自唯一。');
  perform('prepare',{activity:f.elements.activity.value,players:n,duration:+f.elements.duration.value,distance:+f.elements.distance.value,session_kind:f.elements.session_kind.value,bindings,references,player_ids});
};
function recordHtml(s){return '<div class="record"><div class="meta">'+escapeHtml(s.started_utc.replace('T',' ').slice(0,19))+' · '+(s.activity==='training'?'训练':'竞速')+'<small>'+escapeHtml((s.mode==='simulation'?'模拟':'实机')+' · '+describe(s.status)+' · '+s.players.map(p=>p.player_id).join(' / '))+'</small></div><a class="button" href="#report/'+s.session_id+'">查看报告</a></div>';}
async function loadRecent(){try{const data=await api('/api/sessions?limit=4');$('recent').innerHTML=data.sessions.map(recordHtml).join('')||'<p>暂无记录，完成第一场训练后会显示在这里。</p>';}catch(e){$('recent').textContent=e.message;}}
async function loadReport(){
  if(!reportId)return notify('尚未选择报告。');
  const epoch=routeEpoch;
  try{
    const result=await api('/api/sessions/'+encodeURIComponent(reportId)+'/report');if(epoch!==routeEpoch)return;
    const r=result.report;window.focusDiagnostics.reportReady=r.status==='ready';
    $('report-status').textContent=(r.base.mode==='simulation'?'模拟数据':'实机采集')+' · '+describe(r.base.reason)+' · '+(r.status==='ready'?'已完整保存':r.status==='pending'?'保存中':'记录不完整')+' · '+r.measurement_note;
    $('report-metrics').innerHTML=r.base.players.map((p,i)=>'<div class="card '+(i?'orange':'')+'"><h3>玩家 '+(i+1)+' · '+(p.sample_count>=2?'数据充分':'暂无足够数据')+'</h3><p>有效 '+num(p.valid_seconds,'s')+' / 达标 '+num(p.stable_ratio,'%')+'</p><p>平均 '+num(p.average)+' / 趋势变化 '+num(p.trend)+' / 最长连续 '+num(p.best_streak,'s')+'</p></div>').join('');
    $('report-events').innerHTML=r.events.slice(-100).map(e=>'<p>'+escapeHtml(eventText(e))+'</p>').join('');
    let review=baseChart(),series=[];
    r.charts.forEach((lane,i)=>{for(let col=1;col<=2;col++)series.push({id:i+'-'+col,name:'玩家'+(i+1)+(col===1?' 原始':' 平滑'),type:'line',showSymbol:false,connectNulls:false,data:lane.points.map(v=>[v[0],v[col]]),lineStyle:{color:i?'#ffab73':'#6cbaff',type:col===1?'solid':'dashed'},itemStyle:{color:i?'#ffab73':'#6cbaff'},markLine:col===1?{symbol:'none',label:{show:false},data:[{name:'目标 '+r.base.players[i].reference,yAxis:r.base.players[i].reference},...r.events.filter(e=>e.event==='state_transition'||e.event==='device_transition').slice(-60).map(e=>({name:describe(e.reason||e.new),xAxis:e.t}))]}:undefined});});
    review.series=series;chart('review-chart').setOption(review,{replaceMerge:['series']});
    const dist=baseChart();dist.xAxis={type:'category',data:r.charts[0]?.labels||[],axisLabel:{color:'#a5b4c6'}};dist.yAxis={type:'value',name:'有效秒',axisLabel:{color:'#a5b4c6'}};dist.series=r.charts.map((d,i)=>({name:'玩家'+(i+1),type:'bar',data:d.distribution_seconds}));chart('distribution-chart').setOption(dist,{replaceMerge:['series']});
    renderPermissions();if(r.status==='pending')reportRetry=setTimeout(loadReport,800);
  }catch(e){if(epoch!==routeEpoch)return;$('report-status').textContent=e.message;if(state&&reportId===state.session_id)reportRetry=setTimeout(loadReport,1000);}
}
$('export').onclick=async()=>{try{const r=await api('/api/sessions/'+reportId+'/export',{method:'POST',body:JSON.stringify({token})});$('downloads').replaceChildren(...r.files.map(url=>{const a=document.createElement('a');a.href=url;a.download='';a.textContent=url.endsWith('.csv')?'下载逐路 CSV':'下载基础报告 JSON';return a;}));}catch(e){notify(e.message);}};
$('history-form').onsubmit=e=>{e.preventDefault();loadHistory();};
async function loadHistory(){
  try{
    const f=$('history-form'),q=new URLSearchParams();
    for(const name of ['player_id','date_from','date_to'])if(f.elements[name].value)q.set(name,f.elements[name].value);
    selectedCondition=f.elements.condition.value;
    const data=await api('/api/sessions?'+q);
    const select=f.elements.condition, keys=[...new Set(data.sessions.map(s=>s.condition))];
    select.replaceChildren(new Option('选择同条件记录对比',''),...keys.map(k=>new Option(k,k)));
    select.value=keys.includes(selectedCondition)?selectedCondition:'';
    const rows=data.sessions.filter(s=>!select.value||s.condition===select.value);
    $('history-list').innerHTML=rows.map(recordHtml).join('')||'<p>此条件下暂无记录。</p>';
    const op=baseChart(),ordered=rows.filter(s=>s.complete).reverse();
    op.xAxis={type:'category',data:ordered.map(s=>s.started_utc.slice(5,16)),axisLabel:{color:'#a5b4c6'}};
    op.yAxis.name='达标 %';
    const ids=[...new Set(ordered.flatMap(s=>s.players.map(p=>p.player_id)))].slice(0,8);
    op.series=select.value?ids.map(pid=>({name:pid,type:'line',connectNulls:false,data:ordered.map(s=>s.players.find(p=>p.player_id===pid)?.stable_ratio??null)})):[];
    chart('trend-chart').setOption(op,{replaceMerge:['series']});
  }catch(e){notify(e.message);}
}
async function loadMaintenance(){try{const data=await api('/api/maintenance');$('config').textContent=JSON.stringify({version:data.version,environment:data.environment,config:data.config},null,2);$('maintenance-status').innerHTML='<div class="card"><h3>'+escapeHtml(data.version)+' · '+escapeHtml(data.snapshot.mode)+'</h3><p>控制线程 '+(data.snapshot.control_alive?'正常':'异常')+' / 记录 '+(data.snapshot.storage.healthy?'正常':'故障')+'</p><p>'+escapeHtml(data.diagnostics_note)+'</p>'+data.snapshot.players.map((p,i)=>'<p>头环 '+data.snapshot.bindings[i]+'：'+escapeHtml(describe(p.reason))+'</p>').join('')+'</div>';}catch(e){notify(e.message);}}
async function release(){if(token)await api('/api/control/release',{method:'POST',body:JSON.stringify({token})});token='';renderPermissions();}
$('release').onclick=()=>release().catch(e=>notify(e.message));
$('maintenance-exit').onclick=async()=>{if(!await ask('停止当前训练并退出操作模式，进入维护？'))return;if(!['finished','aborted'].includes(state.state)){const r=await perform('end');if(!r?.ok)return;}await release();navigate('maintenance');notify('训练已退出，动力关闭。可按 Alt+F4 返回桌面维护。');};
$('refresh-maintenance').onclick=loadMaintenance;
$('claim').onclick=claim;
document.addEventListener('click',event=>{
  const action=event.target.closest('[data-action]');if(action)perform(action.dataset.action);
  const nav=event.target.closest('[data-nav]');if(nav)navigate(nav.dataset.nav);
  const prep=event.target.closest('[data-prepare]');if(prep){$('prepare-form').elements.activity.value=prep.dataset.prepare;formChanged();navigate('prepare');}
});
window.addEventListener('hashchange',route);
window.addEventListener('resize',()=>charts.forEach(c=>c.resize()));
window.addEventListener('keydown',e=>{if(e.key==='Escape' && !$('confirm').open && token)perform('emergency');});
window.addEventListener('beforeunload',()=>socket?.close());
formChanged();route();connect();

