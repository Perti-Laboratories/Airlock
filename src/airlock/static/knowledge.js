'use strict';
let chatAttachments=[],editingContact=null,pendingRemoval=null;
async function refreshModels(){
 const d=await api('/api/models');const select=$('#chat-model-choice');select.replaceChildren();
 for(const m of d.choices){const option=el('option','',m.name);option.value=m.name;select.append(option);}
 select.value=d.model;$('#save-model').disabled=!d.choices.length;
 $('#model-choice-status').textContent='Current model: '+d.model;
 $('#embedding-choice').textContent='Search embeddings: '+d.embedding_model+' · Ollama on this Mac';
}
$('#refresh-models').onclick=()=>refreshModels().catch(e=>banner(e.message));
$('#model-form').onsubmit=async e=>{e.preventDefault();$('#save-model').disabled=true;try{await api('/api/models','PUT',{model:$('#chat-model-choice').value});await refreshModels();const s=await api('/api/status');$('#model-label').textContent=s.model+' · local inference';$('#model-status').textContent=s.model_status==='ready'?'Local model ready':'Local model unavailable';$('#model-choice-status').textContent='Saved. New chats and agent runs use '+s.model+'.';}catch(e){banner(e.message);}finally{$('#save-model').disabled=false;}};
function renderAttachments(){const node=$('#chat-attachments');node.hidden=!chatAttachments.length;node.replaceChildren();$('#upload-status').hidden=true;for(const a of chatAttachments)node.append(button(a.title+' ×',()=>{chatAttachments=chatAttachments.filter(x=>x.id!==a.id);renderAttachments();},'secondary'));}
$('#upload-document').onclick=()=>{if(!state.busy)$('#chat-upload').click();};
$('#chat-upload').onchange=async()=>{
 const file=$('#chat-upload').files[0];if(!file)return;
 if(file.size>2*1024*1024){banner('Choose a document smaller than 2 MB.');$('#chat-upload').value='';return;}
 if(chatAttachments.length>=4){banner('Attach at most four documents per message.');$('#chat-upload').value='';return;}
 if(state.busy)return;
 setBusy(true);$('#upload-document').disabled=true;$('#upload-status').hidden=false;$('#upload-status').textContent='Adding '+file.name+'…';
 try{const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
 const {result}=await api('/api/knowledge/upload','POST',{filename:file.name,content_base64:encoded});
 if(result.status==='ready'){if(!chatAttachments.some(a=>a.id===result.id))chatAttachments.push(result);renderAttachments();$('#upload-status').textContent='';$('#upload-status').hidden=true;$('#chat-upload').value='';}
 else{$('#upload-status').textContent='Saved. Indexing failed — retry in Settings & Activity → Sources.';}
 }catch(e){$('#upload-status').hidden=false;$('#upload-status').textContent=e.message;}finally{setBusy(false);$('#chat-upload').value='';}
};
async function showSource(id){const s=await api('/api/knowledge/'+id);$('#source-title').textContent=s.title;$('#source-content').textContent=s.content;$('#source-detail').showModal();}
function confirmRemoval(title,note,action){pendingRemoval=action;$('#knowledge-delete-title').textContent=title;$('#knowledge-delete-note').textContent=note;$('#knowledge-delete').showModal();}
$('#knowledge-delete-confirm').onclick=async()=>{try{await pendingRemoval();$('#knowledge-delete').close();}catch(e){banner(e.message);}};
async function refreshSources(){const sources=await api('/api/knowledge');const node=$('#source-list');node.replaceChildren();for(const s of sources){const card=el('article','control-card');card.append(el('span','memory-type',s.kind),el('h3','',s.title),el('p','muted',s.status+' · '+s.chunks+' passages'+(s.error?' · '+s.error:'')),button('Read source',()=>showSource(s.id),'secondary'));
 if(s.status!=='ready')card.append(button('Retry indexing',async()=>{await api('/api/knowledge/'+s.id+'/retry','POST');await refreshSources();},'secondary'));
 if(!['contact','interaction'].includes(s.kind))card.append(button('Remove from retrieval',()=>confirmRemoval('Remove this source?',s.title+' — removes searchable text and vectors. Historical conversations and reports are retained.',async()=>{await api('/api/knowledge/'+s.id,'DELETE');chatAttachments=chatAttachments.filter(a=>a.id!==s.id);renderAttachments();await refreshSources();}),'text-button'));
 node.append(card);}if(!sources.length)node.append(el('div','empty-card','No sources yet. Attach a document in Chat to get started.'));}
