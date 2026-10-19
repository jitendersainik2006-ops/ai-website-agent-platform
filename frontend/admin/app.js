const $ = selector => document.querySelector(selector);
// Do not let historical persistent browser tokens bypass the login-first screen.
localStorage.removeItem('agentToken');
localStorage.removeItem('customerToken');
let token = sessionStorage.agentToken || '';
let customerToken = sessionStorage.customerToken || '';
const customerWidgetKey = 'demo_black_intel_widget_key';
let customerConversationId = null;
let customerRescheduleAppointmentId = null;
document.querySelectorAll('.brand').forEach(brand => { const mark = brand.querySelector('.brand-mark'); const label = brand.querySelector('span:last-child'); if (mark) mark.textContent = 'BI'; if (label) label.textContent = 'BLACK INTEL'; });
const landingPrimary = document.querySelector('.hero-actions .button-primary');
if (landingPrimary) { landingPrimary.classList.remove('open-login'); landingPrimary.classList.add('open-customer'); landingPrimary.dataset.customerMode = 'login'; landingPrimary.textContent = 'Customer login'; }
const finalAction = document.querySelector('.final-cta .button-primary');
if (finalAction) { finalAction.classList.remove('open-login'); finalAction.classList.add('open-customer'); finalAction.dataset.customerMode = 'register'; finalAction.textContent = 'Create your account'; }
const previewAgent = document.querySelector('.preview-message.agent b');
if (previewAgent) previewAgent.textContent = 'Black Intel Agent';
let canWrite = false;
let currentView = 'overview';

