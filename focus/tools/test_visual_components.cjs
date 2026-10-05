// Browser rendering contracts, using fixed values and no control requests.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8765';
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const page=await browser.newPage({viewport:{width:800,height:480}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(url+'/api/health');
  await page.setContent('<html lang="zh-CN"><meta charset="utf-8"><link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/design-match.css"><link rel="stylesheet" href="/static/play-design.css"><body><main style="padding:20px"><h1 style="font-size:21px;margin-bottom:16px">指针组件验证 · 固定输入 0 / 50 / 100</h1><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px"><div id="test-0" class="card" style="height:190px"></div><div id="test-1" class="card" style="height:190px"></div><div id="test-2" class="card" style="height:190px"></div></div><div id="fixture-trend" style="height:140px;margin-top:15px"></div></main></body></html>');
  await page.addScriptTag({url:url+'/static/echarts.min.js'});
  const values=await page.evaluate(async()=>{
   const charts=await import('/static/js/charts.js');window.fixtureCharts=charts;
   [0,50,100].forEach((value,i)=>charts.gauge('test-'+i,{valid:true,smoothed:value,reference:50},i===2?1:0));
   charts.trend('fixture-trend',[[0,20,20],[5,40,35],[10,null,null],[15,80,60],[20,75,68],[25,90,78],[30,82,80]],50,0,30);
   return [0,1,2].map(i=>{const option=charts.charts.get('test-'+i).getOption();return {value:option.series[0].data[0].value,pointer:!option.graphic[0].elements.find(g=>g.id==='attention-pointer').invisible};});
  });
  assert.deepEqual(values,[{value:0,pointer:true},{value:50,pointer:true},{value:100,pointer:true}]);
  const tips=await page.evaluate(()=>[0,1,2].map(i=>{
   const c=fixtureCharts.charts.get('test-'+i),o=c.getOption();
   const pointer=o.graphic[0].elements.find(g=>g.id==='attention-pointer');
   return {x:pointer.shape.x2-o.series[0].center[0],y:pointer.shape.y2-o.series[0].center[1],type:pointer.type,zones:o.series[0].axisLine.lineStyle.color.map(v=>v[0])};
  }));
  assert(tips[0].x<0&&Math.abs(tips[0].y)<1,'zero points left');
  assert(Math.abs(tips[1].x)<1&&tips[1].y<0,'50 points up');
  assert(tips[2].x>0&&Math.abs(tips[2].y)<1,'100 points right');
  tips.forEach(t=>{assert.equal(t.type,'line');assert.deepEqual(t.zones,[.2,.7,1],'three zones stay fixed across changing values');});
  const custom=await page.evaluate(()=>{
   fixtureCharts.gauge('test-0',{valid:true,smoothed:40,reference:90},0,false,[25,80]);
   const zones=fixtureCharts.charts.get('test-0').getOption().series[0].axisLine.lineStyle.color.map(v=>v[0]);
   fixtureCharts.gauge('test-0',{valid:true,smoothed:0,reference:50});return zones;
  });assert.deepEqual(custom,[.25,.8,1],'personal goal must not change configured display bands');
  await page.waitForTimeout(250);
  const out=path.resolve('reports/ui-v2');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'gauge-pointer-states.png')});
  const missing=await page.evaluate(()=>{
   fixtureCharts.gauge('test-1',{valid:false,smoothed:null,reference:50},0);
   const option=fixtureCharts.charts.get('test-1').getOption(),gauge=option.series[0];
   const curve=fixtureCharts.charts.get('fixture-trend').getOption().series[0];
   return {pointer:!option.graphic[0].elements.find(g=>g.id==='attention-pointer').invisible,label:gauge.detail.formatter(),gap:curve.data[2][1],joinGaps:curve.connectNulls};
  });
  assert.deepEqual(missing,{pointer:false,label:'—',gap:null,joinGaps:false});
  const history=await page.evaluate(()=>{
   const player={player_id:'local-1',sample_count:20,best_streak:17};
   fixtureCharts.historyTrend('fixture-trend',[
    {started_utc:'2026-09-29T12:00:00Z',status:'finished',complete:true,players:[player]},
    {started_utc:'2026-09-29T11:00:00Z',status:'aborted',complete:true,players:[player]}
   ],'local-1');
   return fixtureCharts.charts.get('fixture-trend').getOption().series[0].data;
  });
  assert.deepEqual(history,[null,17],'saved interrupted records must not become comparable successes');
  await page.evaluate(()=>{fixtureCharts.dispose([...fixtureCharts.charts.keys()]);document.body.innerHTML='<main style="padding:20px"><h1 style="font-size:21px;margin-bottom:16px">赛车组件验证 · 固定的后台进度</h1><div id="fixture-race"></div></main>';});
  const progress=await page.evaluate(async()=>{
   const {Race}=await import('/static/js/race.js');
   window.fixtureRace=new Race(document.getElementById('fixture-race'));
   window.fixtureState={session_id:'fixture',state:'running',distance:100,players:[{valid:true,position:25,power:.6},{valid:true,position:75,power:.7}]};
   fixtureRace.update(fixtureState,['小蓝','小橙'],true,true);
   return [...document.querySelectorAll('.race-car')].map(el=>({x:parseFloat(el.style.transform.slice(11)),travel:el.parentElement.clientWidth-34-el.offsetWidth-18}));
  });
  progress.forEach((p,i)=>assert(Math.abs(p.x-p.travel*(i?.75:.25))<.01));
  const assets=await page.locator('.sports-car').evaluateAll(async images=>Promise.all(images.map(async img=>{
   await img.decode();const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;
   const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);
   return {width:img.naturalWidth,height:img.naturalHeight,cornerAlpha:ctx.getImageData(0,0,1,1).data[3],bodyAlpha:ctx.getImageData(canvas.width/2,canvas.height/2,1,1).data[3]};
  })));
  assert(assets.every(a=>a.width>0&&a.cornerAlpha===0&&a.bodyAlpha>=250),'car assets load with transparent backgrounds and solid body paint');
  assert(Math.abs(assets[0].width/assets[0].height-assets[1].width/assets[1].height)<.005,'player cars share proportions within raster rounding');
  const before=await page.locator('.race-car').evaluateAll(nodes=>nodes.map(el=>el.style.transform));
  await page.waitForTimeout(250);
  assert.deepEqual(await page.locator('.race-car').evaluateAll(nodes=>nodes.map(el=>el.style.transform)),before,'no invented progress between backend updates');
  const trails=()=>page.locator('.speed-trail').evaluateAll(nodes=>nodes.map(el=>({opacity:Number(getComputedStyle(el).opacity),width:el.getBoundingClientRect().width})));
  await page.evaluate(()=>fixtureRace.update(fixtureState,['小蓝','小橙']));
  assert((await trails()).every(t=>t.opacity===0),'ordinary driving has no exhaust');
  const strengths=[];
  for(const progress of [0,.5,1]){
   await page.evaluate(progress=>{
    Object.assign(fixtureState.players[0],{boost_active:true,boost_progress:progress});
    fixtureRace.update(fixtureState,['小蓝','小橙']);
   },progress);
   await page.waitForTimeout(150);
   const current=await trails();strengths.push(current[0]);
   assert.equal(current[1].opacity,0,'boost is lane-specific');
  }
  assert(strengths[0].opacity>0,'exhaust appears as soon as boost qualifies');
  for(let i=1;i<strengths.length;i++){
   assert(strengths[i].opacity>strengths[i-1].opacity&&strengths[i].width>strengths[i-1].width,'continuous boost increases exhaust density and length');
  }
  await page.screenshot({path:path.join(out,'race-boost-full.png')});
  await page.evaluate(()=>{fixtureState.players[0].boost_active=false;fixtureRace.update(fixtureState,['小蓝','小橙']);});
  assert.equal((await trails())[0].opacity,0,'losing boost immediately removes exhaust');
  await page.evaluate(()=>{Object.assign(fixtureState.players[0],{boost_active:true,boost_progress:0});fixtureRace.update(fixtureState,['小蓝','小橙']);});
  await page.waitForTimeout(150);
  assert.deepEqual((await trails())[0],strengths[0],'boost restarts at the weakest level');
  for(const mode of ['stale','reduced','invalid','stopped','finished']){
   await page.evaluate(mode=>{
    fixtureState.players[0].valid=mode!=='invalid';
    fixtureState.state=mode==='finished'?'finished':'running';
    fixtureRace.update(fixtureState,['小蓝','小橙'],mode==='reduced',mode!=='stale');
    if(mode==='stopped')fixtureRace.stop();
   },mode);
   assert((await trails()).every(t=>t.opacity===0),mode+' removes exhaust');
  }
  await page.evaluate(()=>{fixtureState.state='paused';fixtureRace.update(fixtureState,['小蓝','小橙']);});
  assert.equal(await page.locator('.driving').count(),0);
  assert((await trails()).every(t=>t.opacity===0),'paused cars have no exhaust');
  assert.deepEqual(await page.locator('.race-car').evaluateAll(nodes=>nodes.map(el=>el.style.transform)),before);
  await page.evaluate(()=>{fixtureState.state='running';fixtureState.players[1].valid=false;fixtureRace.update(fixtureState,['小蓝','小橙'],false,true);});
  assert.equal(await page.locator('.race-car.orange.waiting').count(),1);
  assert.equal(await page.locator('.race-car.orange.driving').count(),0);
  await page.screenshot({path:path.join(out,'race-fixed-replay.png')});
  const bootSource=fs.readFileSync('deploy/kiosk_boot.py','utf8');
  const bootHtml=bootSource.match(/HTML = '''([\s\S]*?)'''/)[1];
  // Health-check behavior is covered by Python tests; this checks the offline layout.
  await page.setContent(bootHtml.replace(/<script>[\s\S]*?<\/script>/,''));
  assert(await page.locator('footer').evaluate(el=>el.getBoundingClientRect().bottom<=480),'waiting-page footer must remain visible');
  await page.screenshot({path:path.join(out,'kiosk-wait-800x480.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'components-result.json'),JSON.stringify({passed:true,errors,assets,checks:['0/50/100 pointer and geometric direction','valid zero versus missing','curve gaps','interrupted history gaps','transparent car sprites','confirmed positions only','ordinary driving without exhaust','progressive lane-specific boost exhaust','boost reset and interruptions','paused cars','one invalid lane','offline startup layout']},null,2));
  console.log('Visual component contracts passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
