import {escapeHtml as esc,number,describe,setHtml,setText} from './ui.js';

const states={pending:'正在整理本地分析',ai_pending:'AI 解读排队中',running:'AI 正在解读',retrying:'正在重试，先显示本地反馈',ready:'AI 解读已生成',disabled:'本地分析',not_configured:'本地分析 · 云端尚未配置',simulation_local:'模拟数据 · 本地分析',insufficient_data:'数据不足 · 基础反馈',busy_fallback:'本地分析 · 云端繁忙',fallback:'本地分析 · 云端暂不可用',not_available:'暂无分析',failed:'分析暂不可用',template:'本地分析'};
states.legacy_template='旧版记录 · 本地反馈';
const evidenceNames={quality:'有效记录',target:'本轮达标片段',level:'读数变化',segments:'前中后分段',comparison:'本次到访对照'};
export function pendingAnalysis(report){return report.analysis?.some(a=>['pending','ai_pending','running','retrying'].includes(a.ai_status));}
export function renderAnalysis(report,lane){
 const node=document.getElementById('analysis-content'),a=report.analysis?.find(a=>a.lane===lane+1);
 if(!node)return;
 document.getElementById('analysis-retry').hidden=!a||a.ai_status!=='fallback';
 if(!a?.metrics){setText('analysis-content',states[a?.ai_status]||'记录保存后会自动整理本次反馈。');return;}
 const m=a.metrics;
 setHtml('analysis-content','<p class="analysis-status">'+esc(states[a.ai_status]||a.ai_status)+' · '+(a.scope==='same_visit'?'本次到访对照':'单次体验')+'</p>'+
 '<div class="analysis-metrics"><span>有效覆盖 <b>'+number(m.coverage*100,1)+'%</b></span><span>时间加权平均 <b>'+number(m.weighted_average,1)+'</b></span><span>达标片段 <b>'+m.target_bouts+' 次</b></span></div>'+
 '<h3>本轮小结 · '+esc(a.summary)+'</h3>'+
 (a.observations?.length?'<div class="ai-explanation"><strong>AI 辅助解读</strong>'+a.observations.map(o=>'<p>'+esc(o.text)+' <small>依据：'+esc(evidenceNames[o.evidence_id]||o.evidence_id)+'</small></p>').join('')+'</div>':a.facts.map(f=>'<p data-evidence="'+esc(f.id)+'">'+esc(f.text)+'</p>').join(''))+
 (a.goal?'<section class="practice-goal"><h3>下一轮的小目标</h3><strong>'+esc(a.goal.title)+'</strong><p>'+esc(a.goal.text)+'</p><p class="goal-reason">为什么这样定：'+esc(a.goal.why)+'</p></section>':'')+
 '<h3>可以这样做</h3><ol class="practice-steps">'+a.suggestions.map(s=>'<li>'+esc(s.text)+'</li>').join('')+'</ol>'+
 (a.encouragement?'<p class="practice-encouragement"><strong>送你一句鼓励</strong><br>'+esc(a.encouragement)+'</p>':'')+
 (a.observations?.length?'<details><summary>查看解读依据</summary>'+a.facts.map(f=>'<p>'+esc(f.text)+'</p>').join('')+'</details>':'')+
 '<details><summary>分段数据与缺测原因</summary><p>'+m.segments.map((s,i)=>['前段','中段','后段'][i]+'：均值 '+number(s.average,1)+'，覆盖 '+number(s.coverage*100,1)+'%').join('；')+'</p>'+Object.entries(m.missing_seconds_by_reason).map(([k,v])=>'<p>'+esc(describe(k))+'：'+number(v,1)+' 秒</p>').join('')+'</details>'+
 a.limitations.map(t=>'<p class="fine-print">'+esc(t)+'</p>').join(''));
}