const api = async (path, options = {}) => {
  const response = await fetch('/api/v1' + path, {headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})}, ...options});
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(data.message || data.error || 'Request failed');
  return data;
};
const esc = value => String(value || '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
let customerTimeZone = 'UTC';
const calendarDateInZone = (date, timeZone) => {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(date);
  const pick = type => parts.find(part => part.type === type).value;
  return `${pick('year')}-${pick('month')}-${pick('day')}`;
};
const weekdayInZone = (date, timeZone) => new Intl.DateTimeFormat('en-US', {timeZone, weekday: 'short'}).format(date);
const nextOpenCalendarDate = timeZone => {
  const cursor = new Date();
  let currentHour = 10;
  try {
    const parts = new Intl.DateTimeFormat('en-US', {timeZone, hour: 'numeric', hour12: false}).formatToParts(cursor);
    const hp = parts.find(p => p.type === 'hour');
    if (hp) currentHour = parseInt(hp.value, 10);
  } catch (e) {
    currentHour = cursor.getHours();
  }
  const startStep = currentHour >= 16 ? 1 : 0;
  for (let step = startStep; step < 16; step += 1) {
    const candidate = new Date(cursor.getTime() + step * 24 * 60 * 60 * 1000);
    const weekday = weekdayInZone(candidate, timeZone);
    if (weekday !== 'Sat' && weekday !== 'Sun') return calendarDateInZone(candidate, timeZone);
  }
  return calendarDateInZone(new Date(), timeZone);
};
const dateTime = (value, timeZone) => value ? new Intl.DateTimeFormat(undefined, {year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: timeZone || undefined, timeZoneName: timeZone ? 'short' : undefined}).format(new Date(value)) : 'Not recorded';
const wallTimeInZoneToIso = (localValue, timeZone) => {
  const match = String(localValue || '').match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  if (!match) return new Date(localValue).toISOString();
  const utcGuess = Date.UTC(Number(match[1].slice(0, 4)), Number(match[1].slice(5, 7)) - 1, Number(match[1].slice(8, 10)), Number(match[2]), Number(match[3]), 0);
  const offsetParts = new Intl.DateTimeFormat('en-US', {timeZone, timeZoneName: 'longOffset', hour: 'numeric'}).formatToParts(new Date(utcGuess));
  const tzName = (offsetParts.find(part => part.type === 'timeZoneName') || {}).value || 'GMT';
  const offsetMatch = tzName.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/i);
  if (!offsetMatch) return new Date(localValue).toISOString();
  const sign = offsetMatch[1] === '-' ? -1 : 1;
  const offsetMinutes = sign * (Number(offsetMatch[2]) * 60 + Number(offsetMatch[3] || 0));
  return new Date(utcGuess - offsetMinutes * 60 * 1000).toISOString();
};
const statusBadge = status => `<span class="status-badge ${esc(status || '').toLowerCase()}">${esc(status || 'active')}</span>`;
const empty = (title, text) => `<div class="panel empty-state"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
const loading = () => '<div class="panel empty-state"><h3>Loading workspace data</h3><p>Please wait a moment.</p></div>';
function notice(text, isError = false) { const target = $('#notice'); target.textContent = text; target.style.color = isError ? 'var(--danger)' : 'var(--accent)'; if (text) setTimeout(() => { if (target.textContent === text) target.textContent = ''; }, 4200); }
function setBusy(button, busy, text) { if (!button) return; button.disabled = busy; button.dataset.label ||= button.textContent; button.textContent = busy ? text : button.dataset.label; }
function setActive(view) { document.querySelectorAll('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view)); }
function showLogin() { document.body.classList.add('customer-auth-active'); $('#landing').hidden = true; $('#login').hidden = false; $('#app').hidden = true; $('#customer-auth').hidden = true; $('#customer-app').hidden = true; }
function showLanding() { showCustomerAuth('login'); }

async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const spinner = submit.querySelector('.button-loader');
  $('#login-error').textContent = '';
  ['err-admin-tenant-slug', 'err-admin-email', 'err-admin-password'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '';
  });
  const data = Object.fromEntries(new FormData(form));
  let valid = true;
  if (!data.tenant_slug || !data.tenant_slug.trim()) {
    const el = document.getElementById('err-admin-tenant-slug');
    if (el) el.textContent = 'Tenant workspace is required.';
    valid = false;
  }
  if (!data.email || !data.email.trim() || !data.email.includes('@')) {
    const el = document.getElementById('err-admin-email');
    if (el) el.textContent = 'Valid work email is required.';
    valid = false;
  }
  if (!data.password || !data.password.trim()) {
    const el = document.getElementById('err-admin-password');
    if (el) el.textContent = 'Password is required.';
    valid = false;
  }
  if (!valid) return;
  setBusy(submit, true, 'Verifying access...'); spinner.hidden = false;
  try {
    const result = await api('/auth/login', {method: 'POST', body: JSON.stringify(data)});
    token = result.access_token; sessionStorage.agentToken = token; await boot();
  } catch (error) { $('#login-error').textContent = error.message; }
  finally { setBusy(submit, false); spinner.hidden = true; }
}
async function boot() {
  try {
    const identity = await api('/admin/context');
    canWrite = ['owner', 'admin', 'manager'].includes(identity.role);
    document.body.classList.add('customer-auth-active');
    $('#landing').hidden = true; $('#login').hidden = true; $('#app').hidden = false;
    $('#tenant-name').textContent = identity.tenant.name;
    await show('overview');
  } catch { sessionStorage.removeItem('agentToken'); token = ''; showLogin(); }
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
  root.innerHTML = `<div class="page-heading"><p class="eyebrow">Scheduling operations</p><h2>Appointments</h2><p>Monitor meetings confirmed through the website agent.</p></div><div class="panel"><div class="list-title"><h3>All appointments</h3><span>${items.length} total</span></div>${items.length ? items.map(item => `<div class="row appointment-row"><span><b>${statusBadge(item.status)} ${esc(dateTime(item.start_at, item.timezone))}</b><br><small>${esc(item.timezone || 'Configured tenant time')}</small></span><button class="detail" data-id="${item._id}">Review</button></div>`).join('') : empty('No appointments yet', 'Confirmed visitor meetings will appear here.')}</div><div id="details"></div>`;
  root.querySelectorAll('.detail').forEach(button => button.onclick = async () => {
    $('#details').innerHTML = loading();
    try {
      const [appointment, business] = await Promise.all([
        api('/admin/appointments/' + button.dataset.id),
        api('/admin/business').catch(() => ({}))
      ]);
      const duration = Number(business?.appointment_duration_minutes) || 30;
      const buffer = Number(business?.appointment_buffer_minutes) || 0;
      const apptTz = appointment.timezone || business?.timezone || 'UTC';
      const defaultDate = calendarDateInZone(new Date(appointment.start_at), apptTz);
      const controls = canWrite && appointment.status !== 'cancelled' ? `
