from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import mongomock
import pytest

from app import create_app
from app.security.passwords import hash_password


@pytest.fixture()
def app_client():
    # The MVP limiter is process-local. Clear it so one isolated Flask app does
    # not inherit request counts from an earlier test app.
    from app.api.public import _requests

    _requests.clear()
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


def test_widget_follow_up_uses_only_its_own_persisted_context(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    db.services.insert_one({"tenant_id": tenant, "title": "Incident Response", "description": "Confirmed response support for active security events.", "status": "published"})
    key = {"X-Widget-Key": "tenant-one-key"}
    first = client.post("/api/v1/chat", headers=key, json={"message": "Do you provide incident response?"})
    assert first.status_code == 200
    conversation_id = first.get_json()["conversation_id"]
    follow_up = client.post(
        f"/api/v1/public/conversations/{conversation_id}/messages",
        headers=key,
        json={"message": "What else should I know?"},
    )
    assert follow_up.status_code == 200
    assert "confirmed response support" in follow_up.get_json()["answer"].lower()


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


def test_retrieval_preserves_approved_knowledge_source_url(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    db.knowledge.insert_one({
        "tenant_id": tenant,
        "title": "Black Intel official service information",
        "content": "Black Intel's official information confirms digital forensics services.",
        "source_url": "https://theblackintel.com/",
        "status": "published",
    })
    with client.application.app_context():
        from app.services.knowledge_service import retrieve

        results = retrieve(str(tenant), "What official Black Intel information is available?")
    assert results[0]["source_url"] == "https://theblackintel.com/"


def test_official_knowledge_produces_distinct_grounded_company_answers(app_client):
    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]
    records = (
        {
            "title": "What does Black Intel do?",
            "content": "Black Intel combines cybersecurity, artificial intelligence, digital forensics, and counter-intelligence.",
        },
        {
            "title": "What services does Black Intel offer?",
            "content": "Black Intel lists digital forensics, cyber offense, and defensive security as core divisions.",
        },
        {
            "title": "How does Black Intel work with clients?",
            "content": "Black Intel invites prospective clients to request a consultation to discuss their needs.",
        },
    )
    for record in records:
        db.knowledge.insert_one({
            "tenant_id": tenant,
            **record,
            "source_url": "https://theblackintel.com/",
            "status": "published",
        })

    answers = [
        chat(client, "tenant-one-key", "What does Black Intel do?"),
        chat(client, "tenant-one-key", "What services does Black Intel offer?"),
        chat(client, "tenant-one-key", "How does Black Intel work with clients?"),
    ]
    assert "counter-intelligence" in answers[0].lower()
    assert "core divisions" in answers[1].lower()
    assert "consultation" in answers[2].lower()
    assert len(set(answers)) == 3


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
    assert "booking form" in appointment["answer"].lower()
    assert "is confirmed" not in appointment["answer"].lower()


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


def customer_auth(client, key, full_name="Asha Singh", password="CustomerPass123!"):
    response = client.post(
        "/api/v1/customer/auth/register",
        json={"full_name": full_name, "age": 28, "reason": "Security consultation", "password": password, "widget_key": key},
    )
    assert response.status_code == 201, response.get_json()
    result = response.get_json()
    return {"Authorization": "Bearer " + result["access_token"]}, result


def test_customer_registration_login_and_tenant_scoped_history(app_client):
    client, _ = app_client
    first_headers, first = customer_auth(client, "tenant-one-key")
    assert first["customer"]["customer_id"] == "BI-000001"
    assert "password_hash" not in first["customer"]
    assert client.get("/api/v1/customer/me", headers=first_headers).status_code == 200
    assert client.get("/api/v1/admin/context", headers=first_headers).status_code == 401

    login = client.post(
        "/api/v1/customer/auth/login",
        json={"full_name": "Asha Singh", "customer_id": "BI-000001", "password": "CustomerPass123!", "widget_key": "tenant-one-key"},
    )
    assert login.status_code == 200
    wrong_name = client.post(
        "/api/v1/customer/auth/login",
        json={"full_name": "Someone Else", "customer_id": "BI-000001", "password": "CustomerPass123!", "widget_key": "tenant-one-key"},
    )
    assert wrong_name.status_code == 401
    assert wrong_name.get_json()["error"] == "invalid_credentials"
    assert client.post("/api/v1/customer/auth/register", json={"full_name": "Invalid", "age": 28, "reason": "Test", "password": "CustomerPass123!", "widget_key": "wrong"}).status_code == 400

    chat = client.post("/api/v1/customer/chat", headers=first_headers, json={"message": "Tell me about security consulting."})
    assert chat.status_code == 200
    conversation_id = chat.get_json()["conversation_id"]
    continued_chat = client.post(
        f"/api/v1/customer/conversations/{conversation_id}/messages",
        headers=first_headers,
        json={"message": "What else should I know?"},
    )
    assert continued_chat.status_code == 200
    assert continued_chat.get_json()["conversation_id"] == conversation_id
    booking = client.post("/api/v1/customer/appointments", headers=first_headers, json={"date": "2030-01-07", "time": "09:00"})
    assert booking.status_code == 201
    appointment_id = booking.get_json()["appointment"]["_id"]
    assert "manage_token" not in booking.get_json()["appointment"]

    second_headers, second = customer_auth(client, "tenant-one-key", "Vikram Rao")
    assert second["customer"]["customer_id"] == "BI-000002"
    assert client.post(f"/api/v1/customer/conversations/{conversation_id}/messages", headers=second_headers, json={"message": "Read this"}).status_code == 404
    assert client.get(f"/api/v1/customer/conversations/{conversation_id}", headers=second_headers).status_code == 404
    assert client.post(f"/api/v1/customer/appointments/{appointment_id}/cancel", headers=second_headers).status_code == 403
    rescheduled = client.post(f"/api/v1/customer/appointments/{appointment_id}/reschedule", headers=first_headers, json={"date": "2030-01-07", "time": "09:30"})
    assert rescheduled.status_code == 200
    assert rescheduled.get_json()["appointment"]["status"] == "rescheduled"
    transcript = client.get(f"/api/v1/customer/conversations/{conversation_id}", headers=first_headers)
    assert transcript.status_code == 200
    assert [message["role"] for message in transcript.get_json()["messages"]] == ["customer", "agent", "customer", "agent"]
    dashboard = client.get("/api/v1/customer/dashboard", headers=first_headers).get_json()
    assert len(dashboard["conversations"]) == 1
    assert len(dashboard["appointments"]) == 1
    assert client.post(f"/api/v1/customer/appointments/{appointment_id}/cancel", headers=first_headers).status_code == 200


def test_customer_ids_restart_per_tenant_and_admin_can_manage_customers(app_client):
    client, _ = app_client
    first_headers, first = customer_auth(client, "tenant-one-key", "Tenant One Customer")
    _, second = customer_auth(client, "tenant-two-key", "Tenant Two Customer")
    assert first["customer"]["customer_id"] == second["customer"]["customer_id"] == "BI-000001"
    owner = auth(client, "tenant-one")
    customers = client.get("/api/v1/admin/customers", headers=owner).get_json()
    assert [customer["full_name"] for customer in customers] == ["Tenant One Customer"]
    customer_id = customers[0]["_id"]
    assert client.patch(f"/api/v1/admin/customers/{customer_id}", headers=owner, json={"status": "inactive"}).status_code == 200
    assert client.get("/api/v1/customer/dashboard", headers=first_headers).status_code == 401
    disabled_login = client.post("/api/v1/customer/auth/login", json={"full_name": "Tenant One Customer", "customer_id": "BI-000001", "password": "CustomerPass123!", "widget_key": "tenant-one-key"})
    assert disabled_login.status_code == 401


def test_customer_id_allocation_is_atomic_under_parallel_registration(app_client):
    client, _ = app_client
    app = client.application

    def register(index):
        with app.app_context():
            from app.services.customer_service import register_customer

            result, error = register_customer({
                "full_name": f"Parallel Customer {index}",
                "age": 30,
                "reason": "Parallel registration test",
                "password": "CustomerPass123!",
                "widget_key": "tenant-one-key",
            })
            assert error is None
            return result["customer"]["customer_id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        customer_ids = list(executor.map(register, range(4)))

    assert sorted(customer_ids) == ["BI-000001", "BI-000002", "BI-000003", "BI-000004"]


def test_customer_auth_rate_limit_does_not_reveal_credentials(app_client):
    client, _ = app_client
    from app.api.customer import _auth_requests

    _auth_requests.clear()
    payload = {"full_name": "Unknown Person", "customer_id": "BI-999999", "password": "CustomerPass123!", "widget_key": "tenant-one-key"}
    for _ in range(10):
        response = client.post("/api/v1/customer/auth/login", json=payload)
        assert response.status_code == 401
        assert response.get_json()["error"] == "invalid_credentials"
    limited = client.post("/api/v1/customer/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.get_json()["error"] == "rate_limited"


def test_availability_hides_past_dates_and_elapsed_slots(app_client, monkeypatch):
    client, tenants = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    past = client.get("/api/v1/public/availability/slots?date=2020-01-06", headers=key)
    assert past.status_code == 200
    assert past.get_json()["slots"] == []
    assert past.get_json()["timezone"] == "UTC"

    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 7, 9, 15, tzinfo=timezone.utc))
    today = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()
    assert today["slots"]
    assert all("09:00:00" not in slot for slot in today["slots"])
    assert any("09:30:00" in slot for slot in today["slots"])
    expired = client.post("/api/v1/public/appointments", headers=key, json={"start_at": "2030-01-07T09:00:00+00:00", "name": "Late", "email": "late@example.com"})
    assert expired.status_code == 409
    assert "no longer available" in expired.get_json()["message"].lower()


def test_timezone_date_boundaries_accept_equivalent_instants(app_client, monkeypatch):
    client, tenants = app_client
    db = client.application.extensions["mongo_db"]
    db.business_profiles.update_one({"tenant_id": tenants[0][1]}, {"$set": {"timezone": "Asia/Kolkata"}})
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    key = {"X-Widget-Key": "tenant-one-key"}
    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    assert slots
    assert slots[0].endswith("+05:30")
    utc_equivalent = datetime.fromisoformat(slots[0]).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    booked = client.post("/api/v1/public/appointments", headers=key, json={"start_at": utc_equivalent, "name": "Zone Visitor", "email": "zone@example.com"})
    assert booked.status_code == 201, booked.get_json()
    duplicate = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[0], "name": "Zone Visitor", "email": "zone@example.com"})
    assert duplicate.status_code == 409
    outside = client.post("/api/v1/public/appointments", headers=key, json={"start_at": "2030-01-07T09:00:00+00:00", "name": "Wrong Zone", "email": "wrong-zone@example.com"})
    assert outside.status_code == 409


