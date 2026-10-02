// Report display fixtures: read-only routes, no session/control writes.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const url=process.env.FOCUS_URL||'http://127.0.0.1:8765';
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_PATH?{executablePath:process.env.BROWSER_PATH}:{})});
 const page=await browser.newPage({viewport:{width:800,height:480}}),errors=[],writes=[];
 const out=path.resolve('reports/design-alignment');fs.mkdirSync(out,{recursive:true});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const points=Array.from({length:181},(_,t)=>{
   if((t>=40&&t<55)||(t>=95&&t<110))return [t,null,null];
   return [t,Math.max(0,Math.min(100,37+t*.17+18*Math.sin(t*.65))),37+t*.17+8*Math.sin(t*.17)];
  });
  const valid=points.slice(0,-1).filter(p=>p[1]!==null),target=valid.filter(p=>p[1]>=50).length;
  const bins=[0,0,0,0,0];valid.forEach(p=>bins[Math.min(4,Math.floor(p[1]/20))]++);
  const player={sample_count:valid.length,valid_seconds:valid.length,target_seconds:target,stable_ratio:100*target/valid.length,best_streak:17,average:valid.reduce((a,p)=>a+p[1],0)/valid.length,reference:50};
  const empty={sample_count:0,valid_seconds:0,target_seconds:0,stable_ratio:null,best_streak:0,average:null,reference:60};
  const report={status:'ready',measurement_note:'固定回放样例 · 非实测',config:{player_ids:['local-1','local-2']},base:{mode:'simulation',reason:'user_end',state:'finished',activity:'training',now:180,players:[player,empty]},charts:[{points,distribution_seconds:bins,labels:['0–<20','20–<40','40–<60','60–<80','80–100']},{points:[],distribution_seconds:[0,0,0,0,0],labels:['0–<20','20–<40','40–<60','60–<80','80–100']}],events:[{event:'state_transition',new:'running',reason:'countdown_complete',t:0},{event:'device_transition',lane:1,new:'stale',reason:'stale',t:40},{event:'device_transition',lane:1,new:'valid',t:55},{event:'state_transition',new:'paused',reason:'user_pause',t:95},{event:'state_transition',new:'running',reason:'user_resume',t:110}]};
  const rows=Array.from({length:12},(_,i)=>({session_id:'display-'+i,started_utc:new Date(Date.UTC(2026,8,20+i)).toISOString(),condition:'fixture',activity:'training',mode:'simulation',complete:true,status:i===7?'aborted':'finished',settings:{duration:180,references:[50],session_kind:'experience'},players:[{...player,player_id:'local-1',best_streak:8+i*.8,stable_ratio:45+i*2,valid_seconds:120+i*2}]})).reverse();
  await page.route('**/api/**',route=>{
   if(route.request().method()!=='GET'){writes.push(route.request().url());return route.abort();}
   const path=new URL(route.request().url()).pathname;
   if(path==='/api/sessions/display-report/report')return route.fulfill({json:{ok:true,report}});
   if(path==='/api/sessions')return route.fulfill({json:{ok:true,sessions:rows}});
   return route.continue();
  });
  report.base.reason='manual_end';report.events[3].reason='manual_pause';report.events[4].reason='countdown_complete';
  await page.goto(url+'/#report/display-report');
  await page.waitForFunction(()=>focusDiagnostics.charts.has('distribution-chart'));
  await page.evaluate(()=>{const label=document.createElement('div');label.id='fixture-label';label.textContent='固定显示样例 · 非实测';label.style.cssText='position:fixed;bottom:0;right:8px;z-index:100;font-size:9px;color:#536e94;background:#f6fbff';document.body.append(label);});
  async function check(){
   await page.waitForFunction(()=>['review-chart','distribution-chart'].every(id=>{const c=focusDiagnostics.charts.get(id),n=document.getElementById(id);return c&&n.clientWidth===c.getWidth()&&n.clientHeight===c.getHeight()&&c.getWidth()>0;}));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await check();await page.screenshot({path:path.join(out,'report-800.png'),fullPage:true});
  const review=await page.evaluate(()=>{const c=focusDiagnostics.charts.get('review-chart'),o=c.getOption();return {gaps:o.series[1].data.filter(p=>p[1]===null).length,connect:o.series[1].connectNulls,bands:o.series[1].markArea.data.length};});
  assert.deepEqual(review,{gaps:30,connect:false,bands:2});
  await page.evaluate(()=>focusDiagnostics.charts.get('review-chart').dispatchAction({type:'dataZoom',start:20,end:60}));
  await page.locator('#review-reset').click();
  assert.equal(await page.evaluate(()=>focusDiagnostics.charts.get('review-chart').getOption().dataZoom[0].start),0);
  await page.locator('#report-player').selectOption('1');
  assert(await page.evaluate(()=>['review-chart','distribution-chart'].every(id=>!focusDiagnostics.charts.get(id).getOption().graphic[0].elements.find(g=>g.id==='empty').invisible)),'empty charts explain missing data');
  await page.screenshot({path:path.join(out,'report-empty-800.png'),fullPage:true});
  // One isolated sample still has a visible point, including after a missing interval.
  await page.evaluate(async()=>{
   const charts=await import('/static/js/charts.js');
   const r={base:{now:8,players:[{reference:50}]},charts:[{points:[[0,null,null],[4,65,65],[5,null,null]]}],events:[]};
   charts.review('review-chart',r,0);const s=charts.charts.get('review-chart').getOption().series[1];
   window.singlePointVisible=s.showSymbol&&s.symbolSize([4,65],{dataIndex:1})>0;
  });assert(await page.evaluate(()=>singlePointVisible),'one sample must not render as an empty chart');
  await page.locator('#report-player').selectOption('0');
  await page.evaluate(()=>{window.originalReportChart=focusDiagnostics.charts.get('review-chart');location.hash='home';});
  await page.locator('#home:visible').waitFor();await page.evaluate(()=>location.hash='report/display-report');await page.locator('#report:visible').waitFor();await check();
  assert(await page.evaluate(()=>originalReportChart===focusDiagnostics.charts.get('review-chart')),'revisiting a report reuses its chart');
  for(const [width,height] of [[1280,800],[390,844]]){await page.setViewportSize({width,height});await check();await page.screenshot({path:path.join(out,'report-'+width+'.png'),fullPage:true});}
  await page.setViewportSize({width:800,height:480});await page.evaluate(()=>location.hash='history');await page.locator('#history-condition option').nth(1).waitFor({state:'attached'});await page.locator('#history-condition').selectOption('fixture');
  await page.screenshot({path:path.join(out,'history-800.png'),fullPage:true});
  for(const metric of ['stable_ratio','valid_seconds','best_streak']){
   await page.locator('[data-trend="'+metric+'"]').click();
   const option=await page.evaluate(()=>focusDiagnostics.charts.get('trend-chart').getOption());
   assert.equal(option.series[0].data[7],null,'interrupted record remains a gap across all metrics');
   assert.equal(option.series[0].data[0],rows.at(-1).players[0][metric]);
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(out,'report-result.json'),JSON.stringify({passed:true,errors,writes,review,checks:['both charts visible','empty state','isolated point','pause and missing gaps','zoom reset','player switching','reuse after hidden route','responsive sizing','three history metrics']},null,2));
  console.log('Report chart fixtures passed without control writes.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