<div class="panel">
  <p class="eyebrow">Appointment management</p>
  <h3>Reschedule or cancel meeting</h3>
  <div class="row">
    <label style="flex:1">Date for offered slots
      <input id="admin-reschedule-date" type="date" value="${esc(defaultDate)}" aria-label="Reschedule date">
    </label>
    <label style="flex:1">Offered slots
      <select id="admin-slot" aria-label="Offered slots">
        <option value="">Loading offered slots...</option>
      </select>
    </label>
  </div>
  <div class="row">
    <label style="flex:1">Manual date &amp; time entry
      <input id="admin-time" type="datetime-local" step="${duration * 60}" aria-label="New appointment time">
    </label>
    <div style="display:flex;gap:8px;align-items:flex-end">
      <button id="admin-reschedule" type="button">Reschedule</button>
      <button id="admin-cancel" class="danger" type="button">Cancel appointment</button>
    </div>
  </div>
  <p class="muted small" id="admin-reschedule-guidance">
    Configured slot duration is ${duration} minutes${buffer ? ` (${buffer} min buffer)` : ''}. Choose an offered slot above or specify a time aligning with configured slot intervals and business hours.
  </p>
</div>` : '';
      $('#details').innerHTML = details('Appointment details and history', appointment) + controls;
      if (!canWrite || appointment.status === 'cancelled') return;

      const loadSlots = async (dateStr) => {
        const select = $('#admin-slot');
        if (!select) return;
        select.disabled = true;
        select.innerHTML = '<option value="">Loading offered slots...</option>';
        try {
          const response = await api('/admin/availability/slots?date=' + encodeURIComponent(dateStr) + '&appointment_id=' + appointment._id);
          const slots = Array.isArray(response) ? response : (response.slots || []);
          if (!slots.length) {
            select.innerHTML = '<option value="">No offered slots on this date</option>';
          } else {
            select.innerHTML = '<option value="">Select an offered slot...</option>' + slots.map(s => `<option value="${esc(s)}">${esc(dateTime(s, apptTz))}</option>`).join('');
          }
        } catch (err) {
          select.innerHTML = `<option value="">Unable to load slots: ${esc(err.message)}</option>`;
        } finally {
          select.disabled = false;
        }
      };

      if ($('#admin-reschedule-date')) {
        $('#admin-reschedule-date').onchange = () => {
          const d = $('#admin-reschedule-date').value;
          if (d) loadSlots(d);
        };
        await loadSlots(defaultDate);
      }
      if ($('#admin-slot') && $('#admin-time')) {
        $('#admin-slot').onchange = () => {
          if ($('#admin-slot').value) $('#admin-time').value = '';
        };
        $('#admin-time').oninput = () => {
          if ($('#admin-time').value) $('#admin-slot').value = '';
        };
      }

      $('#admin-cancel').onclick = async () => {
        if (!confirm('Cancel this appointment?')) return;
        const btn = $('#admin-cancel');
        setBusy(btn, true, 'Cancelling...');
        try {
          await api('/admin/appointments/' + appointment._id + '/cancel', {method: 'POST'});
          notice('Appointment cancelled.');
          await show('appointments');
        } catch (error) {
          notice(error.message, true);
        } finally {
          setBusy(btn, false);
        }
      };

      $('#admin-reschedule').onclick = async () => {
        const btn = $('#admin-reschedule');
        const slotValue = $('#admin-slot')?.value;
        const timeValue = $('#admin-time')?.value;
        let chosenIso = '';
        if (slotValue) {
          chosenIso = slotValue;
        } else if (timeValue) {
          chosenIso = wallTimeInZoneToIso(timeValue, apptTz);
        } else {
          return notice('Choose an offered slot or enter a new date and time.', true);
        }
        setBusy(btn, true, 'Rescheduling...');
        try {
          await api('/admin/appointments/' + appointment._id + '/reschedule', {
            method: 'POST',
            body: JSON.stringify({start_at: chosenIso})
          });
          notice('Appointment rescheduled.');
          await show('appointments');
        } catch (error) {
          notice(error.message, true);
        } finally {
          setBusy(btn, false);
        }
      };
    } catch (error) {
      $('#details').innerHTML = `<div class="panel empty-state"><h3>Unable to load appointment</h3><p>${esc(error.message)}</p></div>`;
      notice(error.message, true);
    }
  });
}
async function showAvailability(root) {
  const [hours, blocks, business] = await Promise.all([api('/admin/business-hours'), api('/admin/availability/blocked'), api('/admin/business')]);
  const businessTimeZone = business.timezone || 'UTC';
  const byDay = new Map(hours.map(hour => [hour.weekday, hour])); const names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const hourRows = Array.from({length: 7}, (_, weekday) => { const hour = byDay.get(weekday) || {enabled: false, start_time: '09:00', end_time: '17:00'}; return `<div class="row"><label><input type="checkbox" data-enabled="${weekday}" ${hour.enabled ? 'checked' : ''}> ${names[weekday]}</label><input type="time" data-start="${weekday}" value="${esc(hour.start_time)}"><input type="time" data-end="${weekday}" value="${esc(hour.end_time)}"></div>`; }).join('');
  const hoursEditor = canWrite ? `<form id="hours-form" class="panel"><p class="eyebrow">Scheduling policy</p><h3>Working hours</h3>${hourRows}<button type="submit">Save working hours</button></form>` : `<div class="panel"><h3>Working hours</h3>${hours.map(hour => `<div class="row"><span>${names[hour.weekday]}<br><small>${esc(hour.start_time)} to ${esc(hour.end_time)}</small></span>${statusBadge(hour.enabled ? 'enabled' : 'disabled')}</div>`).join('') || empty('No working hours', 'No availability windows are currently configured.')}</div>`;
  const blockForm = canWrite ? '<form id="block-form" class="panel"><p class="eyebrow">Scheduling control</p><h3>Block a period</h3><label>Start time<input name="start_at" type="datetime-local" required></label><label>End time<input name="end_at" type="datetime-local" required></label><button type="submit">Add blocked period</button></form>' : '';
  root.innerHTML = `<div class="page-heading"><p class="eyebrow">Availability intelligence</p><h2>Availability</h2><p>Define working windows and protect unavailable periods from booking.</p></div>${hoursEditor}${blockForm}<div class="panel"><div class="list-title"><h3>Blocked periods</h3><span>${blocks.length} active</span></div>${blocks.length ? blocks.map(block => `<div class="row"><span><b>${esc(dateTime(block.start_at))}</b><br><small>Until ${esc(dateTime(block.end_at))}</small></span>${canWrite ? `<button class="danger unblock" data-id="${block._id}">Remove</button>` : ''}</div>`).join('') : empty('No blocked periods', 'Your current working-hour windows are available for scheduling.')}</div>`;
  if (!canWrite) return;
  $('#hours-form').onsubmit = async event => { event.preventDefault(); const hours = Array.from({length: 7}, (_, weekday) => ({weekday, enabled: $(`[data-enabled="${weekday}"]`).checked, start_time: $(`[data-start="${weekday}"]`).value, end_time: $(`[data-end="${weekday}"]`).value})); if (hours.some(item => !item.start_time || !item.end_time || item.start_time >= item.end_time)) return notice('Each day needs a valid start and end time.', true); await api('/admin/business-hours', {method: 'PUT', body: JSON.stringify({hours})}); notice('Working hours saved.'); show('availability'); };
  $('#block-form').onsubmit = async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); data.start_at = wallTimeInZoneToIso(data.start_at, businessTimeZone); data.end_at = wallTimeInZoneToIso(data.end_at, businessTimeZone); await api('/admin/availability/blocked', {method: 'POST', body: JSON.stringify(data)}); notice('Blocked period added.'); show('availability'); };
  root.querySelectorAll('.unblock').forEach(button => button.onclick = async () => { await api('/admin/availability/blocked/' + button.dataset.id, {method: 'DELETE'}); notice('Blocked period removed.'); show('availability'); });
}
async function show(view) {
  currentView = view; setActive(view); const root = $('#view'); root.innerHTML = loading(); $('#app').classList.remove('nav-open');
  try {
    if (view === 'customers') { const items = await api('/admin/customers'); root.innerHTML = `<div class="page-heading"><p class="eyebrow">Client operations</p><h2>Customers</h2><p>Review customer accounts, history, and access status for this tenant.</p></div><div class="panel"><div class="list-title"><h3>Customer directory</h3><span>${items.length} records</span></div>${items.length ? items.map(item => `<div class="row"><span><b>${esc(item.full_name)} · ${esc(item.customer_id)}</b><br><small>${item.conversation_count} conversations · ${item.appointment_count} appointments</small></span><div>${statusBadge(item.status)} ${canWrite ? `<button class="detail customer-status" data-id="${item._id}" data-status="${item.status}">${item.status === 'active' ? 'Suspend' : 'Restore'}</button>` : ''}</div></div>`).join('') : empty('No customers yet', 'Customer accounts will appear here after registration.')}</div>`; root.querySelectorAll('.customer-status').forEach(button => button.onclick = async () => { const status = button.dataset.status === 'active' ? 'inactive' : 'active'; await api('/admin/customers/' + button.dataset.id, {method: 'PATCH', body: JSON.stringify({status})}); notice(`Customer ${status === 'active' ? 'restored' : 'suspended'}.`); show('customers'); }); return; }
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
$('#back-home').onclick = () => showCustomerAuth('login');
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => show(button.dataset.view));
$('#mobile-nav').onclick = () => $('#app').classList.toggle('nav-open');
$('#sign-out').onclick = () => { sessionStorage.removeItem('agentToken'); token = ''; canWrite = false; showLanding(); };
const customerApi = async (path, options = {}) => {
  const response = await fetch('/api/v1/customer' + path, {headers: {'Content-Type': 'application/json', ...(customerToken ? {Authorization: `Bearer ${customerToken}`} : {})}, ...options});
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(data.message || data.error || 'Request failed');
  return data;
};
function clearCustomerAuthErrors() {
  const regForm = $('#customer-register-form');
  const loginForm = $('#customer-login-form');
  [regForm, loginForm].forEach(form => {
    if (!form) return;
    form.querySelectorAll('.field-error').forEach(el => { el.textContent = ''; });
    form.querySelectorAll('[aria-invalid]').forEach(el => { el.setAttribute('aria-invalid', 'false'); });
  });
}
function showCustomerAuth(mode = 'login') {
  document.body.classList.add('customer-auth-active');
  $('#landing').hidden = true; $('#login').hidden = true; $('#app').hidden = true; $('#customer-app').hidden = true; $('#customer-auth').hidden = false;
  document.querySelectorAll('.auth-mode').forEach(button => {
    const active = button.dataset.customerMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const regForm = $('#customer-register-form');
  const loginForm = $('#customer-login-form');
  regForm.hidden = mode !== 'register';
  loginForm.hidden = mode !== 'login';
  clearCustomerAuthErrors();
  $('#customer-auth-title').textContent = mode === 'register' ? 'Create Your Black Intel Account' : 'Sign In to Black Intel';
  $('#customer-auth-copy').textContent = mode === 'register' ? 'Your customer ID is issued once and remains yours.' : 'Use your registered full name, Black Intel customer ID, and password.';
  $('#customer-auth-error').textContent = '';
  const activeForm = mode === 'register' ? regForm : loginForm;
  activeForm?.elements?.full_name?.focus();
}
function renderMarkdown(rawText) {
  if (!rawText || typeof rawText !== 'string') return '';
  const escapeHtml = str => str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const codeBlocks = [];
  let text = rawText.replace(/```([a-zA-Z0-9_\-\.]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
    return `@@CODE_BLOCK_${idx}@@`;
  });
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
    return `@@INLINE_CODE_${idx}@@`;
  });
  text = escapeHtml(text);
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__(.+?)__/g, '<strong>$1</strong>');
  const lines = text.split('\n');
  const processed = [];
  let inUl = false;
  let inOl = false;
  for (let line of lines) {
    const headingMatch = line.match(/^(\s*)(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      if (inUl) { processed.push('</ul>'); inUl = false; }
      if (inOl) { processed.push('</ol>'); inOl = false; }
      const level = Math.min(headingMatch[2].length + 1, 4);
      processed.push(`<h${level} class="md-heading">${headingMatch[3]}</h${level}>`);
      continue;
    }
    const ulMatch = line.match(/^(\s*)[-*]\s+(.+)$/);
    const olMatch = line.match(/^(\s*)\d+\.\s+(.+)$/);
    if (ulMatch) {
      if (inOl) { processed.push('</ol>'); inOl = false; }
      if (!inUl) { processed.push('<ul>'); inUl = true; }
      processed.push(`<li>${ulMatch[2]}</li>`);
    } else if (olMatch) {
      if (inUl) { processed.push('</ul>'); inUl = false; }
      if (!inOl) { processed.push('<ol>'); inOl = true; }
      processed.push(`<li>${olMatch[2]}</li>`);
    } else {
      if (inUl) { processed.push('</ul>'); inUl = false; }
      if (inOl) { processed.push('</ol>'); inOl = false; }
      processed.push(line);
    }
  }
  if (inUl) processed.push('</ul>');
  if (inOl) processed.push('</ol>');
  text = processed.join('\n');
  inlineCodes.forEach((html, idx) => { text = text.replace(`@@INLINE_CODE_${idx}@@`, html); });
  codeBlocks.forEach((html, idx) => { text = text.replace(`@@CODE_BLOCK_${idx}@@`, html); });
  return text;
}
function customerMessage(text, role = 'assistant') {
  const node = document.createElement('div');
  node.className = `${role}-message`;
  if (role === 'assistant') {
    node.innerHTML = renderMarkdown(text);
  } else {
    node.textContent = text;
  }
  $('#customer-messages').append(node);
  $('#customer-messages').scrollTop = $('#customer-messages').scrollHeight;
}
function renderCustomerHistory(data) {
  const conversations = data.conversations || []; const appointments = data.appointments || [];
  $('#customer-history-list').innerHTML = `${appointments.length ? appointments.map(item => `<article class="history-item"><span class="history-type">Appointment</span><strong>${esc(dateTime(item.start_at, item.timezone || customerTimeZone))}</strong><small>${esc(item.status)}</small>${item.status !== 'cancelled' ? `<span class="history-actions"><button class="history-control customer-reschedule" data-id="${item._id}" type="button">Reschedule</button><button class="history-control danger customer-cancel" data-id="${item._id}" type="button">Cancel</button></span>` : ''}</article>`).join('') : '<p class="history-empty">No appointments yet.</p>'}${conversations.length ? conversations.map(item => `<article class="history-item"><span class="history-type">Conversation</span><strong>${esc(dateTime(item.updated_at, customerTimeZone))}</strong><button class="history-control customer-conversation" data-id="${item._id}" type="button">Open conversation</button></article>`).join('') : '<p class="history-empty">No conversations yet.</p>'}`;
  document.querySelectorAll('.customer-conversation').forEach(button => button.onclick = () => loadCustomerConversation(button.dataset.id));
  document.querySelectorAll('.customer-cancel').forEach(button => button.onclick = async () => { try { await customerApi('/appointments/' + button.dataset.id + '/cancel', {method: 'POST'}); $('#customer-booking-message').textContent = 'Appointment cancelled.'; $('#customer-booking-message').style.color = 'var(--accent)'; await loadCustomerDashboard(); } catch (error) { $('#customer-booking-message').style.color = 'var(--danger)'; $('#customer-booking-message').textContent = error.message; } });
  document.querySelectorAll('.customer-reschedule').forEach(button => button.onclick = () => {
    customerRescheduleAppointmentId = button.dataset.id;
    const form = $('#customer-booking-form');
    const feedback = $('#customer-booking-message');
    feedback.style.color = 'var(--accent)';
    feedback.textContent = 'Choose a new date and time above, then click Confirm reschedule.';
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Confirm reschedule';
    submitBtn.dataset.label = 'Confirm reschedule';
    let cancelBtn = $('#customer-cancel-reschedule');
    if (!cancelBtn) {
      cancelBtn = document.createElement('button');
      cancelBtn.id = 'customer-cancel-reschedule';
      cancelBtn.className = 'button button-quiet';
      cancelBtn.type = 'button';
      cancelBtn.textContent = 'Cancel reschedule';
      cancelBtn.onclick = () => {
        customerRescheduleAppointmentId = null;
        submitBtn.textContent = 'Check and confirm appointment';
        submitBtn.dataset.label = 'Check and confirm appointment';
        cancelBtn.remove();
        feedback.textContent = '';
        checkCustomerRequestedTime();
      };
      form.append(cancelBtn);
    }
    form.elements.date.focus();
    checkCustomerRequestedTime();
  });
}
async function loadCustomerConversation(conversationId) {
  try { const conversation = await customerApi('/conversations/' + conversationId); customerConversationId = conversation._id; $('#customer-messages').innerHTML = ''; conversation.messages.forEach(message => customerMessage(message.content, message.role === 'customer' ? 'customer' : 'assistant')); } catch (error) { $('#customer-booking-message').textContent = error.message; }
}
async function prepareCustomerBookingDate() {
  const form = $('#customer-booking-form');
  const input = form.elements.date;
  const min = calendarDateInZone(new Date(), customerTimeZone);
  input.min = min;
  if (!input.value || input.value < min) input.value = nextOpenCalendarDate(customerTimeZone);
  if (!form.elements.time.value) form.elements.time.value = '09:00';
  await checkCustomerRequestedTime();
}
async function checkCustomerRequestedTime() {
  const form = $('#customer-booking-form');
  const date = form.elements.date.value;
  const time = form.elements.time.value;
  const feedback = $('#customer-booking-message');
  if (!date || !time) return false;
  feedback.textContent = 'Checking your requested time...';
  try {
    let path = '/availability/check?date=' + encodeURIComponent(date) + '&time=' + encodeURIComponent(time);
    if (customerRescheduleAppointmentId) {
      path += '&appointment_id=' + encodeURIComponent(customerRescheduleAppointmentId);
    }
    const result = await customerApi(path);
    if (result.timezone) customerTimeZone = result.timezone;
    feedback.textContent = result.message;
    feedback.style.color = result.available ? 'var(--accent)' : 'var(--danger)';
    return Boolean(result.available);
  } catch (error) {
    feedback.style.color = 'var(--danger)';
    feedback.textContent = error.message;
    return false;
  }
}
async function loadCustomerDashboard() {
  const data = await customerApi('/dashboard');
  customerTimeZone = data.timezone || customerTimeZone;
  $('#customer-name').textContent = `${data.customer.full_name} · ${data.customer.customer_id}`;
  await prepareCustomerBookingDate();
  renderCustomerHistory(data);
}
async function bootCustomer() {
  try { await customerApi('/me'); document.body.classList.remove('customer-auth-active'); $('#landing').hidden = true; $('#login').hidden = true; $('#app').hidden = true; $('#customer-auth').hidden = true; $('#customer-app').hidden = false; await loadCustomerDashboard(); }
  catch { sessionStorage.removeItem('customerToken'); customerToken = ''; showCustomerAuth('login'); }
}
function validateCustomerField(input) {
  if (!input || !input.name) return true;
  const name = input.name;
  const val = (input.value || '').trim();
  const form = input.form;
  const isRegister = form && form.id === 'customer-register-form';
  const prefix = isRegister ? 'err-reg-' : 'err-login-';
  const errId = prefix + name.replace(/_/g, '-');
  const errEl = document.getElementById(errId);
  let message = '';

  if (input.required && !val) {
    message = 'This field is required.';
  } else if (name === 'full_name' && val.length < 2) {
    message = 'Full name must be at least 2 characters.';
  } else if (name === 'age') {
    const num = parseInt(val, 10);
    if (isNaN(num) || num < 13 || num > 120) {
      message = 'Age must be between 13 and 120.';
    }
  } else if (name === 'reason' && val.length < 2) {
    message = 'Please describe what you would like help with.';
  } else if (name === 'customer_id' && !/^BI-\d{6,}$/.test(val)) {
    message = 'Customer ID format should be e.g. BI-000001.';
  } else if (name === 'password' && val.length < 8) {
    message = 'Password must be at least 8 characters.';
  } else if (name === 'confirm_password') {
    const pwd = form?.elements?.password?.value || '';
    if (input.value !== pwd) {
      message = 'Passwords do not match.';
    }
  }

  if (errEl) errEl.textContent = message;
  input.setAttribute('aria-invalid', message ? 'true' : 'false');
  return !message;
}