def test_customer_chat_guides_booking_without_inventing_slots(app_client):
    client, _ = app_client
    headers, _ = customer_auth(client, "tenant-one-key", "Booking Customer")
    chat = client.post("/api/v1/customer/chat", headers=headers, json={"message": "Please book me an appointment tomorrow at 9am"})
    assert chat.status_code == 200
    payload = chat.get_json()
    assert payload["intent"] == "appointment"
    assert "booking form" in payload["answer"].lower()
    assert "9am" not in payload["answer"].lower()
    natural_request = client.post("/api/v1/customer/chat", headers=headers, json={"message": "Can we meet on 2030-01-07 at 09:00?"})
    assert natural_request.status_code == 200
    assert natural_request.get_json()["intent"] == "appointment"
    assert "booking form" in natural_request.get_json()["answer"].lower()
    assert client.get("/api/v1/customer/availability/slots?date=2019-12-30", headers=headers).get_json()["slots"] == []
    available = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:00", headers=headers)
    assert available.status_code == 200
    assert available.get_json()["available"] is True
    booked = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:00"})
    assert booked.status_code == 201
    taken = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:00"})
    assert taken.status_code == 409


def test_customer_chat_uses_authenticated_name_only_for_greetings(app_client):
    client, _ = app_client
    first_headers, _ = customer_auth(client, "tenant-one-key", "Asha Singh")
    second_headers, _ = customer_auth(client, "tenant-one-key", "Vikram Rao")

    first = client.post("/api/v1/customer/chat", headers=first_headers, json={"message": "Hello"})
    second = client.post("/api/v1/customer/chat", headers=second_headers, json={"message": "Hello"})

    assert first.status_code == second.status_code == 200
    assert "Asha Singh" in first.get_json()["answer"]
    assert "Vikram Rao" not in first.get_json()["answer"]
    assert "Vikram Rao" in second.get_json()["answer"]
    typo = client.post("/api/v1/customer/chat", headers=first_headers, json={"message": "heelo"})
    assert typo.status_code == 200
    assert "Asha Singh" in typo.get_json()["answer"]
    short_typo = client.post("/api/v1/customer/chat", headers=first_headers, json={"message": "hy"})
    assert short_typo.status_code == 200
    assert "Asha Singh" in short_typo.get_json()["answer"]


