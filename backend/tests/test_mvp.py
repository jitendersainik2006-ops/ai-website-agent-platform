from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from app import create_app
from app.security.passwords import hash_password


@pytest.fixture()
def app_client():
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "s" * 32, "JWT_SECRET_KEY": "j" * 32, "MONGODB_DATABASE": "mvp_tests"},
        mongomock.MongoClient(),
    )
    db = app.extensions["mongo_db"]
    tenants = []
    for name, slug in (("Tenant One", "tenant-one"), ("Tenant Two", "tenant-two")):
        tenant_id = db.tenants.insert_one({"name": name, "slug": slug, "status": "active"}).inserted_id
        user_id = db.users.insert_one({"name": name + " Admin", "email": slug + "@example.com", "password_hash": hash_password("CorrectPass123!"), "status": "active"}).inserted_id
        db.memberships.insert_one({"tenant_id": tenant_id, "user_id": user_id, "role": "owner", "status": "active"})
        db.business_profiles.insert_one({"tenant_id": tenant_id, "name": name, "description": f"{name} provides distinct security consulting.", "contact_email": slug + "@example.com", "timezone": "UTC", "appointment_duration_minutes": 30, "appointment_buffer_minutes": 0})
        db.widget_configs.insert_one({"tenant_id": tenant_id, "public_key": slug + "-key", "enabled": True, "allowed_origins": []})
        for weekday in range(5):
            db.business_hours.insert_one({"tenant_id": tenant_id, "weekday": weekday, "enabled": True, "start_time": "09:00", "end_time": "10:00"})
        tenants.append((slug, tenant_id))
    return app.test_client(), tenants


def auth(client, slug):
    result = client.post("/api/v1/auth/login", json={"email": slug + "@example.com", "password": "CorrectPass123!", "tenant_slug": slug})
    return {"Authorization": "Bearer " + result.get_json()["access_token"]}


def test_admin_context_and_role_protection(app_client):
    client, tenants = app_client
    assert client.get("/api/v1/admin/context").status_code == 401
    assert client.get("/api/v1/admin/context", headers=auth(client, "tenant-one")).get_json()["tenant"]["slug"] == "tenant-one"
    db = client.application.extensions["mongo_db"]
    member = db.memberships.find_one({"tenant_id": tenants[0][1]})
    db.memberships.update_one({"_id": member["_id"]}, {"$set": {"role": "viewer"}})
    viewer = auth(client, "tenant-one")
    assert client.post("/api/v1/admin/services", headers=viewer, json={"title": "x", "description": "y"}).status_code == 403
    lead_id = db.leads.insert_one({"tenant_id": tenants[0][1], "email": "viewer@example.com", "created_at": datetime.now(timezone.utc)}).inserted_id
    appointment_id = db.appointments.insert_one({"tenant_id": tenants[0][1], "status": "confirmed", "start_at": datetime(2030, 1, 7, 9, tzinfo=timezone.utc), "end_at": datetime(2030, 1, 7, 9, 30, tzinfo=timezone.utc)}).inserted_id
    assert client.patch(f"/api/v1/admin/leads/{lead_id}", headers=viewer, json={"status": "contacted"}).status_code == 403
    assert client.patch("/api/v1/admin/appointments", headers=viewer, json={"id": str(appointment_id), "status": "cancelled"}).status_code == 403


def test_tenant_scoped_crud_and_knowledge_retrieval(app_client):
    client, _ = app_client
    first, second = auth(client, "tenant-one"), auth(client, "tenant-two")
    service = client.post("/api/v1/admin/services", headers=first, json={"title": "Tenant One Audit", "description": "A private audit", "status": "published"})
    assert service.status_code == 201
    service_id = service.get_json()["_id"]
    assert client.get("/api/v1/admin/services", headers=second).get_json() == []
    assert client.get(f"/api/v1/admin/services/{service_id}", headers=second).status_code == 404
    second_tenant_id = str(client.application.extensions["mongo_db"].tenants.find_one({"slug": "tenant-two"})["_id"])
    assert client.patch(f"/api/v1/admin/services/{service_id}", headers=first, json={"tenant_id": second_tenant_id, "description": "Still isolated"}).status_code == 200
    assert client.get(f"/api/v1/admin/services/{service_id}", headers=second).status_code == 404
    assert client.application.extensions["mongo_db"].audit_logs.count_documents({"action": "services.updated"}) == 1
    chat = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "Tell me about the audit"})
    assert chat.status_code == 200
    assert "still isolated" in chat.get_json()["answer"].lower()
    other_chat = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-two-key"}, json={"message": "Tell me about the audit"})
    assert "still isolated" not in other_chat.get_json()["answer"].lower()


