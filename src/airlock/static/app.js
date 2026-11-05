'use strict';
const $ = s => document.querySelector(s);
const state = {csrf: '', memories: [], proposals: [], busy: false, editId: null, forgetId: null};
function el(tag, cls, text) {const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n;}
function banner(message = '') {$('#banner').textContent = message; $('#banner').hidden = !message;}
let localSessionRefresh = null;
async function refreshLocalSession() {
  if (!localSessionRefresh) localSessionRefresh = (async () => {
    const options = {credentials:'same-origin', cache:'no-store'};
    let response = await fetch('/api/session', options);
    if (response.status === 401) {
      // Use the normal local landing page to renew an expired browser session.
      const landing = await fetch('/', options);
      if (!landing.ok) throw new Error('Refresh Airlock to restart your local session.');
      response = await fetch('/api/session', options);
    }
    if (!response.ok) throw new Error('Refresh Airlock to restart your local session.');
    state.csrf = (await response.json()).csrf;
  })().finally(() => {localSessionRefresh = null;});
  return localSessionRefresh;
}
async function api(path, method = 'GET', body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const options = {method, credentials:'same-origin', headers:{}};
    if (method !== 'GET') {options.headers = {'Content-Type':'application/json', 'X-Airlock-CSRF':state.csrf}; options.body = JSON.stringify(body ?? {});}
    const response = await fetch(path, options); const data = await response.json();
    // Only these middleware rejections are guaranteed to precede any action.
    // Never replay network errors, handler failures, or origin violations.
    if (attempt === 0 && ((response.status === 401 && data.code === 'local_session_expired') ||
        (response.status === 403 && data.code === 'local_csrf_changed'))) {
      await refreshLocalSession();
      continue;
    }
    if (!response.ok && !data.answer) throw new Error(data.detail || 'The local request failed.');
    return data;
  }
}
function view(name) {
  const settingsPage = ['models','sources','activity','connections'].includes(name) ? name : null;
  if(settingsPage) name='settings';
  if(['connector','releases'].includes(name)) name='sharing';
  for(const v of ['chat','memory','calendar','agents','todos','contacts','sharing','settings','company']) $(`#${v}-view`).hidden=v!==name;
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  $('#view-title').textContent=({todos:'To-dos',settings:'Settings & Activity',company:'Company memory'})[name]||name[0].toUpperCase()+name.slice(1);
  const refresh={company:refreshCompany,contacts:refreshContacts,todos:refreshTodos,sharing:refreshSharing,calendar:refreshCalendar,agents:refreshRuns};
  if(name==='chat'&&!state.busy) refreshFeed().catch(e=>banner(e.message));
  if(name==='settings') showSettings(settingsPage||settingsSection);
  else if(refresh[name]) refresh[name]().catch(e=>banner(e.message));
}
function setBusy(value) {state.busy=value; $('#upload-document').disabled=value; $('#send').disabled=value; $('#thinking').hidden=!value; $('#message').disabled=value;$('#chat-local-only').disabled=value; $('#feed-acknowledge-all').disabled=value;$('#feed-history').disabled=value;$('#feed-latest').disabled=value;document.querySelectorAll('.message-acknowledge-button').forEach(b=>b.disabled=value);}
function button(text, action, cls='') {const b=el('button',cls,text);b.type='button';b.addEventListener('click',()=>Promise.resolve().then(action).catch(e=>banner(e.message)));return b;}
const feedState = {history: false, items: [], next: null, generation: 0, signature: '', browsingOlder: false};
async function refreshFeed(older=false, force=false) {
  const generation=++feedState.generation;
  const params=new URLSearchParams({acknowledged:String(feedState.history)});
  if(older && feedState.next) for(const [k,v] of Object.entries(feedState.next)) params.set(k,v);
  const data=await api('/api/feed?'+params);
  if(generation!==feedState.generation)return;
  // Do not replace a pending user message if a background refresh finishes during inference.
  if(state.busy&&!force)return;
  feedState.browsingOlder=older;
  const items=older?[...data.items,...feedState.items]:data.items;
  feedState.items=[...new Map(items.map(i=>[i.key,i])).values()];feedState.next=data.next;
  const signature=JSON.stringify([feedState.items,feedState.next,feedState.history]);
  if(signature!==feedState.signature){
    const list=$('#transcript'), previousHeight=list.scrollHeight, previousTop=list.scrollTop;
    const atBottom=previousHeight-previousTop-list.clientHeight<80;
    renderMessages(feedState.items);
    if(older)list.scrollTop=list.scrollHeight-previousHeight+previousTop;
    else if(!atBottom)list.scrollTop=previousTop;
    feedState.signature=signature;
  }
  $('#feed-acknowledge-all').hidden=feedState.history||feedState.browsingOlder||!feedState.items.length;
  $('#feed-latest').hidden=!feedState.browsingOlder;
  $('#feed-status').hidden=true;
}
async function acknowledgeItem(item) {
  if(state.busy)return;
  await api(`/api/feed/${encodeURIComponent(item.key)}/acknowledge`,'POST');
  feedState.signature='';await refreshFeed();
}
async function showMessageSource(conversationId, messageId) {
  const message=await api(`/api/messages/${messageId}`);
  $('#detail-content').textContent=message?.content||'Source message is unavailable.';
  $('#details').showModal();
}
function renderMessages(messages) {
  const list=$('#transcript');list.replaceChildren();
  if(feedState.next)list.append(button('Load older',()=>refreshFeed(true),'text-button load-older'));
  for(const m of messages) {const item=el('article',`message ${m.role} ${m.metadata?.failed?'failed':''}`);item.id=`message-${m.id}`; const head=el('div','message-header');head.append(el('span','avatar',m.role==='user'?'Y':'a'),el('span','',m.role==='user'?'You':m.role==='notification'?'Airlock · Update':'Airlock'));if(m.created_at){const time=el('time','message-time',new Date(m.created_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}));time.dateTime=m.created_at;head.append(time);}item.append(head,el('div','message-text',m.content));if(m.metadata?.research_steps?.length)item.append(researchDetails(m.metadata.research_steps));if(m.key&&!m.acknowledged&&m.role!=='user')item.append(button('Acknowledge',()=>acknowledgeItem(m),'message-acknowledge-button'));if(m.metadata?.view)item.append(button('Review',()=>view(m.metadata.view),'report-button'));if(m.metadata?.report_id)item.append(button('View action details',()=>showReport(m.metadata.report_id),'report-button'));if(m.metadata?.source_refs){const refs=el('div','source-citations');for(const source of [...new Map(m.metadata.source_refs.map(s=>[s.id,s])).values()])refs.append(button('Source: '+source.title,()=>showSource(source.id),'text-button'));item.append(refs);}if(m.metadata?.company_restricted)item.append(el('p','muted','Company context · acknowledge this exchange before local actions'));if(m.metadata?.company_refs?.length){item.append(el('p','muted','Company sources: '+m.metadata.company_refs.map(s=>s.title).join(' · ')));}if(m.metadata?.company_truncated)item.append(el('p','muted','Company research reached a catalog or evidence limit. Coverage may be incomplete.'));if(m.metadata?.indexing_status==='failed')item.append(el('p','muted','Message saved; source indexing failed. Retry in Sources.'));list.append(item);}
  document.querySelectorAll('.message-acknowledge-button').forEach(b=>b.disabled=state.busy);
  if(!messages.length) list.append(feedState.history?el('div','empty-card','No acknowledged messages yet.'):welcome.cloneNode(true));
  list.scrollTop=list.scrollHeight;
}
const welcome=$('#welcome').cloneNode(true);
async function showReport(id) {const report=await api(`/api/reports/${id}`);$('#detail-content').textContent=JSON.stringify(report.structured_data,null,2);$('#details').showModal();}
function memoryCard(m, preview=false) {
  const card=el('article','memory-card');card.append(el('span','memory-type',m.memory_type.replaceAll('_',' ')),el('h3','',m.title),el('p','',m.content));
  if(!preview){const actions=el('div','card-actions');actions.append(button('Edit',()=>editMemory(m)));
    const source=m.source_refs.find(s=>s.conversation_id);if(source)actions.append(button('View source',()=>showMessageSource(source.conversation_id,source.id)));
    else actions.append(el('span','memory-type','Local editor'));
    actions.append(button('Forget',()=>{state.forgetId=m.id;$('#forget-title').textContent=m.title;$('#forget-dialog').showModal();}));card.append(actions);}
  return card;
}
async function refreshMemory() {
  [state.memories,state.proposals]=await Promise.all([api('/api/memories'),api('/api/proposals')]);
  $('#nav-count').textContent=state.memories.length;
  $('#memory-preview').replaceChildren(...state.memories.slice(0,4).map(m=>memoryCard(m,true)));
  $('#memory-list').replaceChildren(...state.memories.map(m=>memoryCard(m)));
  if(!state.memories.length){$('#memory-preview').append(el('div','empty-card','Nothing saved yet. Ask Airlock to remember something, or add a memory yourself.'));$('#memory-list').append(el('div','empty-card','Your active memories will appear here. Start with a small, useful fact.'));}
  $('#pending-summary').hidden=!state.proposals.length;$('#pending-summary').replaceChildren();if(state.proposals.length)$('#pending-summary').append(button(`${state.proposals.length} awaiting your approval →`,()=>view('memory'),'approval-hint'));
  $('#proposals').replaceChildren();
  for(const p of state.proposals){const card=el('article','proposal');card.append(el('span','eyebrow','AWAITING YOUR APPROVAL'),el('h3','',p.title),el('p','',p.content));const actions=el('div','proposal-actions');for(const decision of ['approve','reject'])actions.append(button(decision==='approve'?'Approve memory':'Reject',async()=>{await api(`/api/proposals/${p.id}/${decision}`,'POST');await refreshMemory();},decision==='approve'?'primary':'secondary'));card.append(actions);$('#proposals').append(card);}
}
function editMemory(memory=null){state.editId=memory?.id??null;$('#editor-title').textContent=memory?'Edit memory':'Add memory';$('#memory-title').value=memory?.title??'';$('#memory-content').value=memory?.content??'';$('#memory-type').value=memory?.memory_type??'fact';$('#memory-review').checked=memory?.impact_level==='very_high';$('#editor-error').textContent='';$('#editor').showModal();$('#memory-title').focus();}
$('#memory-form').addEventListener('submit',async e=>{e.preventDefault();$('#save-memory').disabled=true;try{await api(state.editId?`/api/memories/${state.editId}`:'/api/memories',state.editId?'PATCH':'POST',{title:$('#memory-title').value,content:$('#memory-content').value,memory_type:$('#memory-type').value,impact_level:$('#memory-review').checked?'very_high':'low'});$('#editor').close();await refreshMemory();}catch(err){$('#editor-error').textContent=err.message;}finally{$('#save-memory').disabled=false;}});
$('#confirm-forget').addEventListener('click',async()=>{const b=$('#confirm-forget');b.disabled=true;try{await api(`/api/memories/${state.forgetId}`,'DELETE');$('#forget-dialog').close();await refreshMemory();}catch(e){banner(e.message);}finally{b.disabled=false;}});
function activityLabel(tool){
 const names={'google.credentials.status':'Checked Google connection','exchange.inbox.ack':'Confirmed incoming availability','exchange.inbox':'Checked incoming availability','exchange.publish':'Delivered approved update','exchange.seal':'Prepared approved update','ollama.list_models':'Listed local models','ollama.check_models':'Checked local model','ollama.chat':'Generated reply','ollama.embed':'Embedded memory','ollama.embed_query':'Searched memory','ollama.embed_source':'Indexed source passage','ollama.embed_source_query':'Searched sources','release.preview':'Updated sharing preview','release.policy.save':'Saved sharing rules','knowledge.index':'Indexed source','knowledge.retrieve':'Retrieved source context','contact.retrieve':'Retrieved contacts','calendar.retrieve':'Retrieved calendar','todo.retrieve':'Retrieved to-dos','memory.retrieve':'Retrieved memories','document.extract':'Read document'};
 return names[tool]||tool.replaceAll('.',' · ').replaceAll('_',' ');
}
async function refreshActivity(){const rows=await api('/api/activity');$('#activity-list').replaceChildren(...rows.map(r=>{const line=el('div','activity-row');line.append(el('span','',activityLabel(r.tool)),el('span','',r.status),el('time','',new Date(r.created_at).toLocaleString()));return line;}));if(!rows.length)$('#activity-list').append(el('div','empty-card','Local activity will appear here as you use Airlock.'));}
$('#chat-form').addEventListener('submit',async e=>{e.preventDefault();if(state.busy)return;const message=$('#message').value.trim();if(!message)return;const requestId=crypto.randomUUID();setBusy(true);startChatProgress(requestId);banner();$('#welcome')?.remove();const pending=el('article','message user');pending.append(el('div','message-header','You'),el('div','message-text',message));$('#transcript').append(pending);$('#transcript').scrollTop=$('#transcript').scrollHeight;$('#message').value='';try{await api('/api/chat','POST',{message,request_id:requestId,local_only:$('#chat-local-only').checked,attachment_ids:chatAttachments.map(a=>a.id)});chatAttachments=[];renderAttachments();feedState.history=false;$('#feed-history').setAttribute('aria-pressed','false');$('#feed-label').textContent='Your assistant';await Promise.all([refreshFeed(false,true),refreshMemory()]);}catch(err){banner(err.message);$('#message').value=message;pending.remove();}finally{stopChatProgress();setBusy(false);$('#message').focus();}});
$('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#chat-form').requestSubmit();}});
document.addEventListener('click',e=>{const starter=e.target.closest('[data-prompt]');if(starter){$('#message').value=starter.dataset.prompt;$('#message').focus();}const closer=e.target.closest('.close-dialog');if(closer)closer.closest('dialog').close();});
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
$('#open-memory').addEventListener('click',()=>view('memory'));$('#add-memory').addEventListener('click',()=>editMemory());$('#refresh-activity').addEventListener('click',()=>refreshActivity().catch(e=>banner(e.message)));
$('#feed-latest').addEventListener('click',()=>refreshFeed().catch(e=>banner(e.message)));
$('#feed-acknowledge-all').addEventListener('click',async()=>{
  if(state.busy||feedState.history||!feedState.items.length)return;
  const keys=feedState.items.slice(-60).map(i=>i.key);
  setBusy(true);
  try{await api('/api/feed/acknowledge','POST',{keys});await refreshFeed(false,true);}
  catch(e){banner(e.message);}finally{setBusy(false);}
});
$('#feed-history').addEventListener('click',async()=>{
  if(state.busy)return;
  feedState.history=!feedState.history;feedState.browsingOlder=false;feedState.next=null;feedState.items=[];feedState.signature='';
  $('#feed-history').setAttribute('aria-pressed',String(feedState.history));
  $('#feed-label').textContent=feedState.history?'Acknowledged':'Your assistant';
  await refreshFeed().catch(e=>banner(e.message));
});
async function init(){state.csrf=(await api('/api/session')).csrf;localStorage.removeItem('airlock.conversation');await Promise.all([refreshMemory(),refreshFeed()]);
  setInterval(()=>{if(!state.busy&&!feedState.browsingOlder&&!document.hidden&&!feedState.history&&!$('#chat-view').hidden)refreshFeed().catch(()=>{ $('#feed-status').textContent='Updates are unavailable. Retrying shortly…';$('#feed-status').hidden=false;});},10000);
  await refreshExchange(); const status=await api('/api/status');$('#model-status').textContent=status.model_status==='ready'?'Local model ready':'Local model unavailable';$('#status-dot').classList.toggle('offline',status.model_status!=='ready');$('#model-label').textContent=`${status.model} · local inference`; if(status.workspace_timezone && typeof calendarState !== 'undefined'){calendarState.zone=status.workspace_timezone; $('#calendar-zone').value=status.workspace_timezone;}if(status.error)banner(status.error); const params=new URLSearchParams(location.search); if(params.get('view')==='connections'){view('connections');if(params.get('google')==='not_connected')banner('Google sign-in did not finish. Existing access was preserved if available. Retry or ask your administrator if the app was blocked.');history.replaceState(null,'','/');}
}
init().catch(e=>banner(e.message));
