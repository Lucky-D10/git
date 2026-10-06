// Run against an isolated simulation server with FOCUS_STAFF_PIN=guest-test-pin.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8767';
 const out=path.resolve('reports/guest-qa');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const context=await browser.newContext({viewport:{width:800,height:480}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
 const snapshot=async()=>(await(await page.request.get(url+'/api/session')).json()).snapshot;
 const nav=async hash=>{await page.evaluate(h=>location.hash=h,hash);await page.locator('#'+hash.split('/')[0]+':visible').waitFor();};
 const screenshot=async name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
 async function startPrepared(){
  await page.locator('#prepare-submit:not([disabled])').click();
  await page.locator('#start:not([disabled])').click();
  await page.waitForFunction(()=>!document.querySelector('#result').hidden&&document.querySelector('#report-status').textContent.includes('已保存'),{},{timeout:22000});
 }
 try{
  await page.goto(url);await page.locator('#claim:not([disabled])').click();
  const initial=await snapshot();
  if(['running','paused','countdown'].includes(initial.state)){
   await nav('live');await page.locator('#end:not([disabled])').click();await page.locator('#confirm-yes').click();await page.locator('#result:visible').waitFor();
  }
  await nav('teacher');await page.locator('#teacher-form [name=duration]').fill('12');await page.locator('#teacher-form button.primary').click();
  await page.waitForFunction(()=>document.querySelector('#settings-status').textContent.includes('已保存'));
  await nav('home');await page.locator('[data-prepare="training"]').click();await page.locator('#choose-next').click();
  assert.equal(await page.locator('#draft-player-0').inputValue(),'0');await screenshot('01-new-guest');
  await startPrepared();const first=await snapshot();
  assert(first.player_ids[0].startsWith('guest-'));await screenshot('02-result');
  await page.locator('#details-link').click();await page.waitForFunction(()=>document.querySelector('#analysis-content').textContent.includes('时间加权平均'));
  assert((await page.locator('#analysis-content').innerText()).includes('模拟数据'));await screenshot('03-analysis');
  assert((await page.locator('.practice-goal').innerText()).includes('下一轮的小目标'));
  assert(await page.locator('.practice-steps li').count()>=2);
  assert((await page.locator('.practice-encouragement').innerText()).includes('鼓励'));
  const r=(await(await page.request.get(url+'/api/sessions/'+first.session_id+'/report')).json()).report;
  assert.equal(r.analysis[0].scope,'single_session');assert(r.analysis[0].eligible);
  await page.reload();await page.locator('#claim:not([disabled])').click();await page.locator('#analysis-content .analysis-metrics').waitFor();
  await page.locator('#report-back').click();await page.locator('#again').click();await page.locator('#choose-next').click();
  assert.equal(await page.locator('#draft-player-0').inputValue(),'1');await startPrepared();const second=await snapshot();
  assert.equal(first.visit_ids[0],second.visit_ids[0]);assert.notEqual(first.participant_ids[0],second.participant_ids[0]);
  await page.locator('#details-link').click();await page.waitForFunction(()=>document.querySelector('#analysis-content').textContent.includes('本次到访对照'));
  await screenshot('04-same-visit');
  await page.locator('#report-back').click();await page.locator('#next-visitor').click();await page.locator('#home:visible').waitFor();
  assert.equal((await page.request.get(url+'/api/sessions/'+first.session_id+'/report')).status(),403);
  assert.equal((await page.request.get(url+'/api/sessions')).status(),200);
  assert.equal((await(await page.request.get(url+'/api/sessions')).json()).sessions.length,0);
  await nav('report/'+first.session_id);await page.waitForFunction(()=>document.querySelector('#detail-status').textContent.includes('不属于'));
  assert.equal(await page.locator('#analysis-content').innerText(),'');
  await nav('home');await page.locator('[data-prepare="racing"]').click();await page.locator('#prepare-submit:not([disabled])').click();
  await page.locator('#prepare:visible').waitFor();const third=await snapshot();assert.equal(third.players.length,2);assert(!third.visit_ids.includes(first.visit_ids[0]));
  await page.locator('#start:not([disabled])').click();await page.waitForFunction(()=>document.querySelector('#state-label').textContent==='进行中');
  await page.locator('#end:not([disabled])').click();await page.locator('#confirm-yes').click();
  await page.waitForFunction(sid=>!document.querySelector('#result').hidden&&document.querySelector('#report-status').textContent.includes('已保存')&&document.querySelector('#details-link').getAttribute('href')==='#report/'+sid,third.session_id);
  await page.locator('#details-link').click();await page.locator('#analysis-content .analysis-metrics').waitFor();
  await page.locator('#report-player').selectOption('1');assert((await page.locator('#analysis-content').innerText()).includes('数据不足'));
  assert((await page.locator('.practice-goal').innerText()).includes('不追求更高读数'));
  await screenshot('05-dual-report');
  await nav('history');await page.locator('.staff-unlock:visible').click();await page.locator('#staff-pin').fill('wrong');await page.locator('#staff-unlock-form button.primary').click();
  await page.waitForFunction(()=>document.querySelector('#staff-error').textContent.includes('错误'));
  await page.locator('#staff-pin').fill('guest-test-pin');await page.locator('#staff-unlock-form button.primary').click();
  await page.waitForFunction(()=>!document.querySelector('#staff-dialog').open);
  await page.waitForFunction(()=>document.querySelectorAll('#history-list .record').length>=3);await screenshot('06-staff-history');
  await nav('home');await page.locator('[data-prepare="training"]').click();await page.locator('#choose-next').click();
  await page.locator('#prepare-submit:not([disabled])').click();
  await page.locator('#prepare:visible').waitFor();
  assert.equal((await page.request.get(url+'/api/sessions/'+first.session_id+'/report')).status(),403);
  await page.setViewportSize({width:390,height:844});await screenshot('07-mobile-prepare');
 }finally{
  await screenshot('last-state');await browser.close();
  fs.writeFileSync(path.join(out,'browser-errors.json'),JSON.stringify(errors,null,2));
 }
 assert.deepEqual(errors,[]);console.log('Guest browser acceptance passed');
})().catch(e=>{console.error(e);process.exit(1);});