function initCustomerAuthValidation() {
  const regForm = $('#customer-register-form');
  const loginForm = $('#customer-login-form');
  [regForm, loginForm].forEach(form => {
    if (!form) return;
    Array.from(form.elements).forEach(el => {
      if (!['INPUT', 'TEXTAREA'].includes(el.tagName)) return;
      el.addEventListener('input', () => {
        validateCustomerField(el);
        if (el.name === 'password' && form.elements.confirm_password && form.elements.confirm_password.value) {
          validateCustomerField(form.elements.confirm_password);
        }
      });
      el.addEventListener('blur', () => validateCustomerField(el));
    });
  });
}

async function customerAuthenticate(event, endpoint) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  $('#customer-auth-error').textContent = '';

  let isValid = true;
  let firstInvalid = null;
  Array.from(form.elements).forEach(el => {
    if (!['INPUT', 'TEXTAREA'].includes(el.tagName)) return;
    const ok = validateCustomerField(el);
    if (!ok) {
      isValid = false;
      if (!firstInvalid) firstInvalid = el;
    }
  });

  if (!isValid) {
    if (firstInvalid) firstInvalid.focus();
    return;
  }

  const isRegister = form.id === 'customer-register-form';
  setBusy(button, true, isRegister ? 'Creating secure account...' : 'Opening dashboard...');

  try {
    const payload = {...Object.fromEntries(new FormData(form)), widget_key: customerWidgetKey};
    const result = await customerApi(endpoint, {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    if (!result || !result.access_token) {
      throw new Error('Authentication could not be confirmed by the server.');
    }
    customerToken = result.access_token;
    sessionStorage.customerToken = customerToken;
    await bootCustomer();
    if (isRegister && result.customer && result.customer.customer_id) {
      notice('Welcome ' + result.customer.full_name + '! Your Customer ID is ' + result.customer.customer_id + '.');
    }
  } catch (error) {
    const msg = error.message || 'Authentication failed.';
    $('#customer-auth-error').textContent = msg;
    const prefix = isRegister ? 'err-reg-' : 'err-login-';
    if (msg.toLowerCase().includes('passwords do not match')) {
      const el = form.elements.confirm_password;
      if (el) { el.setAttribute('aria-invalid', 'true'); const err = document.getElementById(prefix + 'confirm-password'); if (err) err.textContent = msg; }
    } else if (msg.toLowerCase().includes('password')) {
      const el = form.elements.password;
      if (el) { el.setAttribute('aria-invalid', 'true'); const err = document.getElementById(prefix + 'password'); if (err) err.textContent = msg; }
    } else if (msg.toLowerCase().includes('credentials') || msg.toLowerCase().includes('customer id')) {
      const el = form.elements.customer_id;
      if (el) { el.setAttribute('aria-invalid', 'true'); const err = document.getElementById('err-login-customer-id'); if (err) err.textContent = msg; }
    }
  } finally {
    setBusy(button, false);
  }
}
document.querySelectorAll('.open-customer').forEach(button => button.onclick = () => showCustomerAuth(button.dataset.customerMode || 'login'));
$('#open-admin-login').onclick = showLogin;
document.querySelectorAll('.auth-mode').forEach(button => button.onclick = () => showCustomerAuth(button.dataset.customerMode));
$('#customer-register-form').onsubmit = event => customerAuthenticate(event, '/auth/register');
$('#customer-login-form').onsubmit = event => customerAuthenticate(event, '/auth/login');
initCustomerAuthValidation();
async function sendCustomerMessage(message) {
  const normalized = message.trim();
  if (!normalized) return;
  customerMessage(normalized, 'customer');
  try {
    const endpoint = customerConversationId ? '/conversations/' + customerConversationId + '/messages' : '/chat';
    const result = await customerApi(endpoint, {method: 'POST', body: JSON.stringify({message: normalized})});
    customerConversationId = result.conversation_id;
    customerMessage(result.answer);
    await loadCustomerDashboard();
  } catch (error) {
    customerMessage(error.message, 'assistant');
  }
}
$('#customer-chat-form').onsubmit = async event => { event.preventDefault(); const input = event.currentTarget.elements.message; const message = input.value; input.value = ''; await sendCustomerMessage(message); };
document.querySelectorAll('[data-customer-prompt]').forEach(button => button.onclick = () => sendCustomerMessage(button.dataset.customerPrompt));
$('#customer-own-question').onclick = () => $('#customer-chat-form').elements.message.focus();
$('#customer-booking-form').elements.date.onchange = checkCustomerRequestedTime;
$('#customer-booking-form').elements.date.oninput = checkCustomerRequestedTime;
$('#customer-booking-form').elements.time.onchange = checkCustomerRequestedTime;
$('#customer-booking-form').elements.time.oninput = checkCustomerRequestedTime;
$('#customer-booking-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');
  const data = Object.fromEntries(new FormData(form));
  const feedback = $('#customer-booking-message');
  if (!data.date || !data.time) return;
  setBusy(submitButton, true, customerRescheduleAppointmentId ? 'Rescheduling...' : 'Checking availability...');
  try {
    const isAvailable = await checkCustomerRequestedTime();
    if (!isAvailable) {
      setBusy(submitButton, false);
      return;
    }
    feedback.style.color = 'var(--accent)';
    feedback.textContent = customerRescheduleAppointmentId ? 'Rescheduling meeting...' : 'Confirming your requested time...';
    const path = customerRescheduleAppointmentId ? '/appointments/' + customerRescheduleAppointmentId + '/reschedule' : '/appointments';
    const result = await customerApi(path, {method: 'POST', body: JSON.stringify(data)});
    if (!result || !result.appointment || !result.appointment._id) {
      throw new Error('Appointment confirmation was not acknowledged by the server.');
    }
    feedback.textContent = customerRescheduleAppointmentId ? 'Appointment successfully rescheduled.' : 'Appointment confirmed.';
    customerRescheduleAppointmentId = null;
    submitButton.textContent = 'Check and confirm appointment';
    submitButton.dataset.label = 'Check and confirm appointment';
    $('#customer-cancel-reschedule')?.remove();
    form.elements.time.value = '09:00';
    await loadCustomerDashboard();
  } catch (error) {
    feedback.style.color = 'var(--danger)';
    feedback.textContent = error.message;
  } finally {
    setBusy(submitButton, false);
  }
};
$('#customer-refresh').onclick = loadCustomerDashboard;
$('#customer-sign-out').onclick = () => { sessionStorage.removeItem('customerToken'); customerToken = ''; showLanding(); };
if (token) boot(); else if (customerToken) bootCustomer(); else showCustomerAuth('login');
