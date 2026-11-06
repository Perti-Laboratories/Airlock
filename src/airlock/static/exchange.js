'use strict';
let todoEditing=null;
const sharingState={connection:null,busy:false,connectionDirty:false};
function renderSharingStatus(){
 const s=sharingState.connection;if(!s)return;
 const paused=s.release_paused;
 $('#sharing-status').textContent=!s.paired?'Not connected':!s.enabled?'Connection off':paused?'Outbound sharing paused':s.error?'Sharing needs attention':'Outbound sharing on';
 $('#sharing-hint').textContent=!s.paired?'Pair a connector below to get started.':!s.enabled?'Enable the connection to exchange approved information.':paused?(releaseState.dirty?'Save your rule changes, then resume sharing.':'Choose what can leave below, then resume sharing.'):(s.error||'Saved type levels also control incoming calendar events and to-dos.');
 $('#sharing-toggle').textContent=!s.enabled?'Enable connection':paused?'Resume sharing':'Pause sharing';
 $('#sharing-toggle').disabled=!s.paired||sharingState.busy||(s.enabled&&paused&&releaseState.dirty);
 $('#sharing-toggle').classList.toggle('secondary',s.enabled&&!paused);
 $('#exchange-banner').textContent=!s.enabled?'Connection off':paused?'Outbound sharing paused':'Approved sharing on';
}
async function refreshExchange(){
 const s=await api('/api/exchange');sharingState.connection=s;
 $('#exchange-status').textContent=s.paired?'Paired · '+s.endpoint:'No connector paired';
 if(!sharingState.connectionDirty){$('#exchange-enabled').checked=s.enabled;$('#exchange-inbound').checked=s.allow_availability;}
 $('#exchange-save').disabled=!s.paired;$('#exchange-sync').disabled=!s.enabled;
 $('#exchange-pair').disabled=s.paired;$('#exchange-invitation').disabled=s.paired;
 $('#exchange-pairing').hidden=s.paired;$('#exchange-pairing').open=!s.paired;
 $('#exchange-details').textContent=s.paired?`Last delivery: ${s.last_sent_at?new Date(s.last_sent_at).toLocaleString():'none'} · package ${s.acknowledged_revision}/${s.revision}${s.queued?' · pending':''}${s.error?' · '+s.error:''}`:'';
 const p=s.last_package;
 $('#exchange-records').textContent=!s.paired?'':!p?'No package prepared yet.':
  `Last prepared package: ${p.calendar_count} calendar events · ${p.todo_count} to-dos${s.queued?' · awaiting delivery':''}. `+
  (p.expired?'Expired; the receiver cannot use it. ':!p.sources_fresh?'A calendar source is stale. Check Settings & Activity → Connections. ':'')+
  (!p.calendar_count&&!p.todo_count?'An empty package is valid: only approved upcoming events and reviewed to-dos appear. ':'')+
  (s.allow_availability?(s.inbound_expires_at&&new Date(s.inbound_expires_at)>new Date()?`Incoming availability is valid until ${new Date(s.inbound_expires_at).toLocaleTimeString()}.`:'Incoming availability is missing or expired; send a new test block from the harness.'):'Incoming availability is off.');
 const r=s.records;
 if(r)$('#exchange-records').textContent+=` Incoming records: ${r.calendar_count} calendar · ${r.todo_count} to-dos · ${!r.enabled?'off':r.stale?'waiting or expired':'current'}.${r.error?' '+r.error:''}`;
 $('#exchange-harness-link').hidden=s.endpoint!=='http://127.0.0.1:8742';
 renderSharingStatus();
}
async function refreshSharing(){await Promise.all([refreshReleases(),refreshExchange()]);}
$('#exchange-pair').addEventListener('click',async()=>{try{const f=$('#exchange-invitation').files[0];if(!f||f.size>8000)throw new Error('Choose a connector invitation smaller than 8 KB.');await api('/api/exchange/pair','POST',{invitation:JSON.parse(await f.text())});$('#exchange-invitation').value='';await refreshSharing();}catch(e){banner(e.message);}});
$('#exchange-form').addEventListener('change',()=>{sharingState.connectionDirty=true;});
$('#exchange-form').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/exchange','PUT',{enabled:$('#exchange-enabled').checked,allow_availability:$('#exchange-inbound').checked});sharingState.connectionDirty=false;await refreshExchange();}catch(e){banner(e.message);}});
$('#exchange-sync').addEventListener('click',async()=>{try{await api('/api/exchange/sync','POST');await refreshExchange();}catch(e){banner(e.message);}});
$('#sharing-todos').onclick=()=>view('todos');
$('#sharing-toggle').onclick=async()=>{
 const s=sharingState.connection;if(!s||!s.paired||sharingState.busy)return;
 sharingState.busy=true;renderSharingStatus();$('#sharing-result').hidden=true;
 try{
  if(!s.enabled){
   await api('/api/exchange','PUT',{enabled:true,allow_availability:s.allow_availability});
   $('#exchange-enabled').checked=true;$('#sharing-result').textContent='Connection enabled.';
  }else{
   if(s.release_paused&&releaseState.dirty)throw Error('Save your rule changes before resuming.');
   const p=releaseState.policy;if(!p)throw Error('Refresh Sharing and try again.');
   // Toggle only the saved policy. Unsaved rule changes cannot be released by this action.
   await api('/api/release-policy','PUT',{expected_revision:p.revision,paused:!s.release_paused,
    rules:p.rules,type_rules:p.type_rules,acknowledge_titles:Object.values(p.rules).includes('original')});
   $('#sharing-result').textContent=s.release_paused?'Sharing resumed. Approved records will sync shortly.':'Sharing paused. Released records will be withdrawn on the next successful sync.';
   await refreshReleases({preserveDraft:releaseState.dirty});
  }
  await refreshExchange();
 }catch(e){$('#sharing-result').textContent=e.message;}
 finally{sharingState.busy=false;$('#sharing-result').hidden=false;renderSharingStatus();}
};
async function refreshTodos(){
 const todos=await api('/api/todos');const target=$('#todo-list');target.replaceChildren();
 for(const t of todos){const card=el('article','control-card');card.append(el('h3','',t.title),el('p','',t.description),el('p','muted',`${t.status.replaceAll('_',' ')} · ${t.priority}${t.due_at?' · due '+new Date(t.due_at).toLocaleString():''}`));
 if(t.read_only){card.append(el('p','muted','From connected planner · edit at source'));target.append(card);continue;}
 const approved=t.release_title&&t.release_revision===t.revision;
 card.append(el('p','',approved?'Reviewed release: '+t.release_title+' · '+t.status+(t.release_due&&t.due_at?' · '+new Date(t.due_at).toLocaleString():''):t.release_title?'Changed since review · kept private':'Kept private'));
 card.append(button('Edit',()=>editTodo(t),'secondary'),button(t.status==='done'?'Reopen':'Complete',async()=>{await api('/api/todos/'+t.id,'PUT',{title:t.title,description:t.description,due_at:t.due_at,scheduled_start_at:t.scheduled_start_at,estimated_minutes:t.estimated_minutes,priority:t.priority,status:t.status==='done'?'open':'done',expected_revision:t.revision});await refreshTodos();},'secondary'));
 card.append(button('Review release',()=>{todoEditing=t;$('#todo-release-title').value=t.release_title||'';$('#todo-release-due').checked=t.release_due;$('#todo-release-name').textContent=t.title+' · '+t.status;$('#todo-release-dialog').showModal();},'secondary'));
 card.append(button('Delete',()=>{todoEditing=t;$('#todo-delete-name').textContent=t.title;$('#todo-delete-dialog').showModal();},'text-button'));
 target.append(card);
 }
 if(!todos.length)target.append(el('div','empty-card','Add a local to-do. It stays private until you review a release.'));
}
function editTodo(t=null){todoEditing=t;$('#todo-title').value=t?.title||'';$('#todo-description').value=t?.description||'';$('#todo-due').value=t?.due_at?new Date(new Date(t.due_at).getTime()-new Date(t.due_at).getTimezoneOffset()*60000).toISOString().slice(0,16):'';$('#todo-priority').value=t?.priority||'normal';$('#todo-status').value=t?.status||'open';$('#todo-error').textContent='';$('#todo-editor').showModal();}
$('#add-todo').addEventListener('click',()=>editTodo());
$('#refresh-todos').addEventListener('click',()=>refreshTodos().catch(e=>banner(e.message)));
$('#todo-form').addEventListener('submit',async e=>{e.preventDefault();try{const t=todoEditing;await api(t?'/api/todos/'+t.id:'/api/todos',t?'PUT':'POST',{title:$('#todo-title').value,description:$('#todo-description').value,due_at:$('#todo-due').value?new Date($('#todo-due').value).toISOString():null,priority:$('#todo-priority').value,status:$('#todo-status').value,scheduled_start_at:t?.scheduled_start_at||null,estimated_minutes:t?.estimated_minutes||null,expected_revision:t?.revision||null});$('#todo-editor').close();await refreshTodos();}catch(e){$('#todo-error').textContent=e.message;}});
$('#todo-release-form').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/todos/'+todoEditing.id+'/release','PUT',{expected_revision:todoEditing.revision,title:$('#todo-release-title').value.trim()||null,include_due:$('#todo-release-due').checked});$('#todo-release-dialog').close();await refreshTodos();}catch(e){$('#todo-release-error').textContent=e.message;}});
$('#todo-delete-confirm').addEventListener('click',async()=>{await api('/api/todos/'+todoEditing.id+'/delete','POST',{expected_revision:todoEditing.revision});$('#todo-delete-dialog').close();await refreshTodos();});
// Keep read views current without replacing an in-progress editor or unsaved release controls.
setInterval(async()=>{
 if(document.hidden||state.busy||document.querySelector('dialog[open]'))return;
 try{if(!$('#sharing-view').hidden)await refreshExchange();if(!$('#calendar-view').hidden)await refreshCalendar();if(!$('#todos-view').hidden)await refreshTodos();}catch(e){banner(e.message);}
},30000);
