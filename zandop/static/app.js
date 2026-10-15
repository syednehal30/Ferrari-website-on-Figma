const paths = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  flow:'<rect x="2" y="8" width="5" height="7" rx="1"/><rect x="17" y="2" width="5" height="6" rx="1"/><rect x="17" y="16" width="5" height="6" rx="1"/><path d="M7 11h5V5h5M12 11v8h5"/>',
  users:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/>',
  file:'<path d="M14 2H5a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V8zM14 2v6h6M8 13h8M8 17h6"/>',
  shield:'<path d="M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6"/>',
  plug:'<path d="m8 3 3 3m5-3 3 3M5 10l9-9M9 6l9 9M3 21l6-6M5 10l9 9 6-6-9-9z"/>',
  activity:'<path d="M2 12h4l3-8 5 16 3-8h5"/>',
  radar:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="m12 12 7-7"/><circle cx="12" cy="12" r="1"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  send:'<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>',
  chat:'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 1 1 17-5Z"/><path d="M8 10h8M8 14h4"/>',
  database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4M18 4h4"/>',
  code:'<path d="m7 6-5 6 5 6M17 6l5 6-5 6M14 3l-4 18"/>',
  wallet:'<path d="M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h17v12H5a3 3 0 0 1-3-3V6M22 12h-6v5h6"/><path d="M18 14.5h.1"/>',
  chart:'<path d="M3 3v18h18M7 16v-5M12 16V7M17 16v-8"/>',
  gift:'<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v9h14v-9M12 8v13M12 8c-7 0-7-7-3-6 3 1 3 6 3 6s0-5 3-6c4-1 4 6-3 6"/>',
  bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  plus:'<path d="M12 4v16M4 12h16"/>',
  play:'<path d="m8 4 12 8-12 8z"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  globe:'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 10h18M8 14h2M14 14h2"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>'
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = null, filter = 'all', search = '', page = 'overview', busy = false;
const nav = [['overview','Overview','grid'],['workflow','Agent workflow','flow'],['growth','Lead finder','globe'],['crm','Leads & clients','users'],['inbox','Client inbox','chat'],['documents','Client documents','file'],['approvals','Approvals','shield'],['local-setup','Local setup','plug'],['integrations','Integrations','plug'],['activity','Activity log','activity']];
const labels = {ecommerce:'E-commerce',website:'Website',content:'Content'};
const statusLabels = {awaiting_review:'Review first email',awaiting_capacity:'Waiting for a project slot',ready:'Ready',approval:'Needs approval',awaiting_reply:'Awaiting reply',awaiting_call:'Call booked',awaiting_payment:'Awaiting payment',queued:'Queued',awaiting_requirements:'Awaiting answers',awaiting_acceptance:'Awaiting client acceptance',blocked:'Needs attention',scheduled:'Scheduled',closed:'Closed',suppressed:'Suppressed',rejected:'Held for revision'};
const pending = () => state.approvals.filter(a => a.status === 'pending');
const clientName = id => state.leads.find(l => l.id === id)?.name || 'Workspace';
const age = value => { const diff = Math.max(0,(Date.now()-new Date(value))/60000); return diff < 1 ? 'Just now' : diff < 60 ? `${Math.floor(diff)}m ago` : diff < 1440 ? `${Math.floor(diff/60)}h ago` : `${Math.floor(diff/1440)}d ago`; };
const money = (amount,currency='usd') => new Intl.NumberFormat('en-US',{style:'currency',currency:currency.toUpperCase(),maximumFractionDigits:0}).format(amount/100);
const badge = (label,kind='') => `<span class="badge ${h(kind)}">${h(label)}</span>`;
const logo = (lead,index=0) => `<div class="client-logo c${index%6}">${h(lead.name.slice(0,1))}${lead.name.includes(' ')?'<span style="font-size:8px;margin-left:-6px">.</span>':''}</div>`;
const button = (text,action,ico,classes='',extra='') => `<button class="btn ${classes}" data-action="${action}" ${extra}>${ico?icon(ico):''}${text}</button>`;

