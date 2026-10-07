const $ = selector => document.querySelector(selector);
let token = localStorage.agentToken || '';
let canWrite = false;

const api = async (path, options = {}) => {
  const response = await fetch('/api/v1' + path, {headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})}, ...options});
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(data.message || data.error || 'Request failed');
  return data;
};
const note = text => { $('#notice').textContent = text; };
const esc = value => String(value || '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
const dateTime = value => value ? new Date(value).toLocaleString() : '';

async function login(event) {
  event.preventDefault();
  try {
    const result = await api('/auth/login', {method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    token = result.access_token;
    localStorage.agentToken = token;
    await boot();
  } catch (error) { $('#login-error').textContent = error.message; }
}
async function boot() {
  try {
    const identity = await api('/admin/context');
    canWrite = ['owner', 'admin', 'manager'].includes(identity.role);
    $('#login').hidden = true;
    $('#app').hidden = false;
    $('#tenant-name').textContent = identity.tenant.name;
    show('overview');
  } catch { localStorage.removeItem('agentToken'); token = ''; }
}
function details(title, value) { return `<div class="panel"><h3>${esc(title)}</h3><pre>${esc(JSON.stringify(value, null, 2))}</pre></div>`; }
function bindCrud(view, fields, root, items) {
  const create = canWrite ? `<form class="panel" id="create"><input name="${fields[0]}" placeholder="${fields[0]}" required><textarea name="${fields[1]}" placeholder="${fields[1]}" required></textarea><button>Create</button></form>` : '';
  root.innerHTML = `<h2>${view}</h2>${create}<div class="panel">${items.map(item => `<div class="row"><span><b>${esc(item[fields[0]])}</b><br><small>${esc(item[fields[1]])}</small></span>${canWrite ? `<button class="danger delete" data-id="${item._id}">Delete</button>` : ''}</div>`).join('') || 'No records yet.'}</div>`;
  if (!canWrite) return;
  $('#create').onsubmit = async event => { event.preventDefault(); await api('/admin/' + view, {method: 'POST', body: JSON.stringify({...Object.fromEntries(new FormData(event.target)), status: 'published'})}); show(view); };
  root.querySelectorAll('.delete').forEach(button => button.onclick = async () => { await api('/admin/' + view + '/' + button.dataset.id, {method: 'DELETE'}); show(view); });
}
async function showAppointments(root) {
  const items = await api('/admin/appointments');
  root.innerHTML = `<h2>Appointments</h2><div class="panel">${items.map(item => `<div class="row"><span><b>${esc(item.status)}</b><br><small>${esc(dateTime(item.start_at))}</small></span><button class="detail" data-id="${item._id}">Details</button></div>`).join('') || 'No appointments yet.'}</div><div id="details"></div>`;
  root.querySelectorAll('.detail').forEach(button => button.onclick = async () => {
    const appointment = await api('/admin/appointments/' + button.dataset.id);
    const controls = canWrite && appointment.status !== 'cancelled' ? `<div class="panel inline"><button id="admin-cancel" class="danger">Cancel</button><input id="admin-time" type="datetime-local"><button id="admin-reschedule">Reschedule</button></div>` : '';
    $('#details').innerHTML = details('Appointment details', appointment) + controls;
    if (!canWrite || appointment.status === 'cancelled') return;
    $('#admin-cancel').onclick = async () => { if (confirm('Cancel this appointment?')) { await api('/admin/appointments/' + appointment._id + '/cancel', {method: 'POST'}); show('appointments'); } };
    $('#admin-reschedule').onclick = async () => { const value = $('#admin-time').value; if (!value) return note('Choose a new date and time.'); await api('/admin/appointments/' + appointment._id + '/reschedule', {method: 'POST', body: JSON.stringify({start_at: new Date(value).toISOString()})}); show('appointments'); };
  });
}
async function showAvailability(root) {
  const [hours, blocks] = await Promise.all([api('/admin/business-hours'), api('/admin/availability/blocked')]);
  const byDay = new Map(hours.map(hour => [hour.weekday, hour]));
  const hourRows = Array.from({length: 7}, (_, weekday) => {
    const hour = byDay.get(weekday) || {weekday, enabled: false, start_time: '09:00', end_time: '17:00'};
    return `<div class="row"><label><input type="checkbox" data-enabled="${weekday}" ${hour.enabled ? 'checked' : ''}> Day ${weekday}</label><input type="time" data-start="${weekday}" value="${esc(hour.start_time)}"><input type="time" data-end="${weekday}" value="${esc(hour.end_time)}"></div>`;
  }).join('');
  const hoursEditor = canWrite ? `<form id="hours-form" class="panel"><h3>Working hours</h3>${hourRows}<button>Save working hours</button></form>` : `<div class="panel"><h3>Working hours</h3>${hours.map(hour => `<div class="row"><span>Day ${hour.weekday}: ${esc(hour.start_time)}-${esc(hour.end_time)} (${hour.enabled ? 'enabled' : 'disabled'})</span></div>`).join('') || 'No working hours configured.'}</div>`;
  const form = canWrite ? '<form id="block-form" class="panel"><h3>Block a period</h3><input name="start_at" type="datetime-local" required><input name="end_at" type="datetime-local" required><button>Add blocked period</button></form>' : '';
  root.innerHTML = `<h2>Availability</h2>${hoursEditor}${form}<div class="panel"><h3>Blocked periods</h3>${blocks.map(block => `<div class="row"><span>${esc(dateTime(block.start_at))} to ${esc(dateTime(block.end_at))}</span>${canWrite ? `<button class="danger unblock" data-id="${block._id}">Remove</button>` : ''}</div>`).join('') || 'No blocked periods.'}</div>`;
  if (!canWrite) return;
  $('#hours-form').onsubmit = async event => {
    event.preventDefault();
    const schedule = Array.from({length: 7}, (_, weekday) => ({weekday, enabled: $(`[data-enabled="${weekday}"]`).checked, start_time: $(`[data-start="${weekday}"]`).value, end_time: $(`[data-end="${weekday}"]`).value}));
    if (schedule.some(item => !item.start_time || !item.end_time || item.start_time >= item.end_time)) return note('Each day must have a valid start time before its end time.');
    try { await api('/admin/business-hours', {method: 'PUT', body: JSON.stringify({hours: schedule})}); note('Working hours saved.'); show('availability'); } catch (error) { note(error.message); }
  };
  $('#block-form').onsubmit = async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.start_at = new Date(data.start_at).toISOString(); data.end_at = new Date(data.end_at).toISOString(); await api('/admin/availability/blocked', {method: 'POST', body: JSON.stringify(data)}); show('availability'); };
  root.querySelectorAll('.unblock').forEach(button => button.onclick = async () => { await api('/admin/availability/blocked/' + button.dataset.id, {method: 'DELETE'}); show('availability'); });
}
async function show(view) {
  note(''); const root = $('#view');
  try {
    if (view === 'overview') { const data = await api('/admin/analytics'); root.innerHTML = `<h2>Overview</h2><div class="grid">${[['Conversations', data.total_conversations], ['Leads', data.total_leads], ['Appointments', data.total_appointments], ['Conversion', data.conversion_rate + '%']].map(item => `<div class="metric"><small>${item[0]}</small><b>${item[1]}</b></div>`).join('')}</div>`; return; }
    if (view === 'business') { const data = await api('/admin/business'); root.innerHTML = `<h2>Business profile</h2><form class="panel" id="business-form"><input name="name" value="${esc(data.name)}" ${canWrite ? '' : 'disabled'}><textarea name="description" ${canWrite ? '' : 'disabled'}>${esc(data.description)}</textarea><input name="contact_email" value="${esc(data.contact_email)}" ${canWrite ? '' : 'disabled'}><input name="timezone" value="${esc(data.timezone || 'Asia/Kolkata')}" ${canWrite ? '' : 'disabled'}>${canWrite ? '<button>Save profile</button>' : ''}</form>`; if (canWrite) $('#business-form').onsubmit = async event => { event.preventDefault(); await api('/admin/business', {method: 'PATCH', body: JSON.stringify(Object.fromEntries(new FormData(event.target)))}); note('Saved'); }; return; }
    if (['services', 'faqs', 'knowledge'].includes(view)) { const fields = view === 'services' ? ['title', 'description'] : view === 'faqs' ? ['question', 'answer'] : ['title', 'content']; bindCrud(view, fields, root, await api('/admin/' + view)); return; }
    if (view === 'appointments') return showAppointments(root);
    if (view === 'availability') return showAvailability(root);
    if (['conversations', 'leads'].includes(view)) { const items = await api('/admin/' + view); root.innerHTML = `<h2>${view}</h2><div class="panel">${items.map(item => `<div class="row"><span><b>${esc(item.name || item.visitor_id || 'Record')}</b><br><small>${esc(item.email || item.updated_at)}</small></span><button class="detail" data-id="${item._id}">Details</button></div>`).join('') || 'No records yet.'}</div><div id="details"></div>`; root.querySelectorAll('.detail').forEach(button => button.onclick = async () => { $('#details').innerHTML = details('Details', await api('/admin/' + view + '/' + button.dataset.id)); }); return; }
    if (view === 'embed') { const data = await api('/admin/widget-config'); const key = data.public_key || 'demo_black_intel_widget_key'; root.innerHTML = `<h2>Embed widget</h2><div class="panel"><p>Paste this on a business website:</p><textarea readonly>&lt;script src="${location.origin}/widget-loader.js" data-widget-key="${key}"&gt;&lt;/script&gt;</textarea><p>Public key: <code>${esc(key)}</code></p></div>`; }
  } catch (error) { root.innerHTML = `<div class="panel">${esc(error.message)}</div>`; }
}
$('#login-form').onsubmit = login;
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => show(button.dataset.view));
$('#sign-out').onclick = () => { localStorage.removeItem('agentToken'); location.reload(); };
if (token) boot();
