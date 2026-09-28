// 2-hour run: FOCUS_SECONDS=7200 node tools/soak_web.cjs (simulation server only).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
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
   await page.locator('nav a[href="#live"]').click();
   await page.locator('[data-action=end]').click();await page.locator('#confirm-yes').click();
   await page.waitForFunction(()=>document.querySelector('#report-status').textContent.includes('已完整保存'));
   await page.locator('nav a[href="#home"]').click();
  }
  await page.locator('[data-prepare="training"]').click();
  await page.locator('input[name=duration]').fill(String(Math.min(7200,seconds+20)));
  await page.locator('#prepare-form button').click();
  await page.locator('#prepare [data-action=start]:not([disabled])').waitFor();
  await page.locator('#prepare [data-action=start]').click();
  await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='进行中');
  const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
  const since=(await(await page.request.get(url+'/api/maintenance/metrics')).json()).clock;
  const started=Date.now();
  while(Date.now()-started<seconds*1000){
   await page.waitForTimeout(Math.min(5000,seconds*1000-(Date.now()-started)));
   // Avoid polling exactly on Uvicorn's 5s idle keep-alive expiry using a stale socket.
   const t=Date.now(),health=await (await page.request.get(url+'/api/health',{headers:{Connection:'close'}})).json();
   assert.equal(health.ready,true);
   const perf=await cdp.send('Performance.getMetrics');
   const metrics=Object.fromEntries(perf.metrics.map(x=>[x.name,x.value]));
   samples.push({elapsed_s:(Date.now()-started)/1000,health_ms:Date.now()-t,heap_bytes:metrics.JSHeapUsedSize,nodes:metrics.Nodes,...await page.evaluate(()=>({charts:focusDiagnostics.charts.size,observed:focusDiagnostics.observed.size}))});
  }
  await page.locator('[data-action=end]').click();await page.locator('#confirm-yes').click();
  await page.waitForFunction(()=>document.querySelector('#report-status').textContent.includes('已完整保存'));
  const latency=await(await page.request.get(url+'/api/maintenance/metrics?since='+since)).json();
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  assert(samples.every(s=>s.charts===1),'chart instances must remain stable');
  const result={seconds,passed:true,errors,external,latency,samples,note:'Desktop simulation; not Pi cold boot or 2-hour acceptance unless seconds >= 7200'};
  const out=path.resolve('reports/stage3');fs.mkdirSync(out,{recursive:true});
  fs.writeFileSync(path.join(out,'soak-result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({seconds,passed:true,latency,samples:samples.length,first:samples[0],last:samples.at(-1)},null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

