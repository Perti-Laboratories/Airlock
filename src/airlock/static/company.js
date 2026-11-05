'use strict';
let companyBusy=false;
async function companyAction(work){if(companyBusy)return;companyBusy=true;$('#company-notice').textContent='Working locally…';try{const result=await work();await refreshCompany();$('#company-notice').textContent=result?.result?.status==='failed'?'Extraction failed. Check processing details.':'Done.';}catch(e){$('#company-notice').textContent=e.message;}finally{companyBusy=false;}}
async function refreshCompany(){
 const data=await api('/api/company');
 $('#company-status').textContent=!data.connected?'No company connected':data.name+' · '+(data.enabled?'Connected':'Paused');
 $('#company-automatic').checked=data.automatic_research;$('#company-automatic').disabled=!data.connected;
 $('#company-extraction').checked=data.extraction_enabled;$('#company-enabled').checked=data.enabled;
 $('#company-connect').hidden=data.connected;$('#company-enabled-label').hidden=!data.connected;$('#company-save').hidden=!data.connected;
 $('#company-run').disabled=!data.enabled||!data.extraction_enabled;
 $('#company-details').textContent=data.connected?JSON.stringify({endpoint:data.endpoint,embedding:data.embedding_spec,last_run:data.last_run_at,next_run:data.next_run_at,error:data.error},null,2):'Local prototype · separate Postgres on this Mac';
 const sources=$('#company-sources');sources.replaceChildren();
 for(const s of data.sources){const row=el('div','control-card');const label=el('label','checkbox');const checkbox=el('input');checkbox.type='checkbox';checkbox.checked=s.selected;checkbox.disabled=!data.connected;
 checkbox.onchange=()=>companyAction(()=>api('/api/company/sources/'+s.id,'PUT',{enabled:checkbox.checked}));
 label.append(checkbox,document.createTextNode(s.title));row.append(label,el('p','muted',s.kind+' · '+s.status+' · '+s.passages_done+' passages processed'+(s.error?' · '+s.error:'')));sources.append(row);}
 if(!data.sources.length)sources.append(el('p','muted','Upload a synthetic company document in Chat, then select it here.'));
 const cards=$('#company-candidates');cards.replaceChildren();
 for(const c of data.candidates){const card=el('article','control-card');card.append(el('span','eyebrow',c.status),el('h3','',c.title),el('p','',c.content),el('blockquote','',c.evidence),el('p','muted','Source: '+c.source_label+' · passage '+(c.ordinal+1)));
 const details=el('details');details.append(el('summary','','Processing & receipt'),el('pre','',JSON.stringify({embedding:c.embedding_spec,receipt:c.receipt,source_current:c.source_current},null,2)));card.append(details);
 if(c.status==='pending'){const send=button('Send reviewed candidate',()=>companyAction(()=>api('/api/company/candidates/'+c.id+'/submit','POST')),'primary');send.disabled=!data.enabled||!c.source_current;card.append(send,button('Reject',()=>companyAction(()=>api('/api/company/candidates/'+c.id+'/reject','POST')),'secondary'));}
 if(c.status==='submitted')card.append(button('Refresh company receipt',()=>companyAction(()=>api('/api/company/candidates/'+c.id+'/submit','POST')),'secondary'));
 if(!c.source_current)card.append(el('p','muted','Source changed or unselected. This candidate cannot be sent.'));cards.append(card);}
 if(!data.candidates.length)cards.append(el('p','muted','No suggestions yet. Select a source and enable suggestions to begin.'));
}
$('#company-connect').onclick=()=>companyAction(()=>api('/api/company/demo','POST',{enabled:$('#company-extraction').checked}));
$('#company-save').onclick=()=>companyAction(()=>api('/api/company','PUT',{enabled:$('#company-enabled').checked,extraction_enabled:$('#company-extraction').checked,automatic_research:$('#company-automatic').checked}));
$('#company-run').onclick=()=>companyAction(()=>api('/api/company/extract','POST'));
$('#company-refresh').onclick=()=>refreshCompany().catch(e=>banner(e.message));
