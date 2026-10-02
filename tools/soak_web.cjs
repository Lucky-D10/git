// 2-hour run: FOCUS_SECONDS=7200 node tools/soak_web.cjs (simulation server only).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
// Each probe opens its own TCP connection, independent of Playwright's idle pool.
function healthProbe(url){return new Promise((resolve,reject)=>{
 const request=require('http').get(url+'/api/health',{agent:false},response=>{
  let body='';response.on('data',chunk=>body+=chunk);response.on('error',reject);
  response.on('end',()=>{try{assert.equal(response.statusCode,200);resolve(JSON.parse(body));}catch(error){reject(error);}});
 });
 request.setTimeout(2000,()=>request.destroy(new Error('Health probe timed out')));
 request.on('error',reject);
});}
(async()=>{
 const seconds=Number(process.env.FOCUS_SECONDS||7200),url=process.env.FOCUS_URL||'http://127.0.0.1:8765';
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const context=await browser.newContext({viewport:{width:800,height:480}});
 const page=await context.newPage(),errors=[],external=[],samples=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',r=>new URL(r.request().url()).origin===url?r.continue():(external.push(r.request().url()),r.abort()));
 try {
  await page.goto(url);
  const initial=await (await page.request.get(url+'/api/session')).json();
  assert.equal(initial.snapshot.mode,'simulation','This load test must not drive real hardware');
  await page.locator('#claim:not([disabled])').waitFor();await page.locator('#claim').click();
  if(['paused','running','countdown'].includes(initial.snapshot.state)){
   await page.evaluate(()=>location.hash='live');
   await page.locator('[data-action=end]').click();await page.locator('#confirm-yes').click();
   await page.waitForFunction(()=>document.querySelector('#report-status').textContent.includes('已保存'));
  }
  await page.evaluate(()=>location.hash='teacher');
  await page.locator('#teacher-form input[name=duration]').fill(String(Math.min(7200,seconds+20)));
  await page.locator('#teacher-form button.primary').click();
  await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));
  await page.evaluate(()=>location.hash='home');
  await page.locator('[data-prepare="training"]').click();
  await page.locator('[data-players="2"]').click();
  await page.locator('#choose-next').click();
  await page.locator('#prepare-submit').click();
  await page.locator('#prepare [data-action=start]:not([disabled])').waitFor();
  await page.locator('#prepare [data-action=start]').click();
  await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='进行中');
  const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
  const since=(await(await page.request.get(url+'/api/maintenance/metrics')).json()).clock;
  const started=Date.now();
  while(Date.now()-started<seconds*1000){
   await page.waitForTimeout(Math.min(5000,seconds*1000-(Date.now()-started)));
   const t=Date.now(),health=await healthProbe(url);
   assert.equal(health.ready,true);
   const perf=await cdp.send('Performance.getMetrics');
   const metrics=Object.fromEntries(perf.metrics.map(x=>[x.name,x.value]));
   samples.push({elapsed_s:(Date.now()-started)/1000,health_ms:Date.now()-t,heap_bytes:metrics.JSHeapUsedSize,nodes:metrics.Nodes,...await page.evaluate(()=>({state:document.querySelector('#state-label').textContent,charts:focusDiagnostics.charts.size,observed:focusDiagnostics.observed.size}))});
  }
  if(await page.locator('[data-action=end]').isEnabled()){
   await page.locator('[data-action=end]').click();await page.locator('#confirm-yes').click();
  }
  await page.waitForFunction(()=>document.querySelector('#report-status').textContent.includes('已保存'));
  const latency=await(await page.request.get(url+'/api/maintenance/metrics?since='+since)).json();
  // At the 7200s duration limit a final report legitimately creates two charts.
  // Compare counts within the active training phase, not across page transitions.
  const runningSamples=samples.filter(s=>s.state==='进行中');
  const stableCharts=runningSamples.length>0&&runningSamples.every(s=>s.charts===runningSamples[0].charts);
  const healthyStates=samples.every(s=>['进行中','已结束'].includes(s.state));
  const result={seconds,passed:!errors.length&&!external.length&&stableCharts&&healthyStates,errors,external,latency,samples,note:'Desktop simulation; hardware acceptance requires separate Pi measurements'};
  const out=path.resolve('reports/ui-v2');fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'soak-result.json'),JSON.stringify(result,null,2));
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  assert(stableCharts,'chart instances must remain stable across samples');
  assert(healthyStates,'training must not unexpectedly pause or abort');
  console.log(JSON.stringify({seconds,passed:true,latency,samples:samples.length,first:samples[0],last:samples.at(-1)},null,2));
 }catch(error){
  const out=path.resolve('reports/ui-v2');fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'soak-failure-'+Date.now()+'.json'),JSON.stringify({seconds,passed:false,error:String(error),errors,external,samples},null,2));
  throw error;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