def test_customer_books_currently_offered_slot_only(app_client, monkeypatch):
    client, _ = app_client
    headers, _ = customer_auth(client, "tenant-one-key", "Available Customer")
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 7, 9, 15, tzinfo=timezone.utc))

    check = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:30", headers=headers)
    assert check.get_json()["available"] is True
    assert client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:30"}).status_code == 201
    past = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:00"})
    assert past.status_code == 409
    assert "past" in past.get_json()["message"].lower()


def test_customer_books_exact_timezone_slot_returned_by_availability(app_client, monkeypatch):
    client, tenants = app_client
    db = client.application.extensions["mongo_db"]
    db.business_profiles.update_one({"tenant_id": tenants[0][1]}, {"$set": {"timezone": "Asia/Kolkata"}})
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    headers, _ = customer_auth(client, "tenant-one-key", "Timezone Customer")

    availability = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:00", headers=headers)
    assert availability.status_code == 200
    assert availability.get_json()["available"] is True
    booked = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:00"})
    assert booked.status_code == 201, booked.get_json()
    assert booked.get_json()["appointment"]["start_at"].endswith("+05:30")


def test_customer_requested_time_enforces_hours_blocks_and_conflicts(app_client, monkeypatch):
    client, tenants = app_client
    headers, _ = customer_auth(client, "tenant-one-key", "Requested Time Customer")
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    db = client.application.extensions["mongo_db"]
    tenant = tenants[0][1]
    db.blocked_times.insert_one({"tenant_id": tenant, "start_at": datetime(2030, 1, 7, 9, 30, tzinfo=timezone.utc), "end_at": datetime(2030, 1, 7, 10, 0, tzinfo=timezone.utc)})

    outside = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=08:45", headers=headers)
    assert outside.get_json()["available"] is False
    blocked = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:30", headers=headers)
    assert blocked.get_json()["available"] is False
    first = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:00"})
    assert first.status_code == 201
    overlap = client.post("/api/v1/customer/appointments", headers=headers, json={"date": "2030-01-07", "time": "09:15"})
    assert overlap.status_code == 409
    assert "conflicts with an existing appointment" in overlap.get_json()["message"].lower()


