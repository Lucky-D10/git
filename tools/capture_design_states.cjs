// Visual fixtures only: intercept WebSocket data, never claim control or submit actions.
// Screenshots are explicitly marked as fixed display inputs, not device measurements.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8765';
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const context=await browser.newContext({viewport:{width:800,height:480}}),page=await context.newPage(),errors=[],controls=[],sizes=[];
 const out=path.resolve('reports/design-alignment');fs.mkdirSync(out,{recursive:true});
 let timer;
 try{
  const base=(await(await context.request.get(url+'/api/session')).json()).snapshot;
  assert.equal(base.mode,'simulation');
  const players=[0,1].map(i=>({...base.players[i],valid:true,connected:true,worn:true,calibration:'normal',reason:'valid',raw:68+i*8,smoothed:68+i*8,reference:50+i*10,current_streak:8-i*2,power:.4,position:45+i*20,sample_count:31}));
  const points=players.map((p,i)=>Array.from({length:31},(_,t)=>[t,32+t*1.2+10*Math.sin(t*1.15+i),32+t*1.2+7*Math.sin(t*1.15+i)]));
  points.forEach((lane,i)=>lane[30]=[30,players[i].raw,players[i].smoothed]);
  let state={...base,session_id:'display-fixture',activity:'training',state:'running',safety:'allowed',reason:'',duration:180,elapsed:100,now:30,distance:100,players,chart_points:points,player_ids:['local-1','local-2'],bindings:[1,2],record_incomplete:false};
  await context.route('**/api/**',route=>{if(route.request().method()==='POST'){controls.push(route.request().url());return route.abort();}return route.continue();});
  await page.routeWebSocket('**/ws',ws=>{
   ws.send(JSON.stringify({type:'hello',connection:'fixture-reader'}));
   const push=()=>ws.send(JSON.stringify({type:'snapshot',packet_id:'fixture',snapshot:state}));
   push();timer=setInterval(push,100);ws.onClose(()=>clearInterval(timer));
  });
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url+'/#live');await page.locator('.training-card').first().waitFor();
  await page.evaluate(()=>{const label=document.createElement('div');label.id='fixture-label';label.textContent='固定显示样例 · 非实测';label.style.cssText='position:fixed;bottom:0;right:8px;z-index:100;font-size:9px;color:#536e94;background:#f6fbff';document.body.append(label);});
  async function capture(name){await page.waitForTimeout(250);const size=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,overflow:[...document.querySelectorAll('#main *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1&&el.getBoundingClientRect().width).slice(0,8).map(el=>el.id||el.className)}));sizes.push({name,...size});await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});assert(size.width<=size.viewport,name+' horizontal overflow '+JSON.stringify(size));}
  await capture('duo-800');
  state={...state,players:[players[0]],chart_points:[points[0]],player_ids:['local-1'],bindings:[1]};await capture('solo-800');
  state={...state,players:[players[0],{...players[1],valid:false,reason:'stale',power:0,current_streak:0}],chart_points:[points[0],points[1].map(p=>p[0]>25?[p[0],null,null]:p)],player_ids:['local-1','local-2'],bindings:[1,2]};
  await capture('missing-lane-800');
  assert(await page.locator('.training-card.orange .signal-help').isVisible());
  assert.equal(await page.evaluate(()=>!focusDiagnostics.charts.get('gauge-1').getOption().graphic[0].elements.find(g=>g.id==='attention-pointer').invisible),false);
  state={...state,activity:'racing',players:players.map(p=>({...p,boost_active:true,boost_progress:.8}))};
  await page.waitForFunction(()=>{
   const nodes=[...document.querySelectorAll('#race-track .race-car')];
   return nodes.length===2&&nodes.every((el,i)=>Math.abs(parseFloat(el.style.transform.slice(11))-(el.parentElement.clientWidth-34-el.offsetWidth-18)*(i?.65:.45))<2);
  });
  await capture('race-800');
  await page.setViewportSize({width:1280,height:800});state={...state,activity:'training',players,chart_points:points};await capture('duo-desktop');
  assert(await page.locator('.training-card').evaluateAll(cards=>cards.every(c=>c.querySelector('.mini-plot').getBoundingClientRect().bottom<=c.getBoundingClientRect().bottom)));
  await page.setViewportSize({width:390,height:844});await capture('duo-mobile');
  state={...state,players:[players[0]],chart_points:[points[0]],player_ids:['local-1'],bindings:[1]};await capture('solo-mobile');
  for(const hash of ['teacher','maintenance','history']){await page.evaluate(h=>location.hash=h,hash);await capture(hash+'-mobile');}
  assert.deepEqual(errors,[]);assert.deepEqual(controls,[]);
  fs.writeFileSync(path.join(out,'fixtures-result.json'),JSON.stringify({passed:true,errors,controls,sizes},null,2));
  console.log('Display fixtures passed without control requests.');
 }finally{clearInterval(timer);await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
