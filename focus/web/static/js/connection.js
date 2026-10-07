import {describe} from './ui.js';
let staffToken='';
export function setStaffToken(value){staffToken=value;}
export function requestHeaders(){return {'Content-Type':'application/json','X-Focus-Client':'web',...(staffToken?{'X-Focus-Staff':staffToken}:{})};}
export async function api(url, body) {
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),4000);
 try {
  const response=await fetch(url,{method:body?'POST':'GET',headers:requestHeaders(),...(body?{body:JSON.stringify(body)}:{}),signal:controller.signal});
  const result=await response.json();
  if(!response.ok)throw new Error(describe(result.reason||result.detail||response.status));
  return result;
 }finally{clearTimeout(timer)}
}
export class Connection extends EventTarget {
 constructor(){super();this.snapshot=null;this.socket=null;this.token='';this.connection=null;this.lastSnapshot=0;this.pending=null;this.urgentPending=null;this.busy=false;this.urgentBusy=false;this.emergencyEpoch=0;this.observed=new Map();this.retryTimer=null;this.claimId=null;}
 emit(type,detail){this.dispatchEvent(new CustomEvent(type,{detail}));}
 get fresh(){return this.socket?.readyState===WebSocket.OPEN&&!!this.connection&&performance.now()-this.lastSnapshot<700;}
 get allowed(){return this.fresh&&!!this.token;}
 connect(){
  clearTimeout(this.retryTimer);
  const socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws');this.socket=socket;
  socket.onmessage=event=>{
   if(socket!==this.socket)return;
   const packet=JSON.parse(event.data);
   if(packet.type==='hello'){this.connection=packet.connection;this.claimId=crypto.randomUUID();return;}
   if(packet.type==='heartbeat'){if(!packet.ok){this.token='';this.emit('change');}return;}
   if(packet.type!=='snapshot')return;
   const previous=this.snapshot;this.snapshot=packet.snapshot;this.lastSnapshot=performance.now();
   this.emit('snapshot',{previous,packet});this.emit('change');
  };
  socket.onclose=()=>{if(socket!==this.socket)return;this.connection=null;this.token='';this.lastSnapshot=0;this.emit('change');this.retryTimer=setTimeout(()=>this.connect(),1000);};
  socket.onerror=()=>socket.close();
 }
 start(){this.connect();this.heartbeat=setInterval(()=>{if(this.allowed)this.socket.send(JSON.stringify({type:'heartbeat',token:this.token}));this.emit('change');},300);}
 async claim(){
  if(!this.fresh)throw new Error('请等待页面连接恢复');
  if(this.token)return true;
  const r=await api('/api/control/claim',{connection:this.connection,request_id:this.claimId});
  this.token=r.token;this.socket.send(JSON.stringify({type:'heartbeat',token:this.token}));this.emit('change');return true;
 }
 async release(){if(this.token)await api('/api/control/release',{token:this.token});this.token='';this.claimId=crypto.randomUUID();this.emit('change');}
 async command(action,options={},retry=false){
  if(!this.allowed)throw new Error('请接管操作并等待连接恢复');
  const urgent=action==='emergency', key=urgent?'urgentPending':'pending', busy=urgent?'urgentBusy':'busy';
  if(this[busy] || (!urgent&&this.urgentPending))return null;
  if(this[key]&&!retry)throw new Error('上一操作结果待确认，请先重试');
  if(urgent&&!retry)this.emergencyEpoch++;
  const epoch=this.emergencyEpoch;
  const envelope=retry?this[key]:{sid:this.snapshot.session_id,body:{action,request_id:crypto.randomUUID(),token:this.token,...options}};
  if(!envelope)return null;
  // An expired lease cannot execute an old operation. Fetching a snapshot is
  // sufficient to reconcile it; never resubmit with a new ID automatically.
  this[key]=envelope;this[busy]=true;this.emit('change');
  try{
   const result=await api('/api/session/'+encodeURIComponent(envelope.sid)+'/action',envelope.body);
   if(result.reason==='result_pending_retry_same_id')return result;
   this[key]=null;
   const latest=await api('/api/session');
   if(!this.snapshot||latest.snapshot.published_monotonic>=this.snapshot.published_monotonic)this.snapshot=latest.snapshot;
   if(!urgent&&epoch!==this.emergencyEpoch)return {ok:false,reason:'superseded_by_emergency'};
   return result;
  }finally{this[busy]=false;this.emit('change');}
 }
 ack(packet){
  if(!this.fresh||document.hidden)return;
  const keys=[];
  packet.snapshot.players.forEach((p,i)=>{const key=packet.snapshot.session_id+':'+i+':'+p.generation+':'+p.sequence;if(p.valid&&!this.observed.has(key)){keys.push(key);this.observed.set(key,true);if(this.observed.size>2000)this.observed.delete(this.observed.keys().next().value);}});
  if(keys.length)this.socket.send(JSON.stringify({type:'rendered',packet_id:packet.packet_id,keys}));
 }
}