async function api(path, options={}) {
  const headers = {'Content-Type':'application/json',...(options.headers||{})};
  const token = sessionStorage.getItem('zandop-token');
  if(token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api${path}`, {...options,headers});
  let result;
  try { result = await response.json(); } catch { throw new Error('The server returned an unexpected response.'); }
  if(!response.ok) {
    if(response.status===401) { renderLogin(); throw new Error('Sign in with the workspace operator token.'); }
    throw new Error(typeof result.detail==='string' ? result.detail : JSON.stringify(result.detail));
  }
  return result;
}

function editingForm() {
  return !!document.querySelector('form[data-dirty="true"]') || !!document.activeElement?.closest('form');
}
async function refresh(background=false) {
  const next = await api('/state');
  if(background && (editingForm() || document.querySelector('.modal')))return;
  state = next;
  render();
}
function toast(message,error=false) {
  const el = document.createElement('div'); el.className = 'toast'+(error?' error':''); el.textContent=message;
  const root=document.getElementById('toast-root');
  while(root.children.length>=2)root.firstElementChild.remove();
  root.append(el); setTimeout(()=>el.remove(),6500);
}
function renderLogin() {
  document.getElementById('main').innerHTML = `<div class="login-card panel" style="padding:30px">${icon('lock')}<h1>Your agency workspace</h1><p>Enter the operator token configured for this environment. It stays in this browser session.</p><form data-form="login"><label class="field">Operator token<input name="token" type="password" required autocomplete="current-password"></label><button class="btn primary" type="submit">Open workspace ${icon('arrow')}</button></form></div>`;
}

function render() {
  if(!state) return;
  page = location.hash.slice(1).split('?')[0] || 'overview';
  if(!nav.some(n=>n[0]===page)) page='overview';
  document.getElementById('breadcrumb').textContent = nav.find(n=>n[0]===page)[1];
  document.getElementById('mode-pill').textContent = state.mode==='demo' ? 'Demo workspace' : !state.mailbox.verified ? 'Real workspace · setup needed' : state.mode==='paused' ? 'Real workspace · paused' : 'Real workspace · running';
  document.getElementById('notification-button').innerHTML=icon('bell');
  document.getElementById('navigation').innerHTML=nav.map(([id,title,ico])=>`<a href="#${id}" class="nav-item ${page===id?'active':''}" ${page===id?'aria-current="page"':''}>${icon(ico)}<span>${title}</span>${id==='approvals' && pending().length?`<span class="nav-count">${pending().length}</span>`:''}</a>`).join('');
  document.getElementById('last-sync').textContent = `v${state.version||'0.3.1'} · Updated ${new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',timeZone:'Asia/Karachi'}).format(new Date(state.updated_at))} PKT`;
  const views = {growth:leadFinder,overview,workflow,crm,inbox,documents,approvals,integrations,activity,'local-setup':localSetup};
  document.getElementById('main').innerHTML=(state.mode==='demo'?`<div class="callout" role="status"><strong>Demo only — these are fictional clients.</strong><p>To use your Gmail, close this demo and open <b>Start ZanDop.bat</b> or <b>Start ZanDop Workspace.bat</b> in the updated download. A real workspace opens Local setup and has no sample clients. The demo sends no real emails.</p><a class="btn" href="#local-setup">View setup instructions</a></div>`:'')+views[page]();
}

function heading(eyebrow,title,subtitle,actions='') {
  return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function metrics() {
  const liveProjects=state.leads.filter(l=>l.stage>=6&&l.stage<=10).length;
  const demoValue=state.approvals.filter(a=>a.demo&&a.kind==='proposal').reduce((sum,a)=>sum+(a.payload.amount||0),0);
  const valueCard=state.mode==='demo'?['Demo proposal value',money(demoValue),'wallet','Illustrative · not revenue','']:['Accepted scope value',money(state.growth.capacity.booked_amount),'wallet','This week · payment verified separately',''];
  const data=[['Leads in your orbit',state.leads.length,'users','Imported & scored','positive'],['Projects in motion',liveProjects,'code','From welcome to handoff','positive'],['Your attention needed',pending().length,'shield','Human checkpoints','attention'],valueCard];
  return `<div class="metrics">${data.map(([title,value,ico,caption,cls],i)=>`<div class="metric"><div class="metric-top">${title}<span class="metric-icon">${icon(ico)}</span></div><strong>${value}</strong><div class="metric-foot"><span class="${cls}">${i===2?'◷':i<2?'+':'○'}</span>${caption}</div>${i!==2?`<svg class="metric-spark" viewBox="0 0 80 30" aria-hidden="true"><path d="M1 ${24-i*3} 12 21 20 24 31 13 42 17 53 8 64 12 79 3" fill="none" stroke="${i===3?'#b9a2d0':'#a3c1ad'}" stroke-width="1.8"/></svg>`:''}</div>`).join('')}</div>`;
}
function pipeline() {
  return `<div class="pipeline-scroll"><div class="pipeline-track">${state.stages.map((stage,i)=>{
    const count=state.leads.filter(l=>l.stage===stage.id&&!['closed','suppressed'].includes(l.status)).length;
    return `${i?'<span class="flow-arrow">›</span>':''}<button class="stage ${count?'has-leads':''}" data-action="stage" data-id="${stage.id}" aria-label="Stage ${stage.id}: ${h(stage.name)}, ${count} leads"><div class="stage-graphic">${icon(stage.icon)}${count?`<span class="stage-count">${count}</span>`:''}</div><span class="stage-label">${h(stage.name)}</span><span class="stage-number">${String(stage.id).padStart(2,'0')}</span></button>`;
  }).join('')}</div></div>`;
}
function leadTable(leads,wide=false) {
  return `<div class="table-wrap"><table class="${wide?'table-wide':''}"><thead><tr><th>Business</th><th>Service</th>${wide?'<th>Source</th><th>Score</th>':''}<th>Current stage</th><th>${wide?'Status':'Score'}</th></tr></thead><tbody>${leads.map((lead,i)=>`<tr data-action="lead" data-id="${lead.id}" tabindex="0" role="button" aria-label="Open ${h(lead.name)}"><td><div class="client-cell">${logo(lead,i)}<div><strong>${h(lead.name)}</strong><small>${h(lead.industry||lead.email)}${lead.demo?' · Demo':''}</small></div></div></td><td><span class="service ${lead.service}"><span class="service-dot"></span>${labels[lead.service]}</span></td>${wide?`<td>${h(lead.source.replaceAll('_',' '))}</td><td><span class="score">${lead.score}</span></td>`:''}<td>${badge(state.stages[lead.stage-1].name,lead.status==='approval'?'warning':'')}</td><td>${wide?badge(statusLabels[lead.status]||lead.status,lead.status==='blocked'?'danger':lead.status==='approval'?'warning':'neutral'):`<span class="score">${lead.score}</span>`}</td></tr>`).join('')}</tbody></table>${!leads.length?'<div class="empty">No leads match this view.</div>':''}</div>`;
}
function paper(client,kind='welcome') {
  return `<div class="paper-stack"><div class="paper"><div class="paper-brand">ZanDop</div><div class="paper-line"></div><div class="paper-kicker">${kind.toUpperCase()} / PREPARED FOR YOU</div><div class="paper-title">${kind==='welcome'?'Your next<br>chapter<br>starts here.':kind==='plan'?'A clear plan.<br>A confident<br>next step.':'The next<br>opportunity.'}</div><div class="paper-shape"></div><div class="paper-client">${h(client)}<br><br>THOUGHTFUL WORK. REAL IMPACT.</div></div></div>`;
}
function activityItems(events) {
  return events.map(e=>`<div class="activity-item"><span class="activity-node">${icon(e.action.includes('document')?'file':e.action.includes('approval')?'shield':e.action.includes('delivery')?'code':'check')}</span><div class="activity-copy"><strong>${h(e.agent)}</strong> · ${h(e.action.replaceAll('.',' ').replaceAll('_',' '))}<small>${h(e.client||'Workspace')} ${e.detail.includes('Demo')?'· Demo action':''}</small></div><span class="activity-time">${age(e.created_at)}</span></div>`).join('');
}
function overview() {
  const date=new Intl.DateTimeFormat('en-US',{weekday:'long',month:'long',day:'numeric',timeZone:'Asia/Karachi'}).format(new Date());
  const doc=state.documents.find(d=>d.kind==='welcome');
  return heading(date,'Your agency, in motion.','A little less busywork. A lot more room to do great work.',button('Add a lead','new-lead','plus')+button('Run next cycle','run','play','primary'))+
  (state.mode!=='demo'&&!state.mailbox.enabled?`<div class="callout"><strong>${state.mailbox.verified?'Gmail is connected. Automation is paused.':'Your real workspace is open. Connect Gmail to begin.'}</strong><p>${state.mailbox.verified?'Enable automatic replies in Local setup when you are ready.':'There are no sample clients here. Connect and test your Gmail, then enable automatic replies. Add your own prospects in Lead finder.'}</p><a class="btn primary" href="#local-setup">Continue setup</a></div>`:'')+metrics()+`<section class="panel pipeline-panel"><div class="panel-header"><div><div class="panel-title"><h2>One connected client journey</h2><span class="tiny-label">11 specialist agents</span></div><p>From the first opportunity to the next introduction.</p></div><a href="#workflow" class="text-link">View workflow ${icon('arrow')}</a></div>${pipeline()}<div class="pipeline-bottom"><span>${icon('database')} Every step recorded in your CRM</span><span>${icon('shield')} Human approval where it matters</span></div></section>
  <div class="main-grid"><div class="stack"><section class="panel"><div class="panel-header"><div class="panel-title"><h2>On your radar</h2><span class="count-pill">${state.leads.length}</span></div><a href="#crm" class="text-link">All leads ${icon('arrow')}</a></div>${leadTable(state.leads.slice(0,5))}<div class="table-footer"><span>${Math.min(state.leads.length,5)} of ${state.leads.length} leads${state.mode==='demo'?' · Sample clients are labeled Demo':''}</span><a href="#crm">View all →</a></div></section><section class="panel"><div class="panel-header"><h2>Behind the scenes</h2><a href="#activity" class="text-link">Activity log ${icon('arrow')}</a></div><div class="activity-list">${activityItems(state.events.slice(0,3))}</div></section></div>
  <div class="stack right-stack"><section class="panel"><div class="panel-header"><div class="panel-title"><h2>A human touch</h2><span class="count-pill">${pending().length}</span></div><span class="tiny-label">YOUR CHECKPOINT</span></div><div class="approval-list">${pending().slice(0,2).map(a=>`<div class="approval-mini"><span class="approval-symbol">${icon(a.kind==='invoice'?'wallet':a.kind==='final_delivery'?'shield':'file')}</span><div class="approval-mini-content"><h3>${a.kind==='final_delivery'?'Ready for a final look':a.kind==='invoice'?'An invoice to approve':'A proposal to review'}</h3><p>${h(a.client)} · ${a.kind==='proposal'&&a.payload.amount?money(a.payload.amount,a.payload.currency):'Your approval comes first'}</p>${button('Review '+(a.kind==='final_delivery'?'delivery':a.kind==='invoice'?'invoice':'proposal'),'approval','arrow','small',`data-id="${a.id}"`)}</div></div>`).join('')||'<div class="empty">All clear. No pending approvals.</div>'}</div><div class="human-footer">${icon('lock')} Money, legal & final delivery stay with you.</div></section>
  <section class="panel"><div class="panel-header"><h2>First impressions, made to last.</h2>${icon('spark')}</div><div class="doc-feature"><div><span class="eyebrow" style="font-size:8px">THE CLIENT EXPERIENCE</span><h3>A warm welcome.<br>A clear way forward.</h3><p>Beautifully branded documents,<br>personalized for every client.</p>${doc?`<a class="btn ghost" href="/api/documents/${doc.id}/download" target="_blank" rel="noopener">Open welcome PDF ${icon('arrow')}</a>`:'<a href="#documents" class="text-link">Explore documents →</a>'}</div>${paper(doc?.client||'Your next client')}</div></section></div></div>
  <div class="bottom-banner"><span>${icon('shield')}<span><strong>${state.mode==='demo'?'Space to explore. Nothing sends.':'Your policies stay in control.'}</strong> ${state.mode==='demo'?'Demo clients, simulated actions, and real documents. Live outreach is disabled.':'Approvals, delivery checks and bounce protection guard external actions.'}</span></span><a href="#integrations" class="text-link">Manage integrations ${icon('arrow')}</a></div>`;
}
function workflow() {
  return heading('THE BIG PICTURE','Eleven specialists. One team.','A connected journey, with you at the moments that matter.',`<a class="btn" href="/workflow.svg" download="ZanDop-workflow.svg">${icon('download')} Download diagram</a>`+button('Run next cycle','run','play','primary'))+
  `<section class="panel workflow-hero"><div class="workflow-logo"><span class="brand-mark">z<span>→</span></span>ZanDop</div><p>Discover potential. Deliver exceptional. Grow through trust.</p>${pipeline()}<div class="workflow-notes"><span>↳ Welcome PDF triggers immediately on booking</span><span>↳ CRM audit trail spans every stage</span><span>↳ Final, financial & legal approvals stay human</span></div></section><div class="stage-grid">${state.stages.map(s=>`<section class="panel stage-card"><div class="stage-label-row"><span class="stage-index">${String(s.id).padStart(2,'0')}</span><strong>${h(s.name)}</strong></div><p>${h(s.description)}</p><div style="margin-top:14px">${button('View stage','stage','arrow','ghost small',`data-id="${s.id}"`)}</div></section>`).join('')}</div><div class="workflow-bottom"><span>Delivery specialists: Shopify · WooCommerce · WordPress · React · React Native · Content</span><span>↻ Weekly reports run throughout active projects</span></div>`;
}
function crm() {
  const leads=state.leads.filter(l=>(filter==='all'||l.service===filter)&&`${l.name} ${l.email} ${l.industry}`.toLowerCase().includes(search.toLowerCase()));
  return heading('RELATIONSHIPS, REMEMBERED','Good opportunities start here.','Every conversation, decision, and deliverable. One shared history.',button('Import CSV','import','download')+button('Add a lead','new-lead','plus','primary'))+
    `<div class="toolbar"><div class="tabs">${[['all','All leads'],['ecommerce','E-commerce'],['website','Websites'],['content','Content']].map(([id,label])=>`<button class="tab ${filter===id?'active':''}" data-action="filter" data-value="${id}">${label}</button>`).join('')}</div><label class="search-field">${icon('search')}<input id="lead-search" type="search" value="${h(search)}" placeholder="Search clients or companies" aria-label="Search leads"></label></div><section class="panel">${leadTable(leads,true)}<div class="table-footer"><span>${leads.length} leads in this view</span><span>All scores include their evidence in the lead record</span></div></section>`;
}
function documents() {
  const docs=state.documents.filter(d=>filter==='all'||d.kind===filter);
  return heading('THE ZANDOP EXPERIENCE','Make the first impression count.','Thoughtfully designed welcome guides, project blueprints, and research briefs.',`<span class="tiny-label">BRANDED. PERSONAL. VERSIONED.</span>`)+
  `<div class="toolbar"><div class="tabs">${[['all','All documents'],['welcome','Welcome guides'],['plan','Project plans'],['brief','Research briefs']].map(([id,label])=>`<button class="tab ${filter===id?'active':''}" data-action="filter" data-value="${id}">${label}</button>`).join('')}</div><span class="muted" style="font-size:10px">${docs.length} documents · PDF format</span></div><div class="card-grid">${docs.map(d=>`<article class="panel doc-card"><div class="doc-cover">${paper(d.client,d.kind)}</div><div class="doc-card-body"><h3>${h(d.client)} — ${h(d.title)}</h3><p>${h(labels[d.service])} · Version ${d.version} ${d.demo?'· Demo client':''}</p><div class="doc-card-actions">${badge(d.kind==='welcome'?'Welcome guide':d.kind==='plan'?'Project blueprint':'Research brief')}<a class="btn ghost small" href="/api/documents/${d.id}/download" target="_blank" rel="noopener">Open PDF ${icon('download')}</a></div></div></article>`).join('')}</div>${!docs.length?'<section class="panel empty"><strong>Your next chapter is on its way.</strong>Documents appear as research completes and client calls are booked.</section>':''}`;
}
function approvals() {
  const approvals=state.approvals.filter(a=>filter==='all'?a.status==='pending':a.status!=='pending');
  return heading('THE HUMAN CHECKPOINT','Your judgment. Their next step.','Review the exact scope, files, or amount before an agent takes action.')+
  `<div class="toolbar"><div class="tabs"><button class="tab ${filter==='all'?'active':''}" data-action="filter" data-value="all">Needs attention <span class="count-pill">${pending().length}</span></button><button class="tab ${filter==='history'?'active':''}" data-action="filter" data-value="history">Decision history</button></div><span class="muted" style="font-size:10px">Every decision is recorded</span></div><div class="card-grid">${approvals.map(a=>`<article class="panel approval-card"><div>${badge(a.kind.replaceAll('_',' '),'warning')} ${a.demo?badge('Demo','neutral'):''}</div><h3>${h(a.title)}</h3><p>${h(a.payload.scope||a.payload.description||a.payload.reason||'Review the deliverables and remaining quality checks before releasing this package to the client.')}</p>${a.payload.amount?`<div class="amount">${money(a.payload.amount,a.payload.currency)}</div>`:''}<p>${h(a.client)} · ${age(a.created_at)}</p>${a.status==='pending'?`<div class="approval-card-actions">${button('Review request','approval','arrow','primary',`data-id="${a.id}"`)}</div>`:badge(a.status,a.status==='rejected'?'danger':'success')}</article>`).join('')}</div>${!approvals.length?`<section class="panel empty">${icon('shield')}<strong>${filter==='all'?'A clear desk. A good feeling.':'Decisions will appear here.'}</strong>${filter==='all'?'No pending requests need your attention.':'Approved and rejected requests stay in your audit trail.'}</section>`:''}`;
}
function integrations() {
  return heading('YOUR CONNECTED TOOLKIT','The right tools, working together.','Provider choices are flexible. Set credentials securely in the server environment.')+
  `<div class="callout"><strong>${state.mode==='demo'?'You’re exploring in demo mode.':state.mode==='paused'?'Local automation is paused.':'Live mode is enabled.'}</strong> ${state.mode==='demo'?'No real messages or payment requests leave this demo. Use Local setup for Gmail. Client prices are edited manually, starting at $500 USD.':'Configured credentials indicate presence, not verified provider readiness.'} Secret values are never displayed here.</div>
  <div class="card-grid">${state.providers.map((p,i)=>`<section class="panel integration-card"><div style="display:flex;justify-content:space-between;align-items:flex-start"><div class="integration-icon">${icon(['send','calendar','wallet','chat','globe','spark','shield'][i])}</div>${badge(p.configured?'Configured':'Not connected',p.configured?'success':'neutral')}</div><h3>${h(p.name)}</h3><p>${h(p.provider)}</p>${p.requirements.map(r=>`<div class="requirement ${r.present?'present':''}">${h(r.name)} ${r.present?'· set':''}</div>`).join('')}</section>`).join('')}</div>
  ${state.mailbox.local_workspace||state.mode==='demo'?`<section class="panel" style="padding:24px;margin-top:22px"><h2>Personal Gmail outreach</h2><p>Daily limits, bounce protection and the two-project capacity are shown in <a href="#growth">Lead finder</a>. No paid sending platform is required.</p></section>`:`<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Outreach health</h2>${badge(state.outreach_health.paused?'Paused':state.outreach_health.checked_at?'Monitoring':'Awaiting telemetry',state.outreach_health.paused?'danger':'neutral')}</div><div style="padding:0 22px 22px;color:#9d87af;font-size:12px;line-height:1.9">${state.outreach_health.checked_at?`${state.outreach_health.sent||0} messages sent · ${state.outreach_health.bounced||0} bounces · Checked ${age(state.outreach_health.checked_at)}`:'Connect authenticated campaign events before enabling outreach. Cold sends require a verified warmed secondary domain and fresh bounce telemetry.'}<br>Personal and primary agency domains are blocked for cold outreach. The default bounce-rate pause threshold is 2%.</div></section>`}`;
}
function activity() {
  return heading('THE SHARED MEMORY','Nothing falls through the cracks.','Timestamped agent actions, human decisions, and document versions in one place.')+
  `<section class="panel activity-full">${state.events.map(e=>`<div class="activity-item"><span class="activity-node">${icon(e.agent==='Human'?'shield':'activity')}</span><div class="activity-copy"><strong>${h(e.agent)}</strong> · ${h(e.action)}<small>${h(e.client||'Workspace')} — ${h(e.detail.slice(0,210))}</small></div><span class="activity-time" title="${h(e.created_at)}">${age(e.created_at)}</span></div>`).join('')||'<div class="empty">Agent actions will appear here.</div>'}</section>`;
}

let previousFocus = null;
function modal(title,content,footer='',wide=false) {
  previousFocus=document.activeElement;
  document.getElementById('modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="modal-header"><h2 id="dialog-title">${title}</h2><button class="icon-button" data-action="close" aria-label="Close dialog">${icon('close')}</button></div><div class="modal-content">${content}</div>${footer?`<div class="modal-footer">${footer}</div>`:''}</section></div>`;
  document.body.style.overflow='hidden';
  setTimeout(()=>document.querySelector('.modal input,.modal button,.modal a')?.focus(),0);
}
function closeModal() {document.getElementById('modal-root').innerHTML='';document.body.style.overflow='';previousFocus?.focus();}
function newLead() {
  modal('A new opportunity',`<form id="lead-form" data-form="lead"><div class="form-grid"><label class="field">Business name<input name="name" required maxlength="120" placeholder="e.g. Studio Fern"></label><label class="field">Business contact email<input name="email" type="email" required placeholder="hello@business.com"></label><label class="field">Website<input name="website" type="url" placeholder="https://"></label><label class="field">Industry<input name="industry" placeholder="e.g. Home & living"></label><label class="field">Service<select name="service"><option value="ecommerce">E-commerce design & rebuild</option><option value="website">Website development</option><option value="content">Content writing</option></select></label><label class="field">Platform<select name="platform"><option>Shopify</option><option>WooCommerce</option><option>WordPress</option><option>React</option><option>React Native</option><option>Custom</option><option>Unknown</option></select></label><label class="field">Source<select name="source"><option value="manual">Manual / referral</option><option value="google_maps">Google Maps</option><option value="shopify_directory">Shopify directory</option><option value="woocommerce_directory">WooCommerce directory</option><option value="job_board">Job board</option><option value="linkedin">LinkedIn authorized export</option></select></label><label class="field">Brand voice<input name="brand_voice" placeholder="Warm, confident, thoughtful"></label><label class="field full">Project goals<textarea name="goals" placeholder="What would a successful project change for this business?"></textarea></label><label class="field full">SEO keywords<input name="keywords" placeholder="Comma-separated keywords"></label><label class="field full">Product CSV (for store projects)<textarea name="product_csv" placeholder="title,price,description&#10;Everyday Tote,48.00,A thoughtfully made essential"></textarea></label></div><label class="confirmation-check"><input type="checkbox" name="client_contact"><span>This is an existing client or inbound enquiry who expects a questionnaire. Skip cold outreach and start discovery.</span></label><p class="confirmation-text">This creates a real lead record. In demo mode, its live actions remain disabled.</p></form>`,button('Cancel','close',null)+`<button class="btn primary" type="submit" form="lead-form">${icon('plus')} Add lead</button>`);
}
function importLeads() {
  modal('Import your opportunities',`<p class="confirmation-text">Import an authorized CSV export from Google Maps, Shopify or WooCommerce directories, job boards, LinkedIn, or your own list. Up to 500 rows per import.</p><div class="code-block">name,email,website,service,platform,industry,source<br>Studio Fern,hello@fern.example,https://fern.example,ecommerce,Shopify,Home & living,shopify_directory</div><form id="import-form" data-form="import" style="margin-top:18px"><label class="field">CSV contents<textarea name="csv_text" required style="min-height:190px" placeholder="Paste your CSV here"></textarea></label></form>`,button('Cancel','close',null)+`<button class="btn primary" type="submit" form="import-form">Import leads ${icon('arrow')}</button>`);
}
async function openLead(id) {
  const result=await api(`/leads/${id}`), l=result.lead,d=l.details;
  const docs=state.documents.filter(doc=>doc.lead_id===id);
  modal(h(l.name),`<div class="detail-top">${logo(l)}<div><h3>${h(l.name)}</h3><span class="service ${l.service}"><span class="service-dot"></span>${labels[l.service]} · ${h(l.industry)}</span> ${l.demo?badge('Demo client','neutral'):''}</div></div><div class="detail-grid"><div class="detail-stat"><small>Current stage</small><strong>${l.stage.toString().padStart(2,'0')} / ${h(state.stages[l.stage-1].name)}</strong></div><div class="detail-stat"><small>Status</small><strong>${h(statusLabels[l.status]||l.status)}</strong></div><div class="detail-stat"><small>Contact</small><strong>${h(l.email)}</strong></div><div class="detail-stat"><small>Opportunity score</small><strong>${l.score} / 100 ${d.score_components?`· revenue ${d.score_components.revenue}, traffic ${d.score_components.traffic}, platform ${d.score_components.platform}, visual ${d.score_components.visual_opportunity}`:''}</strong></div></div>${d.blocker?`<div class="callout"><strong>Needs attention:</strong> ${h(d.blocker)}</div>`:''}<div class="detail-actions">${localClientButtons(l)}${button('Run next stage','advance','play','primary',`data-id="${id}"`)}${button('Add call notes','notes','file','',`data-id="${id}"`)}${l.demo?button('Simulate booking','demo-book','calendar','',`data-id="${id}"`):button('Book a call','book','calendar','',`data-id="${id}"`)}${l.demo&&d.invoice&&!d.paid_at?button('Simulate payment','demo-pay','wallet','',`data-id="${id}"`):''}${d.delivery?`<a class="btn" href="/api/leads/${id}/artifact">${icon('download')} Delivery ZIP</a>`:''}${d.delivery?.preview?`<a class="btn" href="/api/leads/${id}/preview" target="_blank" rel="noopener">${icon('globe')} Draft preview</a>`:''}</div>${d.research?`<section class="detail-section"><h4>Research brief</h4><p>${h(d.research.flaw||'No substantiated flaw detected.')}</p><div class="detail-grid"><div class="detail-stat"><small>Platform</small><strong>${h(d.research.platform)}</strong></div><div class="detail-stat"><small>HTML response / mobile viewport</small><strong>${h(d.research.load_seconds??'Unknown')} s / ${h(d.research.mobile_viewport??'Unknown')}</strong></div></div><p class="muted">${h(d.research.evidence)}</p></section>`:''}${docs.length?`<section class="detail-section"><h4>Client documents</h4><div class="detail-actions">${docs.map(doc=>`<a class="btn small" href="/api/documents/${doc.id}/download" target="_blank" rel="noopener">${icon('file')}${h(doc.kind)} · v${doc.version}</a>`).join('')}</div></section>`:''}${d.call_notes?`<section class="detail-section"><h4>Call notes</h4><p>${h(d.call_notes)}</p></section>`:''}${d.quality?`<section class="detail-section"><h4>Quality review</h4>${qualityRows(d.quality)}</section>`:''}<section class="detail-section"><h4>Conversation history</h4>${result.messages.map(m=>`<div class="message"><h4>${h(m.subject)} ${badge(m.status,'neutral')}</h4><p>${h(m.body)}</p><small>${h(m.direction)} · ${age(m.created_at)}</small></div>`).join('')||'<p>No messages yet.</p>'}</section><section class="detail-section"><h4>Recent activity</h4>${activityItems(result.events.slice(0,8))}</section>`,button('Done','close',null),true);
}
function qualityRows(checks) {return checks.map(c=>`<div class="check-row">${icon(c.status==='passed'?'check':'shield')}<span>${h(c.check)}<small>${h(c.detail)}</small></span>${badge(c.status,c.status==='passed'?'success':c.status==='failed'?'danger':'warning')}</div>`).join('');}
function openApproval(id) {
  const a=state.approvals.find(a=>a.id===id),p=a.payload;
  modal('Your approval comes first',`<div>${badge(a.kind.replaceAll('_',' '),'warning')} ${a.demo?badge('Simulated action','neutral'):''}</div><h3 style="font-size:22px;font-weight:550;line-height:1.4">${h(a.title)}</h3>${p.amount?`<div class="detail-stat" style="margin:18px 0"><small>Exact amount to approve</small><strong style="font-size:30px">${money(p.amount,p.currency)}</strong><p class="confirmation-text">${h(p.recipient||clientName(a.lead_id))} · ${h(p.scope||p.description)}</p></div>`:''}${p.action?`<p class="confirmation-text">${h(p.action)}</p>`:''}${p.body?`<div class="message"><h4>${h(p.subject)}</h4><p>${h(p.body)}</p></div>`:''}${approvalAttachment(p)}${p.checks?`<section class="detail-section"><h4>Review these checks before approving</h4>${qualityRows(p.checks)}<div class="detail-actions"><a class="btn" href="/api/leads/${a.lead_id}/artifact">${icon('download')} Download package</a><a class="btn" href="/api/leads/${a.lead_id}/preview" target="_blank" rel="noopener">${icon('globe')} Open draft</a></div></section>`:''}${p.request?`<div class="message"><p>${h(p.request)}</p></div><p class="confirmation-text">${h(p.reason)}</p>`:''}<label class="confirmation-check"><input id="approval-confirm" type="checkbox"><span>I have reviewed this exact ${a.kind.replaceAll('_',' ')}${p.checks?' and completed the remaining browser, scope, and copy checks':''}. ${a.demo?'I approve the simulated action.':'I authorize the described external action.'}</span></label>`,button('Reject / hold','reject','close','danger',`data-id="${id}"`)+button(a.demo?'Approve simulation':'Approve action','approve','check','primary',`data-id="${id}"`),true);
}
function stageModal(id) {
  const s=state.stages[id-1],leads=state.leads.filter(l=>l.stage===id);
  modal(`${String(id).padStart(2,'0')} / ${h(s.name)}`,`<p class="confirmation-text">${h(s.description)}</p>${leads.length?leadTable(leads):'<div class="empty">No clients at this stage yet.</div>'}${id===6?'<div class="callout">The welcome guide is generated as soon as a call is booked, even before the client reaches this stage. The project plan follows the call notes.</div>':''}${id===5?'<div class="callout">All agents log actions immediately. This stage consolidates the records for the delivery handoff.</div>':''}`,button('Done','close',null),true);
}
function notesModal(id) {
  const lead=state.leads.find(l=>l.id===id);
  modal(`Call notes / ${h(lead.name)}`,`<form id="notes-form" data-form="notes" data-id="${id}"><label class="field">Decisions, goals, and agreed direction<textarea name="notes" required minlength="10" maxlength="10000" style="min-height:220px" placeholder="Paste your call notes or transcript here…">${h(lead.details.call_notes||'')}</textarea></label><p class="confirmation-text">The client success agent uses these notes to personalize the project plan.</p></form>`,button('Cancel','close',null)+`<button class="btn primary" type="submit" form="notes-form">Save call notes ${icon('check')}</button>`);
}
function bookingModal(id) {
  modal('Book a confirmed time',`<form id="book-form" data-form="booking" data-id="${id}"><div class="form-grid"><label class="field full">Start time, including UTC offset<input name="start" required placeholder="2026-10-20T14:00:00+05:00"></label><label class="field full">Client timezone<input name="timezone" required placeholder="Asia/Karachi"></label><label class="confirmation-check field full"><span><input name="confirmed" type="checkbox" required> The client has confirmed this time and timezone.</span></label></div><p class="confirmation-text">In a local workspace, this records a slot already confirmed with the client and sends the welcome guide. Add the event and video link to your own calendar. External calendar creation is optional.</p></form>`,button('Cancel','close',null)+`<button class="btn primary" type="submit" form="book-form">Book call ${icon('calendar')}</button>`);
}

document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-action]'); if(!el) return;
  const action=el.dataset.action,id=el.dataset.id;
  if(busy&&!['close','lead','stage','approval'].includes(action)) return;
  try {
    if(action==='close') return closeModal();
    if(action==='new-lead') return newLead();
    if(action==='import') return importLeads();
    if(action==='lead') return await openLead(id);
    if(action==='approval') return openApproval(id);
    if(action==='stage') return stageModal(Number(id));
    if(action==='filter') {filter=el.dataset.value;render();return;}
    if(action==='notes') return notesModal(id);
    if(action==='book') return bookingModal(id);
    if(action==='approve'&&!document.getElementById('approval-confirm').checked) return toast('Review the request and select the approval checkbox first.',true);
    busy=true; el.disabled=true;
    if(action==='run') {const result=await api('/run',{method:'POST'});await refresh();toast(`Cycle complete. ${result.processed} leads checked; approval gates remain in place.`);}
    if(action==='advance') {await api(`/leads/${id}/advance`,{method:'POST'});await refresh();await openLead(id);toast('Agent step recorded in the CRM.');}
    if(action==='approve'||action==='reject') {await api(`/approvals/${id}`,{method:'POST',body:JSON.stringify({decision:action==='approve'?'approve':'reject',confirmation:id})});closeModal();await refresh();toast(action==='approve'?'Approval recorded. The authorized action has been queued.':'Request held. The decision is in the audit trail.');}
    if(action==='demo-book') {await api('/demo/events',{method:'POST',body:JSON.stringify({id:crypto.randomUUID(),type:'call.booked',lead_id:id,data:{start:new Date(Date.now()+86400000).toISOString()}})});await refresh();await openLead(id);toast('Demo booking received. Personalized welcome PDF created.');}
    if(action==='demo-pay') {const inv=state.leads.find(l=>l.id===id).details.invoice;await api('/demo/events',{method:'POST',body:JSON.stringify({id:crypto.randomUUID(),type:'invoice.paid',lead_id:id,data:{invoice_id:inv.id,amount_paid:inv.amount,currency:inv.currency}})});await refresh();await openLead(id);toast('Demo payment recorded. No money moved.');}
  } catch(error) {toast(error.message,true);} finally {busy=false;el.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-form]');if(!form)return;event.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  const submit=document.querySelector(`[form="${form.id}"]`)||form.querySelector('button[type=submit]');
  if(submit)submit.disabled=true;
  try {
    if(form.dataset.form==='login') {sessionStorage.setItem('zandop-token',data.token);await api('/session',{method:'POST'});await refresh();return;}
    if(form.dataset.form==='lead') {const {brand_voice,goals,keywords,product_csv,client_contact,...lead}=data;await api('/leads',{method:'POST',body:JSON.stringify({...lead,details:{brand_voice,goals,client_contact:!!client_contact,keywords:keywords.split(',').map(s=>s.trim()).filter(Boolean),product_csv}})});toast('Lead added. Ready for discovery and research.');}
    if(form.dataset.form==='import') {const result=await api('/leads/import',{method:'POST',body:JSON.stringify(data)});toast(`${result.imported.length} leads imported.`);}
    if(form.dataset.form==='notes') {await api(`/leads/${form.dataset.id}/notes`,{method:'POST',body:JSON.stringify(data)});toast('Call notes saved.');}
    if(form.dataset.form==='booking') {await api(`/leads/${form.dataset.id}/book`,{method:'POST',body:JSON.stringify({start:data.start,timezone:data.timezone,client_confirmed:!!data.confirmed})});toast('Confirmed booking queued.');}
    closeModal();await refresh();
  }catch(error){toast(error.message,true);}finally{if(submit)submit.disabled=false;}
});
document.addEventListener('input',event=>{
  const form=event.target.closest('form');if(form)form.dataset.dirty='true';
  if(event.target.id==='lead-search') {const position=event.target.selectionStart;search=event.target.value;render();const input=document.getElementById('lead-search');input.focus();if(input.type!=='search')input.setSelectionRange(position,position);}
});
document.addEventListener('change',event=>{
  const form=event.target.closest('form');if(form)form.dataset.dirty='true';
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape') {closeModal();document.getElementById('sidebar').classList.remove('open');}
  if(event.key==='Enter'&&event.target.matches('tr[data-action]')) event.target.click();
  if(event.key==='Tab'&&document.querySelector('.modal')) {
    const elements=[...document.querySelectorAll('.modal button:not([disabled]),.modal input,.modal select,.modal textarea,.modal a[href]')];
    const first=elements[0],last=elements[elements.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }
});
document.getElementById('menu-toggle').addEventListener('click',()=>document.getElementById('sidebar').classList.toggle('open'));
document.getElementById('notification-button').addEventListener('click',()=>location.hash='approvals');
window.addEventListener('hashchange',()=>{filter='all';search='';document.getElementById('sidebar').classList.remove('open');render();});
refresh().catch(error=>toast(error.message,true));
setInterval(()=>{if(state&&!busy&&!editingForm()&&!document.querySelector('.modal'))refresh(true).catch(()=>{});},30000);