def test_concurrent_customer_requested_time_creates_only_one_appointment(app_client, monkeypatch):
    client, tenants = app_client
    app = client.application
    tenant_id = str(tenants[0][1])
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))

    def book_once():
        with app.app_context():
            from app.services.scheduling_service import create_appointment, customer_requested_start

            start, error = customer_requested_start(tenant_id, "2030-01-07", "09:00")
            assert error is None
            appointment, error = create_appointment(
                tenant_id,
                {"start_at": start.isoformat(), "name": "Concurrent", "email": "concurrent@example.com"},
                allow_customer_requested_time=True,
            )
            return appointment is not None, error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: book_once(), range(2)))

    assert sum(created for created, _ in results) == 1
    assert any(error and ("just booked" in error or "not available" in error) for _, error in results)


def test_public_visitor_greetings_use_configured_business_name(app_client):
    client, _ = app_client
    first = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "Hello"})
    second = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-two-key"}, json={"message": "Hi"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["answer"] == "Hello. I can help with Tenant One's approved services, FAQs, or appointment booking."
    assert second.get_json()["answer"] == "Hello. I can help with Tenant Two's approved services, FAQs, or appointment booking."

    typo = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "heelo"})
    assert typo.status_code == 200
    assert "Tenant One" in typo.get_json()["answer"]

    hey = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "hey there"})
    assert hey.status_code == 200
    assert "Tenant One" in hey.get_json()["answer"]