def test_public_lead_and_booking_prevent_double_booking(app_client):
    client, _ = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    lead = client.post("/api/v1/public/leads", headers=key, json={"name": "Visitor", "email": "visitor@example.com", "requirement": "Callback"})
    assert lead.status_code == 201
    slot_response = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key)
    assert slot_response.status_code == 200, slot_response.get_json()
    slots = slot_response.get_json()["slots"]
    assert slots
    payload = {"start_at": slots[0], "name": "Visitor", "email": "visitor@example.com"}
    assert client.post("/api/v1/public/appointments", headers=key, json=payload).status_code == 201
    assert client.post("/api/v1/public/appointments", headers=key, json=payload).status_code == 409


def test_public_widget_rejects_invalid_key_and_origin(app_client):
    client, _ = app_client
    assert client.post("/api/v1/chat", headers={"X-Widget-Key": "wrong"}, json={"message": "hello"}).status_code == 401
    db = client.application.extensions["mongo_db"]
    db.widget_configs.update_one({"public_key": "tenant-one-key"}, {"$set": {"allowed_origins": ["https://allowed.example"]}})
    assert client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key", "Origin": "https://not-allowed.example"}, json={"message": "hello"}).status_code == 403


def test_baseline_security_headers_do_not_block_widget_asset(app_client):
    client, _ = app_client
    response = client.get("/widget-frame.html")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "microphone=()" in response.headers["Permissions-Policy"]


def test_availability_and_widget_configuration_writes_require_role_and_validate(app_client):
    client, tenants = app_client
    owner = auth(client, "tenant-one")
    db = client.application.extensions["mongo_db"]
    member = db.memberships.find_one({"tenant_id": tenants[0][1]})
    db.memberships.update_one({"_id": member["_id"]}, {"$set": {"role": "viewer"}})
    viewer = auth(client, "tenant-one")
    blocked = {"start_at": "2030-01-07T09:00:00+00:00", "end_at": "2030-01-07T10:00:00+00:00"}
    assert client.post("/api/v1/admin/availability/blocked", headers=viewer, json=blocked).status_code == 403
    assert client.patch("/api/v1/admin/widget-config", headers=viewer, json={"enabled": False}).status_code == 403
    assert client.put("/api/v1/admin/business-hours", headers=viewer, json={"hours": []}).status_code == 403
    db.memberships.update_one({"_id": member["_id"]}, {"$set": {"role": "owner"}})

    assert client.post("/api/v1/admin/availability/blocked", headers=owner, json={**blocked, "end_at": blocked["start_at"]}).status_code == 400
    created = client.post("/api/v1/admin/availability/blocked", headers=owner, json=blocked)
    assert created.status_code == 201
    assert client.delete(f"/api/v1/admin/availability/blocked/{created.get_json()['_id']}", headers=owner).status_code == 204
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "blocked_time.created"}) == 1
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "blocked_time.deleted"}) == 1

    original = client.get("/api/v1/admin/business-hours", headers=owner).get_json()
    assert client.put("/api/v1/admin/business-hours", headers=owner, json={"hours": [{"weekday": 0, "start_time": "17:00", "end_time": "09:00"}]}).status_code == 400
    assert client.get("/api/v1/admin/business-hours", headers=owner).get_json() == original
    updated_hours = [{"weekday": weekday, "enabled": weekday < 5, "start_time": "10:00", "end_time": "16:00"} for weekday in range(7)]
    assert client.put("/api/v1/admin/business-hours", headers=owner, json={"hours": updated_hours}).status_code == 200
    saved_hours = client.get("/api/v1/admin/business-hours", headers=owner).get_json()
    assert len(saved_hours) == 7
    assert saved_hours[0]["start_time"] == "10:00"
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "business_hours.updated"}) == 1
    assert client.patch("/api/v1/admin/widget-config", headers=owner, json={"welcome_message": "Updated"}).status_code == 200
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "widget_config.updated"}) == 1


def test_business_profile_rejects_values_that_would_break_scheduling(app_client):
    client, _ = app_client
    owner = auth(client, "tenant-one")
    assert client.patch("/api/v1/admin/business", headers=owner, json={"timezone": "Not/A-Timezone"}).status_code == 400
    assert client.patch("/api/v1/admin/business", headers=owner, json={"appointment_duration_minutes": 0}).status_code == 400
    assert client.patch("/api/v1/admin/business", headers=owner, json={"appointment_buffer_minutes": -1}).status_code == 400
    assert client.patch("/api/v1/admin/business", headers=owner, json={"timezone": "UTC", "appointment_duration_minutes": 45, "appointment_buffer_minutes": 5}).status_code == 200


def chat(client, key, message):
    response = client.post("/api/v1/chat", headers={"X-Widget-Key": key}, json={"message": message})
    assert response.status_code == 200
    return response.get_json()["answer"]


