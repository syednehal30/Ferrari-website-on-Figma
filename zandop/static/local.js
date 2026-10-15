function localButton(text, action, id='', extra='') {
  return `<button class="btn" data-local="${action}" data-id="${h(id)}" ${extra}>${h(text)}</button>`;
}
function localClientButtons(lead) {
  return localButton('Questionnaire','questionnaire',lead.id)+localButton('Edit quote · $500+','quote',lead.id)+localButton('Payoneer link','payoneer',lead.id)+localButton('Compose reply','reply',lead.id)+
    localButton(lead.details.conversation_paused?'Resume replies':'Pause replies','pause-client',lead.id)+
    (lead.demo?localButton('Simulate client email','simulate',lead.id):'')+
    (lead.details.invoice&&!lead.details.paid_at?localButton('Verify Payoneer payment','payment',lead.id):'');
}
function approvalAttachment(payload) {
  const doc=state.documents.find(d=>d.path===payload.attachment);
  return doc?`<a class="btn" href="/api/documents/${h(doc.id)}/download" target="_blank" rel="noopener">Review attached PDF ${icon('download')}</a>`:'';
}
function inbox() {
  const m=state.mailbox;
  const clients=[...state.leads].sort((a,b)=>(b.details.last_client_message_at||'').localeCompare(a.details.last_client_message_at||''));
  return heading('EVERY CLIENT, ONE CONVERSATION','Your client inbox.','Questionnaires, routine replies and project updates. Financial decisions stay with you.',localButton('Check Gmail now','poll'))+
    `<div class="callout"><strong>${m.enabled?'Automatic replies enabled':state.mode==='demo'?'Demo conversations':'Automatic replies paused'}</strong> ${h(m.health.detail||'Connect Gmail in Local setup to receive client email.')} ${m.health.checked_at?'Last checked '+age(m.health.checked_at)+'.':''} The reply target is five minutes while this computer is awake and online.</div>`+
    `<section class="panel"><div class="table-wrap"><table><thead><tr><th>Client</th><th>Conversation</th><th>Last incoming</th><th>Next reply</th></tr></thead><tbody>${clients.map(l=>`<tr data-action="lead" data-id="${l.id}" tabindex="0" role="button"><td><strong>${h(l.name)}</strong><small style="display:block">${h(l.email)}${l.demo?' · Demo':''}</small></td><td>${badge((l.details.conversation_status||'No conversation yet').replaceAll('_',' '),l.details.conversation_status==='needs_owner'?'warning':'neutral')}${l.details.conversation_paused?' · Paused':''}</td><td>${l.details.last_client_message_at?age(l.details.last_client_message_at):'—'}</td><td>${l.details.reply_due_at?badge(Date.now()>Date.parse(l.details.reply_due_at)?'Needs attention':'Queued',Date.now()>Date.parse(l.details.reply_due_at)?'warning':'neutral'):'—'}</td></tr>`).join('')}</tbody></table>${clients.length?'':'<div class="empty">New messages arriving in your selected Gmail label create client records here.</div>'}</div></section>`+
    `<section class="panel" style="margin-top:24px;padding:24px"><h2>Messages waiting to send</h2><p>Financial sends wait for approval. An uncertain send is held until you check Gmail, preventing duplicate replies.</p>${state.outbox.map(a=>`<div class="message"><strong>${h(clientName(a.lead_id))} · ${h(a.kind.replaceAll('_',' '))}</strong> ${badge(a.status,a.status==='uncertain'?'warning':'neutral')}<p>${h(a.result||'Waiting for the next processing cycle.')}</p>${a.status==='uncertain'?localButton('Resolve send status','reconcile',a.id):''}</div>`).join('')||'<p>No pending messages.</p>'}</section>`;
}
function localSetup() {
  const m=state.mailbox, disabled=!m.local_workspace;
  return heading('YOUR COMPUTER. YOUR CLIENTS.','Set up your local agency.','Free open-source software. Gmail and Payoneer retain their own account limits and fees.')+
    (disabled?'<div class="callout"><strong>This is the demo.</strong> Open <b>Start ZanDop Workspace.bat</b> on Windows to connect your real Gmail account. Your demo data stays separate.</div>':'')+
    `<div class="main-grid"><section class="panel" style="padding:24px"><h2>1. Connect Gmail</h2><p>Create a Gmail label called <b>ZanDop</b>, enable its “Show in IMAP” option, and use Gmail filters to put client conversations there. Only new mail in that label is read after the connection test.</p><p>Enable Google 2-Step Verification, then create an app password. Enter it only here on your own computer. Windows encrypts the saved password for your user account.</p><form data-local-form="gmail"><label class="field">Gmail address<input name="email" type="email" value="${h(m.email)}" autocomplete="username" required ${disabled?'disabled':''}></label><label class="field">Gmail label<input name="label" value="${h(m.label)}" required ${disabled?'disabled':''}></label><label class="field">Gmail app password<input name="password" type="password" autocomplete="new-password" placeholder="${m.password_saved?'Saved — leave blank to keep it':'16-character app password'}" ${disabled?'disabled':''}></label><button class="btn primary" ${disabled?'disabled':''}>Save Gmail settings</button></form><div class="detail-actions" style="margin-top:16px">${localButton('Test connection','test-gmail','',disabled?'disabled':'')}</div><p>${m.verified?'✓ Connection verified.':'Connection not yet verified.'} ${h(m.health.detail||'')}</p><p><a href="https://support.google.com/accounts/answer/185833" target="_blank" rel="noopener">Google app-password instructions ↗</a></p></section>
    <div class="stack"><section class="panel" style="padding:24px"><h2>2. Enable client replies</h2><p>Routine discovery, status, assets, and scheduling messages can send automatically. The owner handles video calls, scope changes, financial or legal messages, and final delivery approval.</p><p>Gmail checks run every 60 seconds. Keep this window and the server running, and keep Windows awake. Messages catch up after the computer reconnects.</p>${localButton(m.enabled?'Pause all automation':'Enable automatic replies','automation','',disabled?'disabled':'')}<p><strong>Cold outreach is separate.</strong> It still requires a warmed secondary domain through Instantly or Smartlead. Those services are optional and may cost money; the Gmail connection is for client correspondence.</p></section>
    <section class="panel" style="padding:24px"><h2>3. Pricing and Payoneer</h2><p>Open a client → <b>Edit quote</b>. Every package starts at <b>$500 USD</b>. You set the price and scope; nothing is quoted until you approve the exact message and PDF.</p><p>Create the matching payment request in your Payoneer account, paste its link into the client record, and approve its email. After payment, check Payoneer yourself and record the receipt. ZanDop cannot create requests or verify balances through a normal Payoneer account.</p></section></div></div>
    <section class="panel" style="padding:24px;margin-top:24px"><h2>Optional: local content drafting</h2><p>Routine client replies need no AI model. For content deliverables, install Ollama and download a model you can run on this PC. Model licensing, hardware and disk requirements vary. No paid model API is needed.</p><form data-local-form="model"><label class="field">Installed Ollama model name<input name="model" value="${h(state.ollama_model)}" placeholder="e.g. qwen2.5:7b"></label><button class="btn">Save model</button></form><p>Ollama must be running on this computer. Drafts still pass through quality checks and final human approval.</p></section>`;
}
function localForm(title, kind, id, content, submit='Save') {
  modal(title,`<form id="local-form" data-local-form="${kind}" data-id="${h(id)}">${content}</form>`,button('Cancel','close',null)+`<button class="btn primary" type="submit" form="local-form">${h(submit)}</button>`,true);
}
document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-local]'); if(!el)return;
  event.preventDefault();
  const action=el.dataset.local,id=el.dataset.id,l=state.leads.find(x=>x.id===id);
  if(el.disabled)return;
  try {
    if(action==='quote') return localForm('Review requirements and set the quote','quote',id,`<div class="message"><h4>Client requirements</h4><p>${h(l.details.requirements||l.details.call_notes||l.details.goals||'No requirements saved yet. Send the questionnaire first.')}</p></div><label class="field">Total package price in USD · minimum $500<input name="price" type="number" min="500" step="0.01" value="${(l.details.quote?.amount||50000)/100}" required></label><label class="field">Exact scope and deliverables<textarea name="scope" minlength="20" maxlength="1200" required style="min-height:150px">${h(l.details.quote?.scope||'')}</textarea></label><p>Saving creates a quote PDF and an approval request. It does not send anything. Revising a quote invalidates its previous unsent approval and client acceptance.</p>`,'Prepare quote for approval');
    if(action==='payoneer') return localForm('Add your Payoneer request','payoneer',id,`<p>Create a payment request in Payoneer matching the approved client quote, then paste its link. Sending waits for your approval at the finance stage.</p><label class="field">Payoneer request URL<input name="url" type="url" required value="${h(l.details.payoneer_url||'')}" placeholder="https://…payoneer.com/…"></label>`);
    if(action==='payment') return localForm('Personally verify payment','payment',id,`<p>Check the actual received payment in your Payoneer dashboard. A client saying “paid” is not payment verification.</p><label class="field">Amount received in USD<input name="price" type="number" min="500" step="0.01" required value="${l.details.invoice.amount/100}"></label><label class="field">Payoneer receipt / transaction reference<input name="reference" minlength="4" maxlength="150" required></label><label class="confirmation-check"><input name="confirmed" type="checkbox" required><span>I personally checked this receipt and amount in Payoneer.</span></label>`,'Record verified payment');
    if(action==='questionnaire') return localForm('Send a client questionnaire','questionnaire',id,`<p>ZanDop will send eight questions tailored to ${h(labels[l.service])}. Answers arrive in the client inbox.</p><label class="confirmation-check"><input name="expected" type="checkbox" required><span>This client expects to hear from us; this is not cold outreach.</span></label>`,'Queue questionnaire');
    if(action==='reply'||action==='simulate') return localForm(action==='simulate'?'Simulate an incoming client email':'Prepare a client reply',action,id,`<label class="field">Subject<input name="subject" required value="${action==='simulate'?'Project details':'Your ZanDop project'}"></label><label class="field">Message<textarea name="body" minlength="2" maxlength="10000" required style="min-height:200px"></textarea></label><p>${action==='simulate'?'Fictional client only. No external email is sent.':'Custom replies go through explicit review before sending. Routine agent responses remain automatic.'}</p>`,action==='simulate'?'Receive simulated email':'Prepare for approval');
    if(action==='reconcile') return localForm('Check whether Gmail accepted this message','reconcile',id,`<p>Inspect your Gmail Sent folder before choosing. Do not retry a message whose send status is unknown.</p><label class="field">Verified outcome<select name="outcome"><option value="sent">Gmail accepted the message</option><option value="not_sent">Confirmed it was not sent</option></select></label><label class="field">Evidence<textarea name="evidence" minlength="15" required></textarea></label><label class="field">Gmail Message-ID if sent<input name="provider_id"></label>`,'Record outcome');
    el.disabled=true;
    if(action==='poll') {const r=await api('/local/poll',{method:'POST'});toast(r.error||`Checked Gmail: ${r.processed} messages.`,!!r.error);}
    if(action==='test-gmail') {await api('/local/gmail/test',{method:'POST'});toast('Gmail login verified. No test email was sent.');}
    if(action==='automation') {await api('/local/automation',{method:'POST',body:JSON.stringify({enabled:!state.mailbox.enabled})});toast(state.mailbox.enabled?'Automation paused.':'Automatic client replies enabled.');}
    if(action==='pause-client') {await api(`/leads/${id}/conversation-pause`,{method:'POST',body:JSON.stringify({enabled:!l.details.conversation_paused})});closeModal();}
    await refresh();
  }catch(error){toast(error.message,true);}finally{el.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-local-form]');if(!form)return;
  event.preventDefault();
  const data=Object.fromEntries(new FormData(form)), kind=form.dataset.localForm,id=form.dataset.id;
  const submit=form.querySelector('button')||document.querySelector('[form="local-form"]');if(submit)submit.disabled=true;
  const cents=value=>{if(!/^\d+(\.\d{1,2})?$/.test(value))throw Error('Enter a USD amount with at most two decimal places.');const [whole,fraction='']=value.split('.');return Number(whole)*100+Number(fraction.padEnd(2,'0'));};
  try {
    let path,body=data;
    if(kind==='gmail')path='/local/gmail';
    if(kind==='model')path='/local/model';
    if(kind==='quote'){path=`/leads/${id}/quote`;body={amount:cents(data.price),scope:data.scope};}
    if(kind==='payoneer')path=`/leads/${id}/payoneer`;
    if(kind==='payment'){path=`/leads/${id}/confirm-payment`;body={amount:cents(data.price),reference:data.reference,confirmed:!!data.confirmed};}
    if(kind==='questionnaire'){path=`/leads/${id}/questionnaire`;body={client_expects_contact:!!data.expected};}
    if(kind==='reply')path=`/leads/${id}/reply`;
    if(kind==='simulate')path=`/leads/${id}/simulate-message`;
    if(kind==='reconcile'){path='/actions/reconcile';body={...data,action_id:id,provider_id:data.provider_id||null};}
    const result=await api(path,{method:'POST',body:JSON.stringify(body)});
    if(kind==='gmail')form.querySelector('[name="password"]').value='';
    closeModal();await refresh();
    toast(result.status==='approval'||kind==='quote'||kind==='reply'?'Prepared for your review in Approvals.':'Saved to the workspace.');
  }catch(error){toast(error.message,true);}finally{if(submit)submit.disabled=false;}
});
