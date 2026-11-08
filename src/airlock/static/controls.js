'use strict';
const releaseState = {policy: null, selected: null, dirty: false};
let googleWatch = null;
let googleBaseline = null;

async function refreshConnections() {
  const [workspace, status] = await Promise.all([api('/api/workspace'), api('/api/google/status')]);
  $('#workspace-name').value = workspace.name;
  $('#google-status').textContent = status.error || (status.connected ? 'Connected to ' + workspace.name : status.account_label ? 'Reconnect Google to restore access to ' + workspace.name : status.configured ? 'Ready to connect to ' + workspace.name : 'Google connection setup is pending for this installation.');
  $('#google-account').textContent = status.account_label ? 'Account: ' + status.account_label : '';
  $('#connect-google').hidden = status.connected || !!status.account_label;
  $('#connect-google').disabled = !status.configured;
  $('#reauthorize-google').hidden = !status.connected && !status.account_label;
  $('#list-google').disabled = !status.connected;
  $('#disconnect-google').disabled = !status.connected && !status.account_label;
  $('#save-google-client').disabled = status.connected || !!status.account_label;
  $('#google-client-file').disabled = status.connected || !!status.account_label;
  $('#google-setup-pending').hidden = status.configured || !!status.error;
  $('#google-next-step').textContent = status.connected ? 'Choose calendars to import.' : status.configured ? 'Sign in to choose your calendars.' : '';
  if (status.connected && googleWatch && status.connected_at !== googleBaseline) {
    clearInterval(googleWatch); googleWatch = null;
    $('#google-signin-status').textContent = 'Google connected. Choose which calendars to read.';
    $('#google-auth-link').hidden = true;
  }
  await refreshCalendar();
  if (status.connected && document.querySelector('#calendar-sources').children.length) {
    $('#google-next-step').textContent = '';
  }
}

async function signIn(path) {
  try {
    googleBaseline = (await api('/api/google/status')).connected_at;
    const result = await api(path, 'POST');
    $('#google-signin-status').textContent = result.browser_opened ? 'Continue in your default browser. SSO and Google permissions happen there.' : 'Open the sign-in link in your default browser to continue.';
    $('#google-auth-link').href = result.authorization_url;
    $('#google-auth-link').hidden = result.browser_opened;
    if (googleWatch) clearInterval(googleWatch);
    const expires = Date.now() + 10 * 60 * 1000;
    googleWatch = setInterval(async () => {
      if (Date.now() > expires) {clearInterval(googleWatch); googleWatch = null; return;}
      try {const status = await api('/api/google/status'); if (status.connected && status.connected_at !== googleBaseline) await refreshConnections();} catch {}
    }, 3000);
  } catch (error) {banner(error.message);}
}
$('#connect-google').addEventListener('click', () => signIn('/api/google/connect'));
$('#reauthorize-google').addEventListener('click', () => signIn('/api/google/reauthorize'));
$('#refresh-connections').addEventListener('click', () => refreshConnections().catch(e => banner(e.message)));
$('#calendar-connections').addEventListener('click', () => view('connections'));
$('#workspace-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {await api('/api/workspace', 'PUT', {name: $('#workspace-name').value}); await refreshConnections();} catch (e) {banner(e.message);}
});
$('#save-google-client').addEventListener('click', async () => {
  const file = $('#google-client-file').files[0];
  try {
    if (!file || file.size > 20000) throw new Error('Choose a Google Desktop client JSON file smaller than 20 KB.');
    let document;
    try {document = JSON.parse(await file.text());} catch {throw new Error('This file is not valid JSON.');}
    await api('/api/google/configure', 'POST', {document});
    $('#google-client-file').value = '';
    $('#google-config-result').textContent = 'App configuration saved in macOS Keychain. Connect Google to choose an account.';
    await refreshConnections();
  } catch (e) {$('#google-config-result').textContent = e.message;}
});
$('#list-google').addEventListener('click', async () => {
  try {
    const calendars = await api('/api/google/calendars');
    $('#google-choices').replaceChildren(...calendars.map(c => button('Add ' + c.name, async () => {
      await api('/api/calendar-sources', 'POST', {calendar_id: c.id});
      await refreshConnections();
    }, 'secondary')));
  } catch (e) {banner(e.message);}
});
$('#disconnect-google').addEventListener('click', async () => {
  try {
    await api('/api/google/disconnect', 'POST');
    if (googleWatch) clearInterval(googleWatch); googleWatch = null;
    $('#google-choices').replaceChildren(); $('#google-auth-link').hidden = true;
    $('#google-signin-status').textContent = 'Disconnected locally. Imported records remain paused. Remove the app in Google account settings to revoke the grant there.';
    await refreshConnections();
  } catch (e) {banner(e.message);}
});

