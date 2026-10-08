const $ = selector => document.querySelector(selector);
let token = localStorage.agentToken || '';
let canWrite = false;
let currentView = 'overview';

const api = async (path, options = {}) => {
  const response = await fetch('/api/v1' + path, {headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})}, ...options});
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(data.message || data.error || 'Request failed');
  return data;
};
const esc = value => String(value || '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const dateTime = value => value ? new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value)) : 'Not recorded';
const statusBadge = status => `<span class="status-badge ${esc(status || '').toLowerCase()}">${esc(status || 'active')}</span>`;
const empty = (title, text) => `<div class="panel empty-state"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
const loading = () => '<div class="panel empty-state"><h3>Loading workspace data</h3><p>Please wait a moment.</p></div>';
function notice(text, isError = false) { const target = $('#notice'); target.textContent = text; target.style.color = isError ? 'var(--danger)' : 'var(--accent)'; if (text) setTimeout(() => { if (target.textContent === text) target.textContent = ''; }, 4200); }
function setBusy(button, busy, text) { if (!button) return; button.disabled = busy; button.dataset.label ||= button.textContent; button.textContent = busy ? text : button.dataset.label; }
function setActive(view) { document.querySelectorAll('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view)); }
function showLogin() { $('#landing').hidden = true; $('#login').hidden = false; $('#app').hidden = true; }
function showLanding() { $('#landing').hidden = false; $('#login').hidden = true; $('#app').hidden = true; }

async function login(event) {
  event.preventDefault();
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  const spinner = submit.querySelector('.button-loader');
  setBusy(submit, true, 'Verifying access...'); spinner.hidden = false; $('#login-error').textContent = '';
  try {
    const result = await api('/auth/login', {method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});
    token = result.access_token; localStorage.agentToken = token; await boot();
  } catch (error) { $('#login-error').textContent = error.message; }
  finally { setBusy(submit, false); spinner.hidden = true; }
}
async function boot() {
  try {
    const identity = await api('/admin/context');
    canWrite = ['owner', 'admin', 'manager'].includes(identity.role);
    $('#landing').hidden = true; $('#login').hidden = true; $('#app').hidden = false;
    $('#tenant-name').textContent = identity.tenant.name;
    await show('overview');
  } catch { localStorage.removeItem('agentToken'); token = ''; showLogin(); }
}
function details(title, value) { return `<div class="panel"><p class="eyebrow">Record intelligence</p><h3>${esc(title)}</h3><pre>${esc(JSON.stringify(value, null, 2))}</pre></div>`; }
function bindCrud(view, fields, root, items) {
  const create = canWrite ? `<form class="panel" id="create"><p class="eyebrow">New record</p><h3>Add ${esc(view.slice(0, -1))}</h3><label>${esc(fields[0])}<input name="${fields[0]}" placeholder="Enter ${fields[0]}" required></label><label>${esc(fields[1])}<textarea name="${fields[1]}" placeholder="Add approved ${fields[1]}" required></textarea></label><button type="submit">Publish record</button></form>` : '';
  const list = items.length ? items.map(item => `<div class="row"><span><b>${esc(item[fields[0]])}</b><br><small>${esc(item[fields[1]])}</small></span>${canWrite ? `<button class="danger delete" data-id="${item._id}">Delete</button>` : statusBadge(item.status)}</div>`).join('') : empty(`No ${view} yet`, canWrite ? 'Create your first approved record to give the agent more context.' : 'This workspace has not added any records yet.');
  root.innerHTML = `<div class="page-heading"><p class="eyebrow">Knowledge operations</p><h2>${esc(view)}</h2><p>Maintain the approved information used by the website agent.</p></div>${create}<div class="panel"><h3>Published records</h3>${list}</div>`;
  if (!canWrite) return;
  $('#create').onsubmit = async event => { event.preventDefault(); const button = event.currentTarget.querySelector('button'); setBusy(button, true, 'Publishing...'); try { await api('/admin/' + view, {method: 'POST', body: JSON.stringify({...Object.fromEntries(new FormData(event.currentTarget)), status: 'published'})}); notice('Record published.'); await show(view); } catch (error) { notice(error.message, true); setBusy(button, false); } };
  root.querySelectorAll('.delete').forEach(button => button.onclick = async () => { if (!confirm('Delete this record?')) return; await api('/admin/' + view + '/' + button.dataset.id, {method: 'DELETE'}); notice('Record removed.'); show(view); });
}
async function showAppointments(root) {
  const items = await api('/admin/appointments');
  root.innerHTML = `<div class="page-heading"><p class="eyebrow">Scheduling operations</p><h2>Appointments</h2><p>Monitor meetings confirmed through the website agent.</p></div><div class="panel"><div class="list-title"><h3>All appointments</h3><span>${items.length} total</span></div>${items.length ? items.map(item => `<div class="row appointment-row"><span><b>${statusBadge(item.status)} ${esc(dateTime(item.start_at))}</b><br><small>${esc(item.timezone || 'Configured tenant time')}</small></span><button class="detail" data-id="${item._id}">Review</button></div>`).join('') : empty('No appointments yet', 'Confirmed visitor meetings will appear here.')}</div><div id="details"></div>`;
  root.querySelectorAll('.detail').forEach(button => button.onclick = async () => {
    $('#details').innerHTML = loading();
    const appointment = await api('/admin/appointments/' + button.dataset.id);
    const controls = canWrite && appointment.status !== 'cancelled' ? `<div class="panel inline"><button id="admin-cancel" class="danger" type="button">Cancel appointment</button><input id="admin-time" type="datetime-local" aria-label="New appointment time"><button id="admin-reschedule" type="button">Reschedule</button></div>` : '';
    $('#details').innerHTML = details('Appointment details and history', appointment) + controls;
    if (!canWrite || appointment.status === 'cancelled') return;
    $('#admin-cancel').onclick = async () => { if (!confirm('Cancel this appointment?')) return; await api('/admin/appointments/' + appointment._id + '/cancel', {method: 'POST'}); notice('Appointment cancelled.'); show('appointments'); };
    $('#admin-reschedule').onclick = async () => { const value = $('#admin-time').value; if (!value) return notice('Choose a new date and time.', true); await api('/admin/appointments/' + appointment._id + '/reschedule', {method: 'POST', body: JSON.stringify({start_at: new Date(value).toISOString()})}); notice('Appointment rescheduled.'); show('appointments'); };
  });
}
async function showAvailability(root) {
  const [hours, blocks] = await Promise.all([api('/admin/business-hours'), api('/admin/availability/blocked')]);
  const byDay = new Map(hours.map(hour => [hour.weekday, hour])); const names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const hourRows = Array.from({length: 7}, (_, weekday) => { const hour = byDay.get(weekday) || {enabled: false, start_time: '09:00', end_time: '17:00'}; return `<div class="row"><label><input type="checkbox" data-enabled="${weekday}" ${hour.enabled ? 'checked' : ''}> ${names[weekday]}</label><input type="time" data-start="${weekday}" value="${esc(hour.start_time)}"><input type="time" data-end="${weekday}" value="${esc(hour.end_time)}"></div>`; }).join('');
  const hoursEditor = canWrite ? `<form id="hours-form" class="panel"><p class="eyebrow">Scheduling policy</p><h3>Working hours</h3>${hourRows}<button type="submit">Save working hours</button></form>` : `<div class="panel"><h3>Working hours</h3>${hours.map(hour => `<div class="row"><span>${names[hour.weekday]}<br><small>${esc(hour.start_time)} to ${esc(hour.end_time)}</small></span>${statusBadge(hour.enabled ? 'enabled' : 'disabled')}</div>`).join('') || empty('No working hours', 'No availability windows are currently configured.')}</div>`;
  const blockForm = canWrite ? '<form id="block-form" class="panel"><p class="eyebrow">Scheduling control</p><h3>Block a period</h3><label>Start time<input name="start_at" type="datetime-local" required></label><label>End time<input name="end_at" type="datetime-local" required></label><button type="submit">Add blocked period</button></form>' : '';
  root.innerHTML = `<div class="page-heading"><p class="eyebrow">Availability intelligence</p><h2>Availability</h2><p>Define working windows and protect unavailable periods from booking.</p></div>${hoursEditor}${blockForm}<div class="panel"><div class="list-title"><h3>Blocked periods</h3><span>${blocks.length} active</span></div>${blocks.length ? blocks.map(block => `<div class="row"><span><b>${esc(dateTime(block.start_at))}</b><br><small>Until ${esc(dateTime(block.end_at))}</small></span>${canWrite ? `<button class="danger unblock" data-id="${block._id}">Remove</button>` : ''}</div>`).join('') : empty('No blocked periods', 'Your current working-hour windows are available for scheduling.')}</div>`;
  if (!canWrite) return;
  $('#hours-form').onsubmit = async event => { event.preventDefault(); const hours = Array.from({length: 7}, (_, weekday) => ({weekday, enabled: $(`[data-enabled="${weekday}"]`).checked, start_time: $(`[data-start="${weekday}"]`).value, end_time: $(`[data-end="${weekday}"]`).value})); if (hours.some(item => !item.start_time || !item.end_time || item.start_time >= item.end_time)) return notice('Each day needs a valid start and end time.', true); await api('/admin/business-hours', {method: 'PUT', body: JSON.stringify({hours})}); notice('Working hours saved.'); show('availability'); };
  $('#block-form').onsubmit = async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); data.start_at = new Date(data.start_at).toISOString(); data.end_at = new Date(data.end_at).toISOString(); await api('/admin/availability/blocked', {method: 'POST', body: JSON.stringify(data)}); notice('Blocked period added.'); show('availability'); };
  root.querySelectorAll('.unblock').forEach(button => button.onclick = async () => { await api('/admin/availability/blocked/' + button.dataset.id, {method: 'DELETE'}); notice('Blocked period removed.'); show('availability'); });
}
async function show(view) {
  currentView = view; setActive(view); const root = $('#view'); root.innerHTML = loading(); $('#app').classList.remove('nav-open');
  try {
    if (view === 'overview') { const data = await api('/admin/analytics'); root.innerHTML = `<div class="page-heading"><p class="eyebrow">Command overview</p><h2>Website agent performance</h2><p>Real-time tenant-scoped activity from your website operation.</p></div><div class="grid">${[['Conversations', data.total_conversations], ['Leads', data.total_leads], ['Appointments', data.total_appointments], ['Conversion', data.conversion_rate + '%']].map(([label, value]) => `<div class="metric"><small>${label}</small><b>${value}</b></div>`).join('')}</div><div class="dashboard-split"><div class="panel"><h3>Recent leads</h3>${data.recent_leads?.length ? data.recent_leads.map(lead => `<div class="row"><span><b>${esc(lead.name || lead.email || 'Website visitor')}</b><br><small>${esc(lead.requirement || lead.email || '')}</small></span>${statusBadge(lead.status)}</div>`).join('') : empty('No recent leads', 'Qualified visitors will appear here.')}</div><div class="panel"><h3>Upcoming appointments</h3>${data.recent_appointments?.length ? data.recent_appointments.map(appointment => `<div class="row"><span><b>${esc(dateTime(appointment.start_at))}</b><br><small>${esc(appointment.status)}</small></span>${statusBadge(appointment.status)}</div>`).join('') : empty('No appointments yet', 'Booked meetings will appear here.')}</div></div>`; return; }
    if (view === 'business') { const data = await api('/admin/business'); root.innerHTML = `<div class="page-heading"><p class="eyebrow">Tenant configuration</p><h2>Business profile</h2><p>Keep the agent's identity and contact information current.</p></div><form class="panel profile-form" id="business-form"><label>Business name<input name="name" value="${esc(data.name)}" ${canWrite ? '' : 'disabled'}></label><label>Contact email<input name="contact_email" type="email" value="${esc(data.contact_email)}" ${canWrite ? '' : 'disabled'}></label><label>Timezone<input name="timezone" value="${esc(data.timezone || 'Asia/Kolkata')}" ${canWrite ? '' : 'disabled'}></label><label class="wide">Business description<textarea name="description" ${canWrite ? '' : 'disabled'}>${esc(data.description)}</textarea></label>${canWrite ? '<button type="submit">Save business profile</button>' : statusBadge('read only')}</form>`; if (canWrite) $('#business-form').onsubmit = async event => { event.preventDefault(); const button = event.currentTarget.querySelector('button'); setBusy(button, true, 'Saving...'); try { await api('/admin/business', {method: 'PATCH', body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); notice('Business profile saved.'); setBusy(button, false); } catch (error) { notice(error.message, true); setBusy(button, false); } }; return; }
    if (['services', 'faqs', 'knowledge'].includes(view)) { const fields = view === 'services' ? ['title', 'description'] : view === 'faqs' ? ['question', 'answer'] : ['title', 'content']; bindCrud(view, fields, root, await api('/admin/' + view)); return; }
    if (view === 'appointments') return showAppointments(root);
    if (view === 'availability') return showAvailability(root);
    if (['conversations', 'leads'].includes(view)) { const items = await api('/admin/' + view); root.innerHTML = `<div class="page-heading"><p class="eyebrow">Visitor intelligence</p><h2>${view}</h2><p>Review the context generated by real website interactions.</p></div><div class="panel"><div class="list-title"><h3>${view === 'leads' ? 'Lead pipeline' : 'Conversation history'}</h3><span>${items.length} records</span></div>${items.length ? items.map(item => `<div class="row"><span><b>${esc(item.name || item.email || item.visitor_id || 'Website visitor')}</b><br><small>${esc(item.requirement || item.email || dateTime(item.updated_at))}</small></span><div>${item.status ? statusBadge(item.status) : ''} <button class="detail" data-id="${item._id}">Review</button></div></div>`).join('') : empty(`No ${view} yet`, 'New website activity will appear here.')}</div><div id="details"></div>`; root.querySelectorAll('.detail').forEach(button => button.onclick = async () => { $('#details').innerHTML = loading(); $('#details').innerHTML = details(view === 'leads' ? 'Lead details' : 'Conversation transcript', await api('/admin/' + view + '/' + button.dataset.id)); }); return; }
    if (view === 'embed') { const data = await api('/admin/widget-config'); const key = data.public_key || 'demo_black_intel_widget_key'; root.innerHTML = `<div class="page-heading"><p class="eyebrow">Deployment control</p><h2>Widget settings</h2><p>Install the tenant-scoped website agent with the snippet below.</p></div><div class="dashboard-split"><div class="panel"><h3>Embed snippet</h3><textarea readonly>&lt;script src="${location.origin}/widget-loader.js" data-widget-key="${key}"&gt;&lt;/script&gt;</textarea><p class="muted">Public key: <code>${esc(key)}</code></p></div><div class="panel"><h3>Widget status</h3><p>${statusBadge(data.enabled === false ? 'disabled' : 'enabled')}</p><p class="muted">The widget remains isolated from the host website and requests server-side tenant access using its public key.</p></div></div>`; }
  } catch (error) { root.innerHTML = `<div class="panel empty-state"><h3>Unable to load this view</h3><p>${esc(error.message)}</p><button class="detail" id="retry-view">Try again</button></div>`; $('#retry-view').onclick = () => show(currentView); }
}

$('#login-form').onsubmit = login;
document.querySelectorAll('.open-login').forEach(button => button.onclick = showLogin);
$('#back-home').onclick = showLanding;
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => show(button.dataset.view));
$('#mobile-nav').onclick = () => $('#app').classList.toggle('nav-open');
$('#sign-out').onclick = () => { localStorage.removeItem('agentToken'); token = ''; canWrite = false; showLanding(); };
if (token) boot();
