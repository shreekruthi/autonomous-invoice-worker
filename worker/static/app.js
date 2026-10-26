/* All untrusted data is rendered with textContent. No HTML interpolation. */
const $ = id => document.getElementById(id);
let selected = null, busy = false;
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
async function api(path, body, reviewer = false) {
  const res = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', Authorization: `Bearer ${$(reviewer ? 'reviewer-token' : 'worker-token').value}`},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (!res.ok) { let data; try { data = await res.json(); } catch { data = {}; } throw Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`); }
  return res.json();
}
function badge(status) { return el('span', status.replaceAll('_', ' '), `pill ${status}`); }
function feedback(message) { $('feedback').textContent = message; }
function money(minor) { return new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'}).format(minor / 100); }
function kv(data) { const dl = el('dl', undefined, 'key-value'); for (const [k,v] of Object.entries(data)) { dl.append(el('dt',k),el('dd',String(v))); } return dl; }
function button(text, handler, cls='secondary') { const b = el('button',text,cls); b.onclick = async () => { b.disabled=true; try { await handler(); } catch(e) {feedback(e.message);} finally {b.disabled=false;} }; return b; }
async function connect() {
  try { const c = await api('/api/config'); $('mode').textContent = c.mode === 'demo' ? 'Deterministic demo' : `LLM · ${c.mode} · ${c.model}`;
    $('mode-note').textContent = c.mode === 'demo' ? 'DEMO MODE — A deterministic workflow exercises real APIs and database writes. It does not demonstrate LLM autonomy.' : 'LIVE LLM MODE — The model selects tools after each observation. Application code enforces validation, approvals and verification.';
    $('inject').disabled = !c.faults_enabled;
    $('inject').title = c.faults_enabled ? 'Apply one inbox outage and one post-commit lost response' : 'Start server with ENABLE_FAULTS=true';
    await refresh(); feedback('');
  } catch(e) { feedback(e.message); $('mode').textContent='Connection needed'; }
}
async function refresh() {
  const tasks = await api('/api/tasks'); $('tasks').replaceChildren();
  if (!tasks.length) $('tasks').append(el('p','No tasks yet.','empty'));
  for (const t of tasks) { const b=el('button',undefined,`task-item ${selected===t.id?'selected':''}`); b.append(el('p',t.goal),badge(t.status),el('small',`${t.mode} · ${t.steps} actions · ${t.id.slice(0,8)}`)); b.onclick=()=>openTask(t.id).catch(e=>feedback(e.message)); $('tasks').append(b); }
  await Promise.all([loadLedger(),loadInbox()]);
}
async function openTask(id) { selected=id; await renderTask(); await refresh(); }
async function renderTask() {
  if (!selected) return;
  const [t,events] = await Promise.all([api(`/api/tasks/${selected}`),api(`/api/tasks/${selected}/events`)]);
  const root=$('trace'); root.replaceChildren(); const heading=el('div',undefined,'task-heading'); heading.append(el('h2',t.goal),badge(t.status)); root.append(heading,el('p',t.summary || 'Execution in progress…','task-summary'));
  const m=t.memory; if(m.plan) {const list=el('ol',undefined,'plan'); m.plan.forEach(p=>list.append(el('li',p))); root.append(list);}
  if(t.status==='awaiting_approval') { const box=el('div',undefined,'review'); box.append(el('h3','Human decision required'),el('p','Review the exact staged invoice. The agent cannot make this decision.'));
    box.append(kv({'Invoice':m.prepared.invoice_number,'Vendor':m.prepared.vendor_id,'Amount':money(m.prepared.amount_minor),'Due':m.prepared.due_date,'Source SHA-256':m.prepared.source_sha256}));
    for(const decision of ['approve','reject']) box.append(button(decision==='approve'?'Approve & resume':'Reject',async()=>{
      await api(`/api/tasks/${selected}/review`,{decision,reviewer:$('reviewer-name').value},true); await openTask(selected);
    },decision==='approve'?'':'reject')); root.append(box);
  }
  if(m.verified) { const box=el('div',undefined,'evidence'); box.append(el('h3','✓ Independent read-back verified'),kv({'Ledger ID':m.verified.record_id,'Fingerprint':m.verified.fingerprint,'Source hash':m.verified.source_sha256,'Fields checked':m.verified.fields_checked.join(', '),'Verified at':m.verified.verified_at})); root.append(box); }
  const bar=el('div',undefined,'toolbar'); bar.append(button('Download evidence',async()=>{const data=await api(`/api/tasks/${selected}/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download=`task-${selected}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
  if(['needs_input','awaiting_approval','failed','interrupted'].includes(t.status)) bar.append(button('Clarify using request above',async()=>{const updated=await api(`/api/tasks/${selected}/clarify`,{goal:$('goal').value});await openTask(updated.id);}));
  if(['failed','interrupted'].includes(t.status)) bar.append(button('Resume from checkpoint',async()=>{await api(`/api/tasks/${selected}/resume`,{});await openTask(selected);}));
  root.append(bar,el('h3',`Audit trail · ${events.length} events`)); const list=el('ol',undefined,'timeline');
  for(const e of events) {const li=el('li',undefined,`event ${e.kind}`),d=el('details'),s=el('summary');s.append(el('time',new Date(e.created_at).toLocaleTimeString()),document.createTextNode(`${e.kind.replaceAll('_',' ')}${e.data.tool?' · '+e.data.tool:''}${e.data.attempt?' · attempt '+e.data.attempt:''}`));d.append(s,el('pre',JSON.stringify(e.data,null,2)));li.append(d);list.append(li);} root.append(list);
}
function table(headers, rows) {const t=el('table'),head=el('tr');headers.forEach(h=>head.append(el('th',h)));const thead=el('thead');thead.append(head);t.append(thead);const body=el('tbody');for(const row of rows){const tr=el('tr');for(const cell of row){const td=el('td');td.append(cell instanceof Node?cell:document.createTextNode(String(cell)));tr.append(td);}body.append(tr);}t.append(body);return t;}
async function loadLedger() {const rows=await api('/api/records');$('ledger').replaceChildren(el('h3',`${rows.length} saved invoice${rows.length===1?'':'s'}`));if(rows.length)$('ledger').append(table(['Invoice','Vendor','Amount','Due','Ledger ID'],rows.map(r=>[r.payload.invoice_number,r.payload.vendor_id,money(r.payload.amount_minor),r.payload.due_date,r.id])));else $('ledger').append(el('p','The ledger is empty. Run a task to create a real record.','muted'));}
async function loadInbox() {const rows=await api('/api/inbox');$('inbox').replaceChildren(el('h3','Synthetic company inbox'));$('inbox').append(table(['Source','Vendor','Issue date','Invoice text'],rows.map(r=>{const d=el('details');d.append(el('summary',r.subject),el('pre',r.body));return[r.id,r.vendor_id,r.issued_at,d];})));}
document.querySelectorAll('[data-goal]').forEach(b=>b.onclick=()=>{$('goal').value=b.dataset.goal;$('goal').focus();});
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.tab-content').forEach(x=>x.hidden=x.id!==b.dataset.tab);});
$('task-form').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;$('run').disabled=true;feedback('Working… You can inspect the company ledger while this request runs.');try{const task=await api('/api/tasks',{goal:$('goal').value});await openTask(task.id);feedback('');}catch(e){feedback(e.message);}finally{busy=false;$('run').disabled=false;}};
$('inject').onclick=async()=>{try{for(const name of ['read_invoice','record_after'])await api('/api/faults',{name,count:1},true);feedback('One read outage and one lost write response armed. Run a new invoice task to see recovery.');}catch(e){feedback(e.message);}};
$('refresh').onclick=async()=>{try{await refresh();await renderTask();}catch(e){feedback(e.message);}};
$('connect').onclick=connect;
connect();
