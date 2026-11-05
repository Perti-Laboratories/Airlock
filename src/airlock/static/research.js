'use strict';
let activeResearch=null;
function researchSteps(steps){
  const list=el('ol','research-steps');
  for(const step of steps){
    const row=el('li',`research-step ${step.status}`);
    const marker=({running:'◌',completed:'✓',failed:'!',skipped:'–'})[step.status]||'·';
    row.append(el('span','research-step-label',`${marker} ${step.label}`));
    if(step.detail)row.append(el('small','',step.detail));
    list.append(row);
  }
  return list;
}
function researchDetails(steps){const details=el('details','research-details');details.append(el('summary','','Research & actions'),researchSteps(steps));return details;}
function startChatProgress(id){
  stopChatProgress();
  const turn={id,polling:false,timer:null,signature:''};activeResearch=turn;
  $('#chat-progress').hidden=false;$('#chat-progress').replaceChildren(el('p','muted','Starting local research…'));
  turn.poll=async()=>{
    if(turn.polling||activeResearch!==turn)return;turn.polling=true;
    try{
      const data=await api('/api/chat-progress/'+id);
      if(activeResearch!==turn)return;
      $('#chat-progress').setAttribute('aria-label','Research progress');
      const signature=JSON.stringify(data.steps);
      if(signature===turn.signature)return;
      turn.signature=signature;
      $('#chat-progress').replaceChildren(researchSteps(data.steps));
      $('#chat-progress').scrollTop=$('#chat-progress').scrollHeight;
    }catch{if(activeResearch===turn)$('#chat-progress').setAttribute('aria-label','Research progress reconnecting');}
    finally{turn.polling=false;}
  };
  turn.timer=setInterval(turn.poll,800);
}
function stopChatProgress(){if(activeResearch)clearInterval(activeResearch.timer);activeResearch=null;$('#chat-progress').hidden=true;$('#chat-progress').setAttribute('aria-label','Research progress');}