def test_service_pricing_hours_and_unknown_answer_quality(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    db.services.insert_one({"tenant_id": tenant, "title": "Incident Response", "description": "Confirmed incident response support for active security events.", "status": "published"})
    db.faqs.insert_one({"tenant_id": tenant, "question": "What services do you provide?", "answer": "We provide incident response and security consulting.", "status": "published"})
    key = "tenant-one-key"

    assert "incident response" in chat(client, key, "What services do you provide?").lower()
    assert "incident response support" in chat(client, key, "Do you provide incident response?").lower()
    assert chat(client, key, "What is the price of your services?").startswith("I do not have confirmed information")
    assert "monday to friday: 09:00 to 10:00" in chat(client, key, "What are your office opening hours?").lower()
    assert chat(client, key, "What is the weather today?").startswith("I do not have confirmed information")


def test_relevant_faq_and_published_only_retrieval(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    db.faqs.insert_one({"tenant_id": tenant, "question": "Do you support incident response?", "answer": "Yes, confirmed response support is available.", "status": "published"})
    db.knowledge.insert_one({"tenant_id": tenant, "title": "Private pricing", "content": "The confidential pricing is 99 credits.", "status": "draft"})
    db.services.insert_one({"tenant_id": tenant, "title": "Secret weather service", "description": "This unpublished item answers weather questions.", "status": "draft"})
    assert "confirmed response support" in chat(client, "tenant-one-key", "Do you support incident response?").lower()
    assert chat(client, "tenant-one-key", "What is the pricing?").startswith("I do not have confirmed information")
    assert chat(client, "tenant-one-key", "What is the weather?").startswith("I do not have confirmed information")


def test_hours_without_configured_hours_falls_back_safely(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    db.business_hours.delete_many({"tenant_id": tenant})
    answer = chat(client, "tenant-one-key", "When are you open?")
    assert answer.startswith("I do not have confirmed information")
    assert "security consulting" not in answer.lower()


def test_blocked_time_and_intent_classification(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    blocked_start = datetime(2030, 1, 7, 9, 0, tzinfo=timezone.utc)
    db.blocked_times.insert_one({"tenant_id": tenant, "start_at": blocked_start, "end_at": blocked_start + timedelta(minutes=30)})
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers={"X-Widget-Key": "tenant-one-key"}).get_json()["slots"]
    assert all("09:00:00" not in slot for slot in slots)

    general = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "Tell me a joke."}).get_json()
    lead = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "Please request a quote for me."}).get_json()
    appointment = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "Can I schedule a meeting?"}).get_json()
    assert general["intent"] == "general"
    assert lead["intent"] == "lead"
    assert appointment["intent"] == "appointment"


def test_public_appointment_cancel_and_reschedule_are_token_bound(app_client):
    client, _ = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    booking = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[0], "name": "Token Visitor", "email": "token@example.com"}).get_json()["appointment"]
    appointment_id, token = booking["_id"], booking["manage_token"]
    assert "cancellation_token_hash" not in booking
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers=key, json={"manage_token": "bad"}).status_code == 403
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers={"X-Widget-Key": "tenant-two-key"}, json={"manage_token": token}).status_code == 403

    rescheduled = client.post(f"/api/v1/public/appointments/{appointment_id}/reschedule", headers=key, json={"manage_token": token, "start_at": slots[1]} )
    assert rescheduled.status_code == 200
    assert rescheduled.get_json()["appointment"]["status"] == "rescheduled"
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/reschedule", headers=key, json={"manage_token": token, "start_at": "2030-01-12T09:00:00+00:00"}).status_code == 409

    cancelled = client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers=key, json={"manage_token": token})
    assert cancelled.status_code == 200
    assert cancelled.get_json()["appointment"]["status"] == "cancelled"
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers=key, json={"manage_token": token}).status_code == 200
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/reschedule", headers=key, json={"manage_token": token, "start_at": slots[0]}).status_code == 409