def test_service_question_retrieves_published_official_knowledge(app_client):
    client, tenants = app_client
    db = client.application.extensions["mongo_db"]
    tenant_id = tenants[0][1]

    db.knowledge.insert_many([
        {
            "tenant_id": tenant_id,
            "title": "What does Black Intel do?",
            "content": "Black Intel combines cybersecurity, artificial intelligence, digital forensics, and counter-intelligence.",
            "source_url": "https://theblackintel.com/",
            "status": "published",
        },
        {
            "tenant_id": tenant_id,
            "title": "What services does Black Intel offer?",
            "content": "Black Intel lists digital forensics, cyber offense, and defensive security as core divisions.",
            "source_url": "https://theblackintel.com/",
            "status": "published",
        },
        {
            "tenant_id": tenant_id,
            "title": "Refund policy",
            "content": "All sales and retainers are final according to contract agreements.",
            "source_url": "https://theblackintel.com/terms",
            "status": "published",
        },
    ])

    key = "tenant-one-key"
    ans_provide = chat(client, key, "What services do you provide?")
    assert "core divisions" in ans_provide.lower()
    assert "digital forensics" in ans_provide.lower()

    ans_offer = chat(client, key, "What services do you offer?")
    assert "core divisions" in ans_offer.lower()

    ans_services = chat(client, key, "What are your services?")
    assert "core divisions" in ans_services.lower()

    ans_do = chat(client, key, "What does Black Intel do?")
    assert "counter-intelligence" in ans_do.lower()


