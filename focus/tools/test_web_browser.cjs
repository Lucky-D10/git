// Run against an explicitly started, isolated simulation server.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8765',out=path.resolve('reports/ui-v2');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const context=await browser.newContext({viewport:{width:800,height:480}}),page=await context.newPage(),errors=[],external=[],layoutFailures=[];
 page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',r=>new URL(r.request().url()).origin===url?r.continue():(external.push(r.request().url()),r.abort()));
 const snapshot=async()=>(await(await page.request.get(url+'/api/session')).json()).snapshot;
 async function capture(name,fit=true){
  // Let the route render and ResizeObserver update the scaled frame first.
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}));
  const overflow=fit&&(dimensions.width>800||dimensions.height>480);
  await page.screenshot({path:path.join(out,name+'-800x480.png'),fullPage:!fit||overflow});
  if(overflow)layoutFailures.push({name,...dimensions});
 }
 async function nav(hash){await page.evaluate(h=>location.hash=h,hash);await page.locator('#'+hash.split('/')[0]+':visible').waitFor();}
 async function running(){await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='进行中');}
 async function finish(){
  await page.locator('#end:not([disabled])').click();await page.locator('#confirm-yes').click();
  await page.waitForFunction(()=>!document.querySelector('#result').hidden&&document.querySelector('#report-status').textContent.includes('已保存'));
 }
 async function start(activity='training',players=1){
  await nav('home');await page.locator('[data-prepare="'+activity+'"]').click();
  if(activity==='training'){await page.locator('[data-players="'+players+'"]').click();await capture('choose');await page.locator('#choose-next').click();}
  await page.locator('#players:visible').waitFor();
  await capture('players-'+players);await page.locator('#prepare-submit:not([disabled])').click();
  await page.locator('#start:not([disabled])').waitFor();await capture('prepare-'+players);
  await page.locator('#start').click();await page.locator('#overlay-card.countdown:visible').waitFor();await capture('countdown-'+activity+'-'+players);await running();await page.waitForTimeout(1000);
 }
 try{
  await page.goto(url);await page.locator('#claim:not([disabled])').waitFor();
  const metricSince=(await(await page.request.get(url+'/api/maintenance/metrics')).json()).clock;
  let s=await snapshot();assert.equal(s.mode,'simulation');
  // Test may be rerun after an interrupted browser. Reconcile the existing session explicitly.
  await page.locator('#claim').click();
  if(s.safety==='emergency_locked'){await nav('live');await page.locator('#reset').click();await page.locator('#confirm-yes').click();await page.locator('#players:visible').waitFor();}
  else if(['running','paused','countdown'].includes(s.state)){await nav('live');await finish();}
  await nav('home');await capture('home');
  await nav('teacher');await page.locator('#teacher-form [name=duration]').fill('60');
  await page.waitForTimeout(500);assert.equal(await page.locator('#teacher-form [name=duration]').inputValue(),'60','snapshot must not replace edited form');
  await page.locator('#teacher-form button.primary').click();await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));
  await capture('teacher',false);
  assert(await page.locator('#teacher-form button.primary').evaluate(el=>el.getBoundingClientRect().bottom<=480),'save settings stays in the first screen');
  assert(await page.locator('#add-player').isDisabled(),'guest mode does not edit persistent profiles');
  await nav('maintenance');await page.locator('#maintenance-status .card').first().waitFor();await capture('maintenance',true);
  await start('training',1);await capture('training-solo');
  let sid=(await snapshot()).session_id;assert.equal((await snapshot()).players.length,1);
  await page.locator('#pause').click();await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='已暂停');await capture('paused');
  const paused=(await snapshot()).elapsed;await page.waitForTimeout(600);assert.equal((await snapshot()).elapsed,paused);
  await page.locator('#resume:not([disabled])').click();await running();
  const viewer=await context.newPage();await viewer.goto(url+'/#live');await viewer.locator('#claim:not([disabled])').waitFor();
  assert(await viewer.locator('#pause').isDisabled());await viewer.locator('#claim').click();await viewer.waitForTimeout(300);assert(await viewer.locator('#pause').isDisabled());await viewer.close();
  // Refresh must retain the session, pause the output and require an explicit reclaim/resume.
  await page.reload();await page.locator('#claim:not([disabled])').waitFor();await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='已暂停');
  assert.equal((await snapshot()).session_id,sid);assert((await snapshot()).players.every(p=>p.power===0));await capture('reconnected');
  await page.locator('#claim').click();await page.locator('#resume:not([disabled])').click();await running();
  await finish();await capture('result-solo');
  const stored=(await(await page.request.get(url+'/api/sessions/'+sid+'/report')).json()).report;assert.equal(stored.status,'ready');
  await page.locator('#details-link').click();await page.locator('#export:not([disabled])').waitFor();await capture('report',false);
  assert(await page.locator('#distribution-chart').isVisible(),'time distribution is visible without an extra expansion');
  assert(await page.evaluate(()=>['review-chart','distribution-chart'].every(id=>{const c=focusDiagnostics.charts.get(id),n=document.getElementById(id);return c&&c.getWidth()===n.clientWidth&&c.getHeight()>0;})),'both saved-report charts have usable dimensions');
  await page.locator('#export').click();await page.locator('#downloads a').first().waitFor();
  const download=await page.request.get(new URL(await page.locator('#downloads a').first().getAttribute('href'),url).href);assert.equal(download.status(),200);
  await nav('history');await page.locator('#history-condition option').nth(1).waitFor({state:'attached'});
  await page.locator('#history-player').selectOption((await snapshot()).player_ids[0]);
  await page.locator('#history-condition').selectOption({index:1});await capture('history',false);
  await page.locator('[data-trend="stable_ratio"]').click();
  assert.equal(await page.evaluate(()=>focusDiagnostics.charts.get('trend-chart').getOption().yAxis[0].max),100);
  await page.locator('[data-trend="valid_seconds"]').click();await page.locator('[data-trend="best_streak"]').click();
  await start('training',2);await capture('training-duo');assert.equal((await snapshot()).players.length,2);
  assert(await page.locator('.training-card').evaluateAll(cards=>cards.every(card=>card.querySelector('.mini-plot').getBoundingClientRect().bottom<=card.getBoundingClientRect().bottom)),'dual charts must stay inside their cards');
  const chartCount=await page.evaluate(()=>focusDiagnostics.charts.size);await page.waitForTimeout(1200);assert.equal(await page.evaluate(()=>focusDiagnostics.charts.size),chartCount,'reuse chart instances');
  await finish();await capture('result-duo');
  await start('racing',2);await capture('racing');
  // Low readings correctly leave a car stopped. Compare both displayed positions
  // with the backend instead of requiring one particular lane to move immediately.
  await page.waitForTimeout(700);
  const raceSnapshot=await snapshot();
  const displayed=await page.locator('#race-track .race-car').evaluateAll(nodes=>nodes.map(el=>({x:parseFloat(el.style.transform.slice(11)),travel:el.parentElement.clientWidth-34-el.offsetWidth-18})));
  displayed.forEach((car,i)=>assert(Math.abs(car.x-car.travel*raceSnapshot.players[i].position/raceSnapshot.distance)<8,'car must follow confirmed backend progress'));
  await finish();await capture('result-race');
  const raceReport=(await(await page.request.get(url+'/api/sessions/'+raceSnapshot.session_id+'/report')).json()).report.base;
  const finalCars=await page.locator('#result-race .race-car').evaluateAll(nodes=>nodes.map(el=>({x:parseFloat(el.style.transform.slice(11)),travel:el.parentElement.clientWidth-34-el.offsetWidth-18})));
  finalCars.forEach((car,i)=>assert(Math.abs(car.x-car.travel*raceReport.players[i].position/raceReport.distance)<1,'result uses recorded virtual positions'));
  await start('racing',2);
  // Hold a normal response while the emergency request is sent independently.
  let release,held;const gate=new Promise(r=>release=r),arrived=new Promise(r=>held=r);
  await page.route('**/api/session/*/action',async route=>{
   if(route.request().postDataJSON().action==='pause'){const response=await route.fetch();held();await gate;await route.fulfill({response});}
   else await route.continue();
  });
  await page.locator('#pause').click();await arrived;
  assert(await page.locator('#emergency').isEnabled(),'pending normal action must not disable emergency');
  await page.locator('#emergency').click();await page.waitForFunction(()=>document.querySelector('#overlay-title').textContent.includes('已急停'));
  assert.equal((await snapshot()).safety,'emergency_locked');assert((await snapshot()).players.every(p=>p.power===0));await capture('emergency');release();
  await page.waitForTimeout(200);await page.unroute('**/api/session/*/action');
  await page.locator('#reset:not([disabled])').click();await page.locator('#confirm-yes').click();
  await page.locator('#players:visible').waitFor();assert.equal((await snapshot()).safety,'inhibited');assert.equal((await snapshot()).state,'aborted');
  await nav('home');await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'home-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=390),'mobile horizontal overflow');
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(layoutFailures,[],'core pages must fit 800x480');
  const metrics=await(await page.request.get(url+'/api/maintenance/metrics?since='+metricSince)).json();
  fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:true,errors,external,metrics,scenarios:['solo','duo','race','pause/resume','refresh','readonly','teacher presets','profiles','history','export','emergency during pending request','reset','800x480','mobile']},null,2));
  console.log(JSON.stringify({passed:true,errors,external,metrics},null,2));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});fs.writeFileSync(path.join(out,'browser-failure.json'),JSON.stringify({error:String(e),errors,external,layoutFailures},null,2));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

