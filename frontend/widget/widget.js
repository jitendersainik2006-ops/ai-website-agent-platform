const key = new URLSearchParams(location.search).get('widget_key');
let conversationId;
let appointment = null; // Kept only in this iframe's memory; never persisted or put in a URL.

const $ = selector => document.querySelector(selector);
const msg = (text, who = 'agent') => {
  const element = document.createElement('div');
  element.className = 'msg ' + who;
  element.textContent = text;
  $('#messages').append(element);
  element.scrollIntoView();
};
const status = (text = '', error = false) => {
  const element = $('#appointment-status');
  element.textContent = text;
  element.classList.toggle('error', error);
};
const req = async (path, options = {}) => {
  const response = await fetch('/api/v1' + path, {
    headers: {'Content-Type': 'application/json', 'X-Widget-Key': key},
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.message || 'Request failed');
  return data;
};
const dateValue = date => date.toISOString().slice(0, 10);
const nextBusinessDay = () => {
  const date = new Date();
  do { date.setDate(date.getDate() + 1); } while (date.getDay() === 0 || date.getDay() === 6);
  return dateValue(date);
};
const slotLabel = slot => new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short', timeZoneName: 'short'}).format(new Date(slot));

async function loadSlots() {
  const date = $('#appointment-date').value;
  if (!date) return;
  const response = await req('/public/availability/slots?date=' + encodeURIComponent(date));
  const select = $('#appointment-slot');
  select.replaceChildren(new Option(response.slots.length ? 'Choose a time' : 'No times available', ''));
  response.slots.forEach(slot => select.add(new Option(slotLabel(slot), slot)));
  status(response.slots.length ? `${response.slots.length} available time${response.slots.length === 1 ? '' : 's'} found.` : 'No available times for this date.');
  return response.slots;
}

function showBooking(mode = 'book') {
  $('#appointment-panel').hidden = false;
  $('#appointment-submit').textContent = mode === 'reschedule' ? 'Confirm new time' : 'Confirm appointment';
  ['#appointment-name', '#appointment-email', '#appointment-phone'].forEach(selector => {
    const field = $(selector);
    field.hidden = mode === 'reschedule';
    field.disabled = mode === 'reschedule';
  });
  $('#appointment-form').dataset.mode = mode;
}

(async () => {
  $('#appointment-date').value = nextBusinessDay();
  try {
    const data = await req('/public/widget-config');
    $('#title').textContent = data.business_name;
    msg(data.welcome_message);
  } catch {
    msg('The assistant is unavailable right now.');
  }
})();

$('#form').onsubmit = async event => {
  event.preventDefault();
  const input = $('#input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  msg(text, 'visitor');
  try {
    const result = conversationId
      ? await req('/public/conversations/' + conversationId + '/messages', {method: 'POST', body: JSON.stringify({message: text})})
      : await req('/chat', {method: 'POST', body: JSON.stringify({message: text})});
    conversationId = result.conversation_id;
    msg(result.answer);
  } catch (error) {
    msg(error.message);
  }
};

$('#slots').onclick = async () => {
  showBooking();
  try { await loadSlots(); } catch (error) { status(error.message, true); }
};
$('#book').onclick = async () => {
  showBooking();
  try { await loadSlots(); } catch (error) { status(error.message, true); }
};
$('#appointment-date').onchange = async () => {
  try { await loadSlots(); } catch (error) { status(error.message, true); }
};
$('#appointment-form').onsubmit = async event => {
  event.preventDefault();
  const startAt = $('#appointment-slot').value;
  if (!startAt) return status('Choose an available time first.', true);
  const mode = event.currentTarget.dataset.mode;
  try {
    if (mode === 'reschedule') {
      const result = await req('/public/appointments/' + appointment.id + '/reschedule', {
        method: 'POST', body: JSON.stringify({manage_token: appointment.token, start_at: startAt}),
      });
      appointment.status = result.appointment.status;
      appointment.startAt = result.appointment.start_at;
      status('Your appointment has been rescheduled.');
    } else {
      const result = await req('/public/appointments', {
        method: 'POST',
        body: JSON.stringify({start_at: startAt, name: $('#appointment-name').value.trim(), email: $('#appointment-email').value.trim(), phone: $('#appointment-phone').value.trim()}),
      });
      appointment = {id: result.appointment._id, token: result.appointment.manage_token, status: result.appointment.status, startAt: result.appointment.start_at};
      $('#management-tools').hidden = false;
      status('Your appointment is confirmed. Keep this window open to reschedule or cancel it.');
    }
    $('#appointment-panel').hidden = true;
  } catch (error) {
    status(error.message, true);
  }
};

$('#reschedule').onclick = async () => {
  if (!appointment) return;
  showBooking('reschedule');
  try { await loadSlots(); } catch (error) { status(error.message, true); }
};
$('#cancel-appointment').onclick = async () => {
  if (!appointment || !confirm('Cancel this appointment?')) return;
  try {
    await req('/public/appointments/' + appointment.id + '/cancel', {method: 'POST', body: JSON.stringify({manage_token: appointment.token})});
    appointment = null;
    $('#management-tools').hidden = true;
    $('#appointment-panel').hidden = true;
    status('Your appointment has been cancelled.');
  } catch (error) {
    status(error.message, true);
  }
};
$('#lead').onclick = async () => {
  const email = prompt('Enter your email for a callback:');
  if (!email) return;
  try {
    await req('/public/leads', {method: 'POST', body: JSON.stringify({email, requirement: 'Widget callback request'})});
    msg('Thanks. Your contact request was recorded.');
  } catch (error) {
    msg(error.message);
  }
};
$('#close').onclick = () => { $('#box').style.display = 'none'; };