def test_customer_reschedule_excludes_own_appointment_and_enforces_auth(app_client, monkeypatch):
    client, tenants = app_client
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))

    headers_a, customer_a = customer_auth(client, "tenant-one-key", "Customer A")
    headers_b, customer_b = customer_auth(client, "tenant-one-key", "Customer B")

    booked_a = client.post("/api/v1/customer/appointments", headers=headers_a, json={"date": "2030-01-07", "time": "09:00"})
    assert booked_a.status_code == 201
    appt_a_id = booked_a.get_json()["appointment"]["_id"]

    booked_b = client.post("/api/v1/customer/appointments", headers=headers_b, json={"date": "2030-01-07", "time": "09:30"})
    assert booked_b.status_code == 201
    appt_b_id = booked_b.get_json()["appointment"]["_id"]

    check_own_conflict = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:00", headers=headers_a)
    assert check_own_conflict.get_json()["available"] is False
    assert "conflicts with an existing appointment" in check_own_conflict.get_json()["message"].lower()

    check_self_excluded = client.get(f"/api/v1/customer/availability/check?date=2030-01-07&time=09:00&appointment_id={appt_a_id}", headers=headers_a)
    assert check_self_excluded.status_code == 200
    assert check_self_excluded.get_json()["available"] is True
    assert "available" in check_self_excluded.get_json()["message"].lower()

    slots_response = client.get(f"/api/v1/customer/availability/slots?date=2030-01-07&appointment_id={appt_a_id}", headers=headers_a)
    assert slots_response.status_code == 200
    assert any("09:00" in slot for slot in slots_response.get_json()["slots"])

    stolen_check = client.get(f"/api/v1/customer/availability/check?date=2030-01-07&time=09:00&appointment_id={appt_a_id}", headers=headers_b)
    assert stolen_check.status_code == 403
    assert stolen_check.get_json()["error"] == "appointment_not_authorized"

    conflict_check = client.get(f"/api/v1/customer/availability/check?date=2030-01-07&time=09:30&appointment_id={appt_a_id}", headers=headers_a)
    assert conflict_check.status_code == 200
    assert conflict_check.get_json()["available"] is False
    assert "conflicts with an existing appointment" in conflict_check.get_json()["message"].lower()

    rescheduled_a = client.post(f"/api/v1/customer/appointments/{appt_a_id}/reschedule", headers=headers_a, json={"date": "2030-01-08", "time": "09:00"})
    assert rescheduled_a.status_code == 200
    assert rescheduled_a.get_json()["appointment"]["status"] == "rescheduled"


def test_company_blocked_times_produce_specific_message(app_client, monkeypatch):
    client, tenants = app_client
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    db = client.application.extensions["mongo_db"]
    tenant_id = tenants[0][1]

    db.blocked_times.insert_one({
        "tenant_id": tenant_id,
        "start_at": datetime(2030, 1, 7, 9, 30, tzinfo=timezone.utc),
        "end_at": datetime(2030, 1, 7, 10, 0, tzinfo=timezone.utc),
    })

    headers, _ = customer_auth(client, "tenant-one-key", "Blocked Customer")
    response = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=09:30", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["available"] is False
    assert "company-blocked period" in response.get_json()["message"]


def test_public_widget_rescheduling_excludes_held_slot_with_token(app_client):
    client, _ = app_client
    key = {"X-Widget-Key": "tenant-one-key"}

    slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    assert slots
    first_slot = slots[0]
    booked = client.post("/api/v1/public/appointments", headers=key, json={"start_at": first_slot, "name": "Visitor Held", "email": "held@example.com"})
    assert booked.status_code == 201
    appt = booked.get_json()["appointment"]
    appt_id = appt["_id"]
    token = appt["manage_token"]

    subsequent_slots = client.get("/api/v1/public/availability/slots?date=2030-01-07", headers=key).get_json()["slots"]
    assert first_slot not in subsequent_slots

    reschedule_slots = client.get(f"/api/v1/public/availability/slots?date=2030-01-07&appointment_id={appt_id}&manage_token={token}", headers=key)
    assert reschedule_slots.status_code == 200
    assert first_slot in reschedule_slots.get_json()["slots"]

    bad_token_slots = client.get(f"/api/v1/public/availability/slots?date=2030-01-07&appointment_id={appt_id}&manage_token=wrong_token_123456789012345", headers=key)
    assert bad_token_slots.status_code == 403