async function refreshReleases({preserveDraft=false}={}) {
  const policy = await api('/api/release-policy'); releaseState.policy = policy;
  $('#release-paused').checked = policy.paused;
  if(!preserveDraft){
  releaseState.dirty=false;
  $('#release-save-status').textContent='';
  $('#release-title-ack').checked = false;
  renderTypeRules(policy.type_rules);
  const rules = $('#release-source-rules'); rules.replaceChildren();
  for (const source of policy.sources) {
    const row = el('label', 'release-rule', source.name + (source.stale ? ' · stale' : ''));
    const select = el('select'); select.dataset.source = source.id;
    for (const [value, text] of [['private','Keep private'], ['busy','Busy times only'], ['original','Original title + busy times']]) {
      const option = el('option', '', text); option.value = value; select.append(option);
    }
    select.value = policy.rules[source.id] || 'private'; row.append(select); rules.append(row);
  }
  }
  updateReleaseDraft();
  const preview = await api('/api/release-preview');
  $('#release-preview-count').textContent = preview.eligible_count + ' ready to share · next 30 days';
  const target = $('#release-preview'); target.replaceChildren();
  for (const item of preview.items) {
    const card = el('article', 'control-card release-item');
    card.append(el('span','eyebrow','LOCAL REVIEW · ' + item.source_name), el('h3','',item.local_title), el('p','muted',item.local_start), el('p','',item.reason));
    if (item.candidate) {
      const details=el('details','inline-help');details.append(el('summary','','View allowed fields'),el('pre','release-payload',JSON.stringify(item.candidate,null,2)));card.append(details);
    }
    card.append(button('Edit sharing', () => {
      releaseState.selected = item;
      $('#release-event-name').textContent = item.local_title;
      $('#release-event-mode').value = item.override_mode;
      $('#release-event-title').value = item.display_title || '';
      $('#release-event-title').disabled = item.override_mode !== 'reviewed';
      $('#release-exception-error').textContent = '';
      $('#release-exception').showModal();
    }, 'secondary'));
    target.append(card);
  }
  if (!preview.items.length) target.append(el('div','empty-card','No upcoming events.'));
}
$('#refresh-releases').addEventListener('click', () => refreshSharing().catch(e => banner(e.message)));
const releaseTypes = [
 ['calendar','Calendar',[['busy','Time blocks only'],['original','Titles + time blocks']]],
 ['todo','To-dos',[['title','Titles + status'],['title_due','Titles + status + due dates']]],
 ['contacts','Contacts',[]],
];
function renderTypeRules(values){
 const target=$('#release-type-rules');target.replaceChildren();
 for(const [key,name,levels] of releaseTypes){
  const row=el('div','release-rule');
  const label=el('label','checkbox');const toggle=el('input');toggle.type='checkbox';
  toggle.dataset.releaseType=key;toggle.checked=values[key]!=='private';toggle.disabled=!levels.length;
  label.append(toggle,document.createTextNode(name));row.append(label);
  if(levels.length){
   const select=el('select');select.dataset.typeLevel=key;select.setAttribute('aria-label',name+' sharing level');
   for(const [value,text] of levels){const option=el('option','',text);option.value=value;select.append(option);}
   select.value=toggle.checked?values[key]:levels[0][0];select.disabled=!toggle.checked;
   toggle.addEventListener('change',()=>{select.disabled=!toggle.checked;});row.append(select);
  }else{row.append(el('span','muted','Always private · sharing unavailable'));}
  target.append(row);
 }
}
function draftTypeRules(){
 return {memory:'private',company_memory:'private',...Object.fromEntries(releaseTypes.map(([key])=>[key,
  document.querySelector('[data-release-type="'+key+'"]').checked
   ?document.querySelector('[data-type-level="'+key+'"]').value:'private']))};
}
function updateReleaseDraft(){
 const hasTitles=draftTypeRules().calendar==='original'&&[...document.querySelectorAll('#release-source-rules select')].some(s=>s.value==='original');
 $('#release-title-confirmation').hidden=!hasTitles||!releaseState.dirty;
 $('#release-save').disabled=!releaseState.dirty;
 if(typeof renderSharingStatus==='function')renderSharingStatus();
}
$('#release-policy-form').addEventListener('change',()=>{releaseState.dirty=true;$('#release-save-status').textContent='Unsaved changes';updateReleaseDraft();});
$('#release-policy-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const rules = Object.fromEntries([...document.querySelectorAll('#release-source-rules select')].map(s => [s.dataset.source,s.value]));
    await api('/api/release-policy','PUT',{expected_revision:releaseState.policy.revision, paused:$('#release-paused').checked, rules, type_rules:draftTypeRules(), acknowledge_titles:$('#release-title-ack').checked});
    await refreshSharing(); $('#release-save-status').textContent = 'Rules saved.';
  } catch (e) {$('#release-save-status').textContent = e.message;}
});
$('#release-event-mode').addEventListener('change', () => {$('#release-event-title').disabled = $('#release-event-mode').value !== 'reviewed';});
$('#release-exception-form').addEventListener('submit', async event => {
  event.preventDefault(); const item = releaseState.selected; const mode = $('#release-event-mode').value;
  try {
    await api('/api/release-policy/events/'+item.event_id,'PUT',{expected_event_revision:item.event_revision, expected_policy_revision:releaseState.policy.revision, mode, display_title:mode==='reviewed'?$('#release-event-title').value:null});
    $('#release-exception').close(); await refreshReleases();
  } catch (e) {$('#release-exception-error').textContent = e.message;}
});