$('#refresh-sources').onclick=()=>refreshSources().catch(e=>banner(e.message));
const contactFields=[['name','Name',240],['email','Email',320],['phone','Phone',80],['organization','Organization',240],['summary','About this person',4000],['notes','Private notes',4000]];
for(const [key,label,max] of contactFields){const l=el('label','',label);l.htmlFor='contact-'+key;const input=el(max===4000?'textarea':'input');input.id='contact-'+key;input.maxLength=max;if(key==='name')input.required=true;if(key==='email')input.type='email';$('#contact-fields').append(l,input);}
function editContact(c=null){editingContact=c;for(const [key] of contactFields)$('#contact-'+key).value=c?.[key]||'';$('#contact-error').textContent='';$('#contact-editor').showModal();}
$('#add-contact').onclick=()=>editContact();
$('#contact-form').onsubmit=async e=>{e.preventDefault();try{const body=Object.fromEntries(contactFields.map(([key])=>[key,$('#contact-'+key).value]));body.expected_revision=editingContact?.revision||null;await api(editingContact?'/api/contacts/'+editingContact.id:'/api/contacts',editingContact?'PUT':'POST',body);$('#contact-editor').close();await refreshContacts();}catch(e){$('#contact-error').textContent=e.message;}};
function logInteraction(c){editingContact=c;$('#interaction-heading').textContent='Interaction with '+c.name;$('#interaction-summary').value='';$('#interaction-type').value='note';$('#interaction-error').textContent='';const d=new Date();$('#interaction-time').value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);$('#interaction-editor').showModal();}
$('#interaction-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/contacts/'+editingContact.id+'/interactions','POST',{expected_revision:editingContact.revision,interaction_type:$('#interaction-type').value,occurred_at:new Date($('#interaction-time').value).toISOString(),summary:$('#interaction-summary').value});$('#interaction-editor').close();await refreshContacts();}catch(e){$('#interaction-error').textContent=e.message;}};
$('#contact-search-form').onsubmit=e=>{e.preventDefault();refreshContacts().catch(e=>banner(e.message));};
async function refreshContacts(){const contacts=await api('/api/contacts?q='+encodeURIComponent($('#contact-search').value));const node=$('#contact-list');node.replaceChildren();for(const c of contacts){const card=el('article','control-card');card.append(el('h3','',c.name),el('p','muted',[c.organization,c.email,c.phone].filter(Boolean).join(' · ')),el('p','',c.summary),el('p','',c.notes),button('Edit',()=>editContact(c),'secondary'),button('Log interaction',()=>logInteraction(c),'secondary'),button('Delete contact',()=>confirmRemoval('Delete '+c.name+'?', 'Removes this contact and its interactions from active chat retrieval. Local history is retained.',async()=>{await api('/api/contacts/'+c.id+'/delete','POST',{expected_revision:c.revision});await refreshContacts();}),'text-button'));
 for(const i of c.interactions){const row=el('div','contact-interaction');row.append(el('p','muted',i.interaction_type+' · '+new Date(i.occurred_at).toLocaleString()),el('p','',i.summary),button('Remove interaction',()=>confirmRemoval('Remove this interaction?', 'Removes this interaction from active retrieval. Local audit history remains.',async()=>{await api('/api/contacts/'+c.id+'/interactions/'+i.id+'/delete','POST',{expected_revision:c.revision});await refreshContacts();}),'text-button'));card.append(row);}node.append(card);}if(!contacts.length)node.append(el('div','empty-card','No matching contacts. Add a person here or ask chat to create a contact.'));}

let settingsSection='models';
function showSettings(section){
 settingsSection=section;
 for(const name of ['models','connections','sources','activity']){
  $('#'+name+'-view').hidden=name!==section;
  const tab=$('#tab-'+name);tab.setAttribute('aria-selected',String(name===section));tab.tabIndex=name===section?0:-1;
 }
 const refresh={models:refreshModels,connections:refreshConnections,sources:refreshSources,activity:refreshActivity};
 refresh[section]().catch(e=>banner(e.message));
}
document.querySelectorAll('[data-settings]').forEach(tab=>{
 tab.onclick=()=>showSettings(tab.dataset.settings);
 tab.onkeydown=event=>{
  const tabs=[...document.querySelectorAll('[data-settings]')];let next;
  if(event.key==='ArrowRight')next=(tabs.indexOf(tab)+1)%tabs.length;
  if(event.key==='ArrowLeft')next=(tabs.indexOf(tab)+tabs.length-1)%tabs.length;
  if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;
  if(next!==undefined){event.preventDefault();tabs[next].focus();showSettings(tabs[next].dataset.settings);}
 };
});