def test_admin_availability_slots_and_reschedule_validation(app_client):
    client, tenants = app_client
    key = {"X-Widget-Key": "tenant-one-key"}
    owner = auth(client, "tenant-one")
    other_owner = auth(client, "tenant-two")
    db = client.application.extensions["mongo_db"]
    tenant_id = tenants[0][1]

    # 1. Admin slots endpoint requires auth
    unauth = client.get("/api/v1/admin/availability/slots?date=2030-01-07")
    assert unauth.status_code == 401

    # Missing date param (400)
    assert client.get("/api/v1/admin/availability/slots", headers=owner).status_code == 400
    # Invalid date format (400)
    assert client.get("/api/v1/admin/availability/slots?date=invalid-date", headers=owner).status_code == 400

    # Get offered slots for 2030-01-07 (Monday: 09:00, 09:30)
    slots_resp = client.get("/api/v1/admin/availability/slots?date=2030-01-07", headers=owner)
    assert slots_resp.status_code == 200
    slots = slots_resp.get_json()["slots"]
    assert len(slots) == 2

    # Book two appointments on Monday
    booked1 = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[0], "name": "Admin Test 1", "email": "t1@example.com"}).get_json()["appointment"]
    booked2 = client.post("/api/v1/public/appointments", headers=key, json={"start_at": slots[1], "name": "Admin Test 2", "email": "t2@example.com"}).get_json()["appointment"]
    appt1_id = booked1["_id"]
    appt2_id = booked2["_id"]

    # Slot 0 is taken, but excluding appt1 makes slot 0 available again
    admin_slots_with_appt = client.get(f"/api/v1/admin/availability/slots?date=2030-01-07&appointment_id={appt1_id}", headers=owner)
    assert admin_slots_with_appt.status_code == 200
    assert slots[0] in admin_slots_with_appt.get_json()["slots"]
    # But slot 1 (held by appt2) is excluded
    assert slots[1] not in admin_slots_with_appt.get_json()["slots"]

    # Tenant isolation on admin slots appointment_id lookup
    assert client.get(f"/api/v1/admin/availability/slots?date=2030-01-07&appointment_id={appt1_id}", headers=other_owner).status_code == 404

    # 2. Rescheduling validation reports specific reasons

    # A) Invalid start_at format (400)
    invalid_format = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "not-a-datetime"})
    assert invalid_format.status_code == 400
    assert "A valid appointment start time is required." in invalid_format.get_json()["message"]

    # B) Closed business day (Sunday 2030-01-06)
    closed_day = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "2030-01-06T09:00:00+00:00"})
    assert closed_day.status_code == 409
    assert "business is not available on that date" in closed_day.get_json()["message"]

    # C) Outside business hours (04:00 AM)
    outside_hours = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "2030-01-07T04:00:00+00:00"})
    assert outside_hours.status_code == 409
    assert "outside business hours" in outside_hours.get_json()["message"]

    # D) Conflict with existing appointment (appt1 into appt2's slot 1)
    conflict_res = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": slots[1]})
    assert conflict_res.status_code == 409
    assert "conflicts with an existing appointment" in conflict_res.get_json()["message"]

    # E) Company-blocked period on Tuesday 2030-01-08 at 09:30
    db.blocked_times.insert_one({
        "tenant_id": tenant_id,
        "start_at": datetime(2030, 1, 8, 9, 30, tzinfo=timezone.utc),
        "end_at": datetime(2030, 1, 8, 10, 0, tzinfo=timezone.utc),
    })
    blocked_res = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "2030-01-08T09:30:00+00:00"})
    assert blocked_res.status_code == 409
    assert "company-blocked period" in blocked_res.get_json()["message"]

    # F) Invalid slot intervals on Wednesday (09:15 when slots are 09:00 and 09:30)
    interval_res = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "2030-01-09T09:15:00+00:00"})
    assert interval_res.status_code == 409
    assert "does not align with the configured appointment slot intervals" in interval_res.get_json()["message"]

    # G) Valid reschedule to Tuesday 09:00 offered slot
    valid_res = client.post(f"/api/v1/admin/appointments/{appt1_id}/reschedule", headers=owner, json={"start_at": "2030-01-08T09:00:00+00:00"})
    assert valid_res.status_code == 200
    assert valid_res.get_json()["status"] == "rescheduled"
    assert valid_res.get_json()["history"][-1]["action"] == "admin_rescheduled"
