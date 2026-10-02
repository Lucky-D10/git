// No device/control writes: snapshots exercise real UI state and layout branches.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8765',out=path.resolve('reports/global-layout');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const page=await browser.newPage({viewport:{width:800,height:480}}),errors=[],writes=[],screens=[];let timer;
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const base=(await(await page.request.get(url+'/api/session')).json()).snapshot;
  assert.equal(base.mode,'simulation');
  const ready={...base.players[0],valid:true,connected:true,worn:true,calibration:'normal',calibration_progress:1,reason:'valid',power:0,reference:50,smoothed:68};
  let state={...base,session_id:'preparation-fixture',state:'preparing',safety:'inhibited',duration:180,activity:'training',players:[ready,ready],player_ids:['local-1','local-2'],bindings:[1,2]};
  await page.route('**/api/**',r=>{if(r.request().method()!=='GET'){writes.push(r.request().url());return r.abort();}return r.continue();});
  await page.routeWebSocket('**/ws',ws=>{ws.send(JSON.stringify({type:'hello',connection:'fixture-reader'}));const push=()=>ws.send(JSON.stringify({type:'snapshot',packet_id:'fixture',snapshot:state}));push();timer=setInterval(push,100);ws.onClose(()=>clearInterval(timer));});
  await page.goto(url+'/#prepare');await page.locator('[data-device-state="ready"]').first().waitFor();
  await page.evaluate(()=>{const label=document.createElement('div');label.textContent='固定状态回放 · 非实机采集';label.style.cssText='position:fixed;bottom:0;right:8px;z-index:100;font-size:10px;color:#637d9e;background:#f6fbff';document.body.append(label);});
  const cases=[
   ['disconnected',{connected:false,worn:false,calibration:'off',valid:false,reason:'not_connected'},'头环未连接'],
   ['not-worn',{connected:true,worn:false,calibration:'off',valid:false,reason:'not_worn'},'未佩戴'],
   ['baseline',{connected:true,worn:true,calibration:'baseline',calibration_progress:.37,valid:false,reason:'calibrating'},'基线采集中'],
   ['timeout',{connected:true,worn:true,calibration:'baseline',valid:false,reason:'calibration_timeout'},'基线采集超时'],
   ['waiting-signal',{connected:true,worn:true,calibration:'normal',valid:false,reason:'stale'},'等待有效新信号'],
   ['ready',{},'准备好了']
  ];
  for(const [key,overrides,text] of cases){state={...state,players:[{...ready,...overrides},ready]};await page.locator('.device-card').first().locator('[role="status"]').filter({hasText:text}).waitFor();assert.equal(await page.locator('.device-card').first().getAttribute('data-device-state'),key);assert.equal(await page.locator('.device-card').nth(1).getAttribute('data-device-state'),'ready','each lane progresses independently');if(key!=='ready')assert(await page.locator('#start').isDisabled());}
  state={...state,players:[{...ready,valid:false,calibration:'baseline',calibration_progress:.37,reason:'calibrating'},{...ready,valid:false,worn:false,calibration:'off',reason:'not_worn'}]};
  await page.locator('[data-device-state="baseline"]').waitFor();assert.equal(await page.locator('progress').getAttribute('value'),'37');
  async function capture(name,fit=true){
   await page.waitForTimeout(220);const sizes=await page.evaluate(()=>{const r=document.getElementById('app-shell').getBoundingClientRect();return {w:innerWidth,h:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,scale:focusLayout.scale,frame:[r.x,r.y,r.width,r.height]};});screens.push({name,...sizes});
   await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});assert(sizes.scrollWidth<=sizes.w,name+' horizontal overflow');if(fit)assert(sizes.scrollHeight<=sizes.h+1,name+' vertical overflow '+JSON.stringify(sizes));
  }
  for(const [w,h] of [[800,480],[1024,600],[1280,800],[1920,1080]]){await page.setViewportSize({width:w,height:h});await capture('prepare-duo-'+w);}
  state={...state,players:[{...ready,valid:false,calibration:'baseline',calibration_progress:null,reason:'calibrating'}],player_ids:['local-1'],bindings:[1]};await page.setViewportSize({width:800,height:480});await page.locator('#devices.single').waitFor();
  assert.equal(await page.locator('progress').getAttribute('value'),null,'unknown progress must not invent a percentage');await capture('prepare-single-800');
  const stale=await page.evaluate(async()=>{const {deviceView}=await import('/static/js/device-state.js');return deviceView({valid:true,connected:true,worn:true,calibration:'normal'},false);});assert.equal(stale.ready,false);assert(stale.facts.every(f=>!f.ok));
  await page.setViewportSize({width:390,height:844});await capture('prepare-phone',false);
  state={...state,players:[ready,ready],player_ids:['local-1','local-2'],bindings:[1,2],state:'running',safety:'allowed',duration:180,elapsed:30,now:30,chart_points:[[[0,45,45],[10,55,50],[20,70,65],[30,70,68]],[[0,40,40],[10,50,48],[20,70,66],[30,70,68]]]};
  await page.setViewportSize({width:1920,height:1080});await page.evaluate(()=>location.hash='live');await page.locator('#gauge-0').waitFor();await capture('training-desktop-1920');
  const pixels=await page.locator('#gauge-0 canvas').evaluate(canvas=>({pixels:canvas.width,width:canvas.getBoundingClientRect().width}));assert(pixels.pixels>=pixels.width-2,'canvas density follows proportional enlargement');
  await page.evaluate(()=>document.getElementById('confirm').showModal());
  const dialog=await page.locator('#confirm').boundingBox();assert(Math.abs(dialog.x+dialog.width/2-960)<2,'desktop dialog stays centered');assert(dialog.y>=0&&dialog.y+dialog.height<=1080);await page.screenshot({path:path.join(out,'dialog-desktop.png')});await page.evaluate(()=>document.getElementById('confirm').close());
  await page.setViewportSize({width:800,height:480});await capture('training-pi-800');
  for(const [w,h] of [[800,480],[1920,1080]]){await page.setViewportSize({width:w,height:h});await page.evaluate(()=>location.hash='home');await capture('home-'+w);}
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,errors,writes,screens,pixels},null,2));console.log('Responsive frame and independent preparation states passed.');
 }finally{clearInterval(timer);await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