def test_appointment_lifecycle_adapters_are_safe_and_failure_tolerant(app_client):
    client, _ = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    app = client.application
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    booking = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[0], "name": "Lifecycle", "email": "lifecycle@example.com"}).get_json()["appointment"]
    appointment_id, token = booking["_id"], booking["manage_token"]

    notifications = app.extensions["notification_provider"].events
    calendars = app.extensions["calendar_adapter"].events
    assert [event["event_type"] for event in notifications] == ["appointment.confirmed"]
    assert calendars[appointment_id]["action"] == "created"
    assert token not in str(notifications)
    assert token not in str(calendars)

    assert client.post(f"/api/v1/public/appointments/{appointment_id}/reschedule", headers=key, json={"manage_token": token, "start_at": slots[1]}).status_code == 200
    assert notifications[-1]["event_type"] == "appointment.rescheduled"
    assert calendars[appointment_id]["action"] == "updated"
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers=key, json={"manage_token": token}).status_code == 200
    assert notifications[-1]["event_type"] == "appointment.cancelled"
    assert calendars[appointment_id]["action"] == "cancelled"
    notification_count = len(notifications)
    assert client.post(f"/api/v1/public/appointments/{appointment_id}/cancel", headers=key, json={"manage_token": token}).status_code == 200
    assert len(notifications) == notification_count

    class FailingProvider:
        def send(self, *args, **kwargs):
            raise RuntimeError("provider failed")

    class FailingCalendar:
        def create_event(self, *args, **kwargs):
            raise RuntimeError("calendar failed")

    app.extensions["notification_provider"] = FailingProvider()
    app.extensions["calendar_adapter"] = FailingCalendar()
    next_day_slots = client.get("/api/v1/public/availability/slots?date=2030-01-08", headers=key).get_json()["slots"]
    another = client.post("/api/v1/public/appointments", headers=key, json={"start_at": next_day_slots[0], "name": "Still Booked", "email": "still@example.com"})
    assert another.status_code == 201
    assert another.get_json()["appointment"]["status"] == "confirmed"


def test_calendar_availability_contract_adds_busy_periods_without_replacing_scheduler(app_client):
    client, _ = app_client
    app = client.application

    class BusyCalendar:
        def get_availability(self, tenant_id, start_at, end_at):
            return [{"start_at": start_at, "end_at": start_at + timedelta(minutes=30)}]

    app.extensions["calendar_adapter"] = BusyCalendar()
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers={"X-Widget-Key": "tenant-one-key"}).get_json()["slots"]
    assert len(slots) == 1
    assert "09:30:00" in slots[0]


def test_admin_appointment_management_uses_lifecycle_and_tenant_scope(app_client):
    client, tenants = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    owner, other_owner = auth(client, "tenant-one"), auth(client, "tenant-two")
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    booking = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[0], "name": "Admin Managed", "email": "admin-managed@example.com"}).get_json()["appointment"]
    appointment_id = booking["_id"]

    detail = client.get(f"/api/v1/admin/appointments/{appointment_id}", headers=owner)
    assert detail.status_code == 200
    detail_data = detail.get_json()
    assert detail_data["history"][0]["action"] == "booked"
    assert detail_data["lead"]["email"] == "admin-managed@example.com"
    assert "cancellation_token_hash" not in detail_data
    assert "manage_token" not in detail_data
    assert client.get(f"/api/v1/admin/appointments/{appointment_id}", headers=other_owner).status_code == 404

    db = client.application.extensions["mongo_db"]
    membership = db.memberships.find_one({"tenant_id": tenants[0][1]})
    db.memberships.update_one({"_id": membership["_id"]}, {"$set": {"role": "viewer"}})
    viewer = auth(client, "tenant-one")
    assert client.post(f"/api/v1/admin/appointments/{appointment_id}/reschedule", headers=viewer, json={"start_at": slots[1]}).status_code == 403
    assert client.post(f"/api/v1/admin/appointments/{appointment_id}/cancel", headers=viewer).status_code == 403
    db.memberships.update_one({"_id": membership["_id"]}, {"$set": {"role": "owner"}})

    rescheduled = client.post(f"/api/v1/admin/appointments/{appointment_id}/reschedule", headers=owner, json={"start_at": slots[1]})
    assert rescheduled.status_code == 200
    assert rescheduled.get_json()["status"] == "rescheduled"
    assert client.post(f"/api/v1/admin/appointments/{appointment_id}/reschedule", headers=owner, json={"start_at": slots[0]}).status_code == 200
    assert client.application.extensions["calendar_adapter"].events[appointment_id]["action"] == "updated"
    assert client.application.extensions["notification_provider"].events[-1]["event_type"] == "appointment.rescheduled"

    cancelled = client.post(f"/api/v1/admin/appointments/{appointment_id}/cancel", headers=owner)
    assert cancelled.status_code == 200
    assert cancelled.get_json()["status"] == "cancelled"
    assert client.application.extensions["calendar_adapter"].events[appointment_id]["action"] == "cancelled"
    assert client.application.extensions["notification_provider"].events[-1]["event_type"] == "appointment.cancelled"
    assert client.post(f"/api/v1/admin/appointments/{appointment_id}/cancel", headers=owner).status_code == 200
    assert client.post(f"/api/v1/admin/appointments/{appointment_id}/reschedule", headers=owner, json={"start_at": slots[1]}).status_code == 409
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "appointment.admin_rescheduled"}) == 2
    assert db.audit_logs.count_documents({"tenant_id": tenants[0][1], "action": "appointment.admin_cancelled"}) == 2
