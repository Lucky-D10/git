import {finite,describe} from './ui.js';

// A view of independent backend facts, not a timed, optimistic frontend workflow.
export function deviceView(p,fresh=true){
 const connected=p.connected===true,worn=p.worn===true,calibrated=connected&&p.worn!==false&&p.calibration==='normal';
 let key='checking',title='检查设备状态',hint=describe(p.reason)||'等待设备报告状态';
 if(!fresh){key='offline';title='状态连接中断';hint='正在重连后台，恢复后重新检查设备';}
 else if(!connected){key='disconnected';title='头环未连接';hint='请打开头环并检查连接';}
 else if(p.worn===false){key='not-worn';title='已连接 · 未佩戴';hint='戴好头环，让接触点贴合额头';}
 else if(p.reason==='calibration_timeout'){key='timeout';title='基线采集超时';hint='请调整接触点，再检查设备状态';}
 else if(p.calibration==='baseline'){key='baseline';title='基线采集中';hint='保持自然、减少移动，等待设备完成校准';}
 else if(p.valid){key='ready';title='准备好了';hint='保持轻松，等待开始';}
 else if(calibrated){key='waiting-signal';title='等待有效新信号';hint=describe(p.reason)||'设备校准完成，正在等待有效样本';}
 const progress=key==='baseline'&&finite(p.calibration_progress)?Math.round(Math.max(0,Math.min(1,p.calibration_progress))*100):null;
 const facts=[
  {label:'头环连接',value:connected?'已连接':'未连接',ok:connected},
  {label:'佩戴状态',value:p.worn===true?'已佩戴':p.worn===false?'未佩戴':'设备未单独提供',ok:worn},
  {label:'设备基线',value:calibrated?'采集完成':key==='baseline'?'采集中'+(progress===null?'':' '+progress+'%'):key==='timeout'?'采集超时':'等待采集',ok:calibrated},
  {label:'有效信号',value:p.valid?'已收到':'等待新样本',ok:p.valid===true}
 ].map((f,i)=>!fresh?{...f,value:'状态待更新',ok:false}:!connected&&i>0?{...f,value:'连接后确认',ok:false}:f);
 return {key,title,hint,facts,progress,ready:fresh&&p.valid===true,wear:connected&&p.worn!==false};
}
