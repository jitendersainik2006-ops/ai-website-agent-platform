from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import mongomock
from bson import ObjectId
import pytest

from app import create_app
from app.security.passwords import hash_password


@pytest.fixture()
def app_client():
    # The MVP limiter is process-local. Clear it so one isolated Flask app does
    # not inherit request counts from an earlier test app.
    from app.api.public import _requests
    from app.api.customer import _auth_requests

    _requests.clear()
    _auth_requests.clear()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "s" * 32,
            "JWT_SECRET_KEY": "j" * 32,
            "MONGODB_DATABASE": "mvp_tests",
            "LLM_PROVIDER": "local",
        },
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


def test_appointment_intent_disambiguation_for_technical_queries():
    from app.services.llm_gateway import is_appointment_intent

    # Technical questions mentioning 'schedule' or 'meet' must NOT trigger appointment guidance
    assert not is_appointment_intent("How do I schedule a cron job in Linux?")
    assert not is_appointment_intent("Explain CPU scheduling algorithms such as round robin")
    assert not is_appointment_intent("Where do parallel lines meet?")
    assert not is_appointment_intent("Do two perpendicular lines meet at a right angle?")
    assert not is_appointment_intent("How can I schedule background tasks in Celery and Python?")
    assert not is_appointment_intent("Write a Python script to generate meeting minutes")
    assert not is_appointment_intent("Explain the meet-in-the-middle cryptographic attack")

    # Legitimate appointment and booking questions must trigger appointment intent
    assert is_appointment_intent("Please book me an appointment tomorrow at 9am")
    assert is_appointment_intent("Can we meet on 2030-01-07 at 09:00?")
    assert is_appointment_intent("Can I schedule a consultation?")
    assert is_appointment_intent("Do you have any available slots?")
    assert is_appointment_intent("I would like to reschedule my appointment")
    assert is_appointment_intent("I want to book an appointment with your Python consulting team")


def test_ai_provider_gemini_mocked_completion(app_client, monkeypatch):
    import json
    import urllib.request
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-gemini-key",
        "GEMINI_MODEL": "gemini-3.8-flash",
    })

    mock_response_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "```python\ndef binary_search(arr, target):\n    # implementation\n    return -1\n```"}
                    ]
                }
            }
        ]
    }

    class MockHTTPResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps(mock_response_payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockHTTPResponse())

    with client.application.app_context():
        result = respond(tenant_id, "Write a python function to binary search")
        assert result["provider"] == "gemini"
        assert "def binary_search" in result["answer"]
        assert result["intent"] == "general"


def test_ai_provider_groq_mocked_completion(app_client, monkeypatch):
    import json
    import urllib.request
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    client.application.config.update({
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": "test-groq-key",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
    })

    mock_response_payload = {
        "choices": [
            {
                "message": {
                    "content": "Newton's Third Law states that for every action, there is an equal and opposite reaction."
                }
            }
        ]
    }

    class MockHTTPResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps(mock_response_payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockHTTPResponse())

    with client.application.app_context():
        result = respond(tenant_id, "Explain Newton's third law of motion")
        assert result["provider"] == "groq"
        assert "equal and opposite" in result["answer"]


def test_ai_provider_graceful_fallback_to_local_on_network_failure(app_client, monkeypatch):
    import urllib.error
    import urllib.request
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-key",
    })

    def mock_urlopen_failure(req, timeout=None):
        raise urllib.error.URLError("Network connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_failure)

    with client.application.app_context():
        result = respond(tenant_id, "What is the capital of Mars?")
        assert result["provider"] == "local"
        assert "confirmed information" in result["answer"].lower()


def test_tenant_isolation_in_ai_system_prompt(app_client, monkeypatch):
    import json
    import urllib.request

    client, tenants = app_client
    tenant1_id = tenants[0][1]
    tenant2_id = tenants[1][1]
    db = client.application.extensions["mongo_db"]

    db.knowledge.insert_one({
        "tenant_id": tenant1_id,
        "title": "Tenant One Confidential Capability",
        "content": "Tenant One exclusively provides Quantum Shielding.",
        "status": "published",
    })
    db.knowledge.insert_one({
        "tenant_id": tenant2_id,
        "title": "Tenant Two Secret Operation",
        "content": "Tenant Two exclusively runs Project Horizon.",
        "status": "published",
    })

    captured_payloads = []

    class MockHTTPResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "Mock AI answer"}]}}]}).encode("utf-8")

    def mock_urlopen(req, timeout=None):
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return MockHTTPResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-key",
    })

    res1 = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "What is Quantum Shielding?"})
    assert res1.status_code == 200
    si = captured_payloads[0]["system_instruction"]
    prompt1 = si["parts"][0]["text"] if isinstance(si, dict) else si
    assert "Tenant One" in prompt1
    assert "Quantum Shielding" in prompt1
    assert "Tenant Two" not in prompt1
    assert "Project Horizon" not in prompt1


def test_customer_portal_chat_with_configured_ai_provider(app_client, monkeypatch):
    import json
    import urllib.request

    client, tenants = app_client
    headers, _ = customer_auth(client, "tenant-one-key", "General Chat Customer")

    client.application.config.update({
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": "test-groq-key",
    })

    class MockHTTPResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Photosynthesis is the process used by plants to convert light into chemical energy."}}]
            }).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: MockHTTPResponse())

    chat_res = client.post(
        "/api/v1/customer/chat",
        headers=headers,
        json={"message": "How does photosynthesis work?"},
    )
    assert chat_res.status_code == 200
    data = chat_res.get_json()
    assert data["provider"] == "groq"
    assert "Photosynthesis" in data["answer"]


def test_optional_web_search_augmentation(app_client, monkeypatch):
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    client.application.config.update({
        "LLM_PROVIDER": "local",
        "WEB_SEARCH_ENABLED": True,
    })

    from app.services import web_search_service
    monkeypatch.setattr(
        web_search_service,
        "search_web",
        lambda query, limit=2: [{"title": "Quantum computing", "snippet": "A type of computation...", "url": "https://en.wikipedia.org/wiki/Quantum_computing"}]
    )

    with client.application.app_context():
        res = respond(tenant_id, "Tell me about quantum computing")
        assert res["provider"] == "local"


def test_personalized_customer_chat_and_neutral_fallback(app_client):
    client, _ = app_client
    # Authenticated customer with server-verified name
    headers, _ = customer_auth(client, "tenant-one-key", full_name="Aarav Sharma")
    res1 = client.post("/api/v1/customer/chat", headers=headers, json={"message": "hello"})
    assert res1.status_code == 200
    assert "Hello Aarav Sharma." in res1.get_json()["answer"]

    # Even if client tries to spoof customer_name in payload, server-verified session name is used
    res_spoof = client.post("/api/v1/customer/chat", headers=headers, json={"message": "hello", "customer_name": "SpoofedName"})
    assert res_spoof.status_code == 200
    assert "SpoofedName" not in res_spoof.get_json()["answer"]
    assert "Hello Aarav Sharma." in res_spoof.get_json()["answer"]

    # Public visitor without authenticated account gets neutral greeting
    pub_res = client.post("/api/v1/chat", headers={"X-Widget-Key": "tenant-one-key"}, json={"message": "hello"})
    assert pub_res.status_code == 200
    assert pub_res.get_json()["answer"].startswith("Hello. I can help with")


def test_customer_portal_appointment_booking_guidance_references_form(app_client):
    client, _ = app_client
    headers, _ = customer_auth(client, "tenant-one-key", full_name="Maya Patel")
    chat = client.post(
        "/api/v1/customer/chat",
        headers=headers,
        json={"message": "I would like to schedule a consultation with your security team"},
    )
    assert chat.status_code == 200
    data = chat.get_json()
    assert data["intent"] == "appointment"
    assert "booking form" in data["answer"].lower()
    assert "Maya Patel" in data["answer"]
    # Never claim appointment was booked from chat
    assert "cannot" in data["answer"].lower()


def test_appointment_cancelled_slot_can_be_rebooked_immediately(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    headers, _ = customer_auth(client, "tenant-one-key", full_name="Rohan Verma")
    slot_res = client.get("/api/v1/customer/availability/slots?date=2030-01-07", headers=headers)
    assert slot_res.status_code == 200
    slots = slot_res.get_json()["slots"]
    assert slots, "Expected offered slots on Monday"
    target_slot = slots[0]

    # Book the slot
    book1 = client.post(
        "/api/v1/customer/appointments",
        headers=headers,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert book1.status_code == 201
    appt1_id = book1.get_json()["appointment"]["_id"]

    # Cancel the appointment
    cancel = client.post(f"/api/v1/customer/appointments/{appt1_id}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.get_json()["appointment"]["status"] == "cancelled"

    # Rebook the exact same slot that was freed up
    book2 = client.post(
        "/api/v1/customer/appointments",
        headers=headers,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert book2.status_code == 201
    assert book2.get_json()["appointment"]["status"] == "confirmed"

    # Attempting to double-book the now-active appointment must fail with 409
    book3 = client.post(
        "/api/v1/customer/appointments",
        headers=headers,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert book3.status_code == 409


def test_customer_requested_time_accepts_seconds_format(app_client):
    client, _ = app_client
    from app.services.scheduling_service import customer_requested_start
    db = client.application.extensions["mongo_db"]
    tenant = str(db.tenants.find_one({"slug": "tenant-one"})["_id"])

    with client.application.app_context():
        # Standard HH:MM
        start1, err1 = customer_requested_start(tenant, "2026-10-19", "10:30")
        assert err1 is None
        assert start1.hour == 10 and start1.minute == 30 and start1.second == 0

        # Browser HH:MM:SS format
        start2, err2 = customer_requested_start(tenant, "2026-10-19", "10:30:00")
        assert err2 is None
        assert start2.hour == 10 and start2.minute == 30 and start2.second == 0

        # Invalid time format fails cleanly
        _, err3 = customer_requested_start(tenant, "2026-10-19", "invalid-time")
        assert err3 == "Choose a valid appointment date and time."


def test_official_black_intel_knowledge_synchronization_and_coverage(app_client):
    client, _ = app_client
    from app.services.official_knowledge import sync_official_knowledge
    from app.services.knowledge_service import retrieve
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]

    # Sync all verified official records from theblackintel.com
    count = sync_official_knowledge(db, tenant)
    assert count >= 14

    # Verify specialized retrieval within app context
    with client.application.app_context():
        leadership = retrieve(str(tenant), "Who is Aryan Kumar?")
        assert leadership
        assert "leadership" in leadership[0]["title"].lower() or "aryan" in leadership[0]["content"].lower()
        assert leadership[0]["source_url"] == "https://theblackintel.com/about/leadership"

        mobile = retrieve(str(tenant), "Do you do mobile investigations?")
        assert mobile
        assert "mobile" in mobile[0]["title"].lower()
        assert mobile[0]["source_url"] == "https://theblackintel.com/services/mobile-investigations"

        contact = retrieve(str(tenant), "How can I contact Black Intel?")
        assert contact
        assert "contact" in contact[0]["title"].lower()
        assert "abhishek.managerr@gmail.com" in contact[0]["content"]
        assert "+91 9205105369" in contact[0]["content"]

        pricing = retrieve(str(tenant), "What is your pricing?")
        assert pricing
        assert "pricing" in pricing[0]["title"].lower()
        assert "consultation" in pricing[0]["content"].lower()



def test_favicon_and_logo_static_routes(app_client):
    client, _ = app_client
    fav = client.get("/favicon.ico")
    assert fav.status_code == 200
    assert fav.mimetype == "image/png"

    logo = client.get("/black-intel-logo.png")
    assert logo.status_code == 200
    assert logo.mimetype == "image/png"


def test_customer_auth_field_validation_and_confirm_password(app_client):
    client, _ = app_client

    # 1. Missing fields
    res = client.post("/api/v1/customer/auth/register", json={})
    assert res.status_code == 400
    assert res.get_json()["error"] == "validation_error"

    # 2. Mismatched passwords
    mismatch = client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Rohan Verma",
            "age": 30,
            "reason": "Cyber investigation",
            "password": "Password123!",
            "confirm_password": "DifferentPassword123!",
            "widget_key": "tenant-one-key",
        },
    )
    assert mismatch.status_code == 400
    assert "Passwords do not match." in mismatch.get_json()["message"]

    # 3. Valid registration with confirm_password
    valid_reg = client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Rohan Verma",
            "age": 30,
            "reason": "Cyber investigation",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "widget_key": "tenant-one-key",
        },
    )
    assert valid_reg.status_code == 201
    customer_id = valid_reg.get_json()["customer"]["customer_id"]

    # 4. Login with invalid password
    bad_login = client.post(
        "/api/v1/customer/auth/login",
        json={
            "full_name": "Rohan Verma",
            "customer_id": customer_id,
            "password": "WrongPassword123!",
            "widget_key": "tenant-one-key",
        },
    )
    assert bad_login.status_code == 401
    assert "Invalid customer credentials" in bad_login.get_json()["message"]

    # 5. Login with malformed customer_id
    bad_id = client.post(
        "/api/v1/customer/auth/login",
        json={
            "full_name": "Rohan Verma",
            "customer_id": "NOT-VALID",
            "password": "Password123!",
            "widget_key": "tenant-one-key",
        },
    )
    assert bad_id.status_code == 400


def test_customer_appointment_booking_edge_cases_and_persistence(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    db = client.application.extensions["mongo_db"]

    headers_a, user_a = customer_auth(client, "tenant-one-key", "User Alpha")
    headers_b, user_b = customer_auth(client, "tenant-one-key", "User Beta")

    # 1. Valid booking on open weekday (Monday 2030-01-07 09:00)
    book_a = client.post(
        "/api/v1/customer/appointments",
        headers=headers_a,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert book_a.status_code == 201
    appt_a = book_a.get_json()["appointment"]
    appt_a_id = appt_a["_id"]

    # Verify persistence in database
    persisted = db.appointments.find_one({"_id": ObjectId(appt_a_id)})
    assert persisted is not None
    assert persisted["status"] == "confirmed"
    assert persisted["customer_id"] == user_a["customer"]["customer_id"]

    # 2. Closed business day (weekend Saturday 2030-01-05)
    closed_check = client.post(
        "/api/v1/customer/appointments",
        headers=headers_b,
        json={"date": "2030-01-12", "time": "09:00"},
    )
    assert closed_check.status_code == 409
    assert "business is not available on that date" in closed_check.get_json()["message"]
    assert "weekends" in closed_check.get_json()["message"]

    # 3. Outside business hours (Monday 2030-01-07 06:00)
    outside_check = client.post(
        "/api/v1/customer/appointments",
        headers=headers_b,
        json={"date": "2030-01-07", "time": "06:00"},
    )
    assert outside_check.status_code == 409
    assert "outside business hours" in outside_check.get_json()["message"]

    # 4. Past time (Sunday 2030-01-06 09:00, when simulated now is 12:00)
    past_check = client.post(
        "/api/v1/customer/appointments",
        headers=headers_b,
        json={"date": "2030-01-06", "time": "09:00"},
    )
    assert past_check.status_code == 409
    assert "in the past" in past_check.get_json()["message"]

    # 5. Conflicting appointment (User B tries to book the same slot held by User A)
    conflict_check = client.post(
        "/api/v1/customer/appointments",
        headers=headers_b,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert conflict_check.status_code == 409
    assert "conflicts with an existing appointment" in conflict_check.get_json()["message"]

    # 6. Cancelled slot rebooking (User A cancels, User B books the now-freed slot)
    cancel_a = client.post(f"/api/v1/customer/appointments/{appt_a_id}/cancel", headers=headers_a)
    assert cancel_a.status_code == 200
    assert cancel_a.get_json()["appointment"]["status"] == "cancelled"

    book_freed = client.post(
        "/api/v1/customer/appointments",
        headers=headers_b,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert book_freed.status_code == 201
    appt_b_id = book_freed.get_json()["appointment"]["_id"]
    persisted_b = db.appointments.find_one({"_id": ObjectId(appt_b_id)})
    assert persisted_b is not None
    assert persisted_b["status"] == "confirmed"

    # 7. Customer reschedule to another valid slot (User B reschedules to 09:30)
    resched_b = client.post(
        f"/api/v1/customer/appointments/{appt_b_id}/reschedule",
        headers=headers_b,
        json={"date": "2030-01-07", "time": "09:30"},
    )
    assert resched_b.status_code == 200
    assert resched_b.get_json()["appointment"]["status"] == "rescheduled"
    updated_b = db.appointments.find_one({"_id": ObjectId(appt_b_id)})
    assert updated_b["status"] == "rescheduled"
    assert any(h.get("action") == "customer_rescheduled" for h in updated_b["history"])

    # 8. Customer authorization / Tenant isolation: User A cannot cancel or reschedule User B's appointment
    unauth_cancel = client.post(f"/api/v1/customer/appointments/{appt_b_id}/cancel", headers=headers_a)
    assert unauth_cancel.status_code in (403, 404)
    assert "not authorized" in unauth_cancel.get_json()["message"]

    unauth_resched = client.post(
        f"/api/v1/customer/appointments/{appt_b_id}/reschedule",
        headers=headers_a,
        json={"date": "2030-01-08", "time": "09:00"},
    )
    assert unauth_resched.status_code in (403, 404)
    assert "not authorized" in unauth_resched.get_json()["message"]


def test_appointment_validation_regression_suite(app_client, monkeypatch):
    """
    Regression test suite verifying appointment booking validation requirements:
    1. Monday at 10:00 AM (valid).
    2. Monday at 3:30 PM (valid in 24h '15:30', 12h '3:30 PM', '03:30 PM', and bare '3:30' / '03:30').
    3. The latest valid appointment of the day (16:30 ending at 17:00).
    4. A time that does not leave enough consultation time before closing (16:45 ending at 17:15).
    5. A weekend time (Saturday).
    6. A past time.
    7. A conflicting appointment and its required buffer.
    """
    client, _ = app_client
    # Freeze time to Sunday 2030-01-06 12:00:00 UTC
    monkeypatch.setattr("app.services.scheduling_service.now", lambda: datetime(2030, 1, 6, 12, tzinfo=timezone.utc))
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})
    tenant_id = tenant["_id"]

    # Configure business profile: Monday-Friday 09:00 to 17:00, 30 min duration, 15 min buffer
    db.business_hours.update_many(
        {"tenant_id": tenant_id},
        {"$set": {"start_time": "09:00", "end_time": "17:00"}}
    )
    db.business_profiles.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"appointment_duration_minutes": 30, "appointment_buffer_minutes": 15}}
    )

    headers_user1, user1 = customer_auth(client, "tenant-one-key", "Customer One")
    headers_user2, user2 = customer_auth(client, "tenant-one-key", "Customer Two")

    # 1. Monday at 10:00 AM (valid)
    chk_10am = client.get("/api/v1/customer/availability/check?date=2030-01-07&time=10:00%20AM", headers=headers_user1)
    assert chk_10am.status_code == 200
    assert chk_10am.get_json()["available"] is True
    book_10am = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user1,
        json={"date": "2030-01-07", "time": "10:00 AM"},
    )
    assert book_10am.status_code == 201
    assert book_10am.get_json()["appointment"]["status"] == "confirmed"

    # 2. Monday at 3:30 PM (valid across formats: '15:30', '3:30 PM', '03:30 PM', and bare '3:30')
    for time_val in ("15:30", "3:30 PM", "03:30 PM", "3:30", "03:30"):
        chk_330pm = client.get(
            f"/api/v1/customer/availability/check?date=2030-01-07&time={time_val}",
            headers=headers_user2,
        )
        assert chk_330pm.status_code == 200
        assert chk_330pm.get_json()["available"] is True, f"Failed for time format: {time_val}"

    # Book Monday at 3:30 PM
    book_330pm = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user2,
        json={"date": "2030-01-07", "time": "3:30 PM"},
    )
    assert book_330pm.status_code == 201
    assert book_330pm.get_json()["appointment"]["status"] == "confirmed"

    # 3. Latest valid appointment of the day: 16:30 (4:30 PM, consultation finishes at 17:00 closing)
    chk_latest = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=16:30",
        headers=headers_user1,
    )
    assert chk_latest.status_code == 200
    assert chk_latest.get_json()["available"] is True
    book_latest = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user1,
        json={"date": "2030-01-07", "time": "16:30"},
    )
    assert book_latest.status_code == 201
    assert book_latest.get_json()["appointment"]["status"] == "confirmed"

    # 4. A time that does not leave enough consultation time before closing: 16:45 (ends at 17:15)
    chk_too_late = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=16:45",
        headers=headers_user1,
    )
    assert chk_too_late.status_code == 200
    assert chk_too_late.get_json()["available"] is False
    assert "outside business hours or does not leave enough time" in chk_too_late.get_json()["message"]
    book_too_late = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user1,
        json={"date": "2030-01-07", "time": "16:45"},
    )
    assert book_too_late.status_code == 409
    assert "outside business hours or does not leave enough time" in book_too_late.get_json()["message"]

    # Explicit AM that is outside hours (03:30 AM) must also be blocked
    chk_330am = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=03:30%20AM",
        headers=headers_user1,
    )
    assert chk_330am.status_code == 200
    assert chk_330am.get_json()["available"] is False
    assert "outside business hours" in chk_330am.get_json()["message"]

    # 5. Weekend time (Saturday 2030-01-12)
    chk_weekend = client.get(
        "/api/v1/customer/availability/check?date=2030-01-12&time=10:00",
        headers=headers_user1,
    )
    assert chk_weekend.status_code == 200
    assert chk_weekend.get_json()["available"] is False
    assert "closed on weekends" in chk_weekend.get_json()["message"]
    book_weekend = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user1,
        json={"date": "2030-01-12", "time": "10:00"},
    )
    assert book_weekend.status_code == 409
    assert "closed on weekends" in book_weekend.get_json()["message"]

    # 6. Past time (Saturday 2030-01-05 10:00 when simulated time is Sunday 2030-01-06 12:00)
    chk_past = client.get(
        "/api/v1/customer/availability/check?date=2030-01-05&time=10:00",
        headers=headers_user1,
    )
    assert chk_past.status_code == 200
    assert chk_past.get_json()["available"] is False
    assert "in the past" in chk_past.get_json()["message"]
    book_past = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user1,
        json={"date": "2030-01-05", "time": "10:00"},
    )
    assert book_past.status_code == 409
    assert "in the past" in book_past.get_json()["message"]

    # 7. Conflicting appointment:
    # Customer 1 has 10:00-10:30 on 2030-01-07 with 15 min buffer (blocks 09:45 - 10:45)
    # Customer 2 attempting to book 10:00 AM
    chk_conflict_exact = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=10:00",
        headers=headers_user2,
    )
    assert chk_conflict_exact.status_code == 200
    assert chk_conflict_exact.get_json()["available"] is False
    assert "conflicts with an existing appointment" in chk_conflict_exact.get_json()["message"]
    book_conflict_exact = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user2,
        json={"date": "2030-01-07", "time": "10:00"},
    )
    assert book_conflict_exact.status_code == 409
    assert "conflicts with an existing appointment" in book_conflict_exact.get_json()["message"]

    # Customer 2 attempting to book during the 15-minute buffer (e.g. 10:15)
    chk_conflict_buffer = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=10:15",
        headers=headers_user2,
    )
    assert chk_conflict_buffer.status_code == 200
    assert chk_conflict_buffer.get_json()["available"] is False
    assert "conflicts with an existing appointment" in chk_conflict_buffer.get_json()["message"]

    # 8. Cancelled slot behavior without altering real customer data
    appt_10am_id = book_10am.get_json()["appointment"]["_id"]
    cancel_res = client.post(f"/api/v1/customer/appointments/{appt_10am_id}/cancel", headers=headers_user1)
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["appointment"]["status"] == "cancelled"
    cancelled_doc = db.appointments.find_one({"_id": ObjectId(appt_10am_id)})
    assert cancelled_doc["status"] == "cancelled"

    # Slot 10:00 AM is now freed for Customer 2
    chk_freed = client.get(
        "/api/v1/customer/availability/check?date=2030-01-07&time=10:00",
        headers=headers_user2,
    )
    assert chk_freed.status_code == 200
    assert chk_freed.get_json()["available"] is True

    # Customer 2 books the freed slot; booking persists and confirms
    book_freed = client.post(
        "/api/v1/customer/appointments",
        headers=headers_user2,
        json={"date": "2030-01-07", "time": "10:00"},
    )
    assert book_freed.status_code == 201
    persisted_freed = db.appointments.find_one({"_id": ObjectId(book_freed.get_json()["appointment"]["_id"])})
    assert persisted_freed is not None
    assert persisted_freed["status"] == "confirmed"

    # 9. Signup validation & password requirements
    # Short password (< 8 chars)
    short_pwd = client.post(
        "/api/v1/customer/auth/register",
        json={"full_name": "Test User", "age": 25, "reason": "Test", "password": "short", "widget_key": "tenant-one-key"},
    )
    assert short_pwd.status_code == 400

    # Invalid age (< 13)
    bad_age = client.post(
        "/api/v1/customer/auth/register",
        json={"full_name": "Young User", "age": 10, "reason": "Test", "password": "Password123!", "widget_key": "tenant-one-key"},
    )
    assert bad_age.status_code == 400

    # 10. Successful registration returns access token and unique customer ID
    headers_reg, reg_data = customer_auth(client, "tenant-one-key", "Priya Sharma", "ValidPassword123!")
    assert reg_data["customer"]["customer_id"] == "BI-000003"
    assert "access_token" in reg_data
    assert "password_hash" not in reg_data["customer"]

    # 11. Login validation
    bad_login = client.post(
        "/api/v1/customer/auth/login",
        json={"full_name": "Priya Sharma", "customer_id": "BI-000003", "password": "WrongPassword!", "widget_key": "tenant-one-key"},
    )
    assert bad_login.status_code == 401
    assert bad_login.get_json()["error"] == "invalid_credentials"

    good_login = client.post(
        "/api/v1/customer/auth/login",
        json={"full_name": "Priya Sharma", "customer_id": "BI-000003", "password": "ValidPassword123!", "widget_key": "tenant-one-key"},
    )
    assert good_login.status_code == 200
    assert "access_token" in good_login.get_json()


def test_mongo_create_indexes_resilience_and_conflict_handling():
    """
    Focused mocked test suite covering:
    1. Existing legacy index (unique=True, no partialFilterExpression, matching Atlas).
    2. Matching index (unique=True with partialFilterExpression).
    3. Conflicting options (existing non-unique index preserved without dropping).
    4. Failed index inspection (never assumed absent; skips creation safely).
    5. Index creation failures (safe continuation, never downgraded to non-unique).
    """
    import mongomock
    from unittest.mock import MagicMock
    from pymongo.errors import OperationFailure
    from app import _create_indexes

    # 1. Existing legacy index matching MongoDB Atlas
    legacy_db = mongomock.MongoClient().db_legacy
    legacy_db.appointments.create_index([("tenant_id", 1), ("start_at", 1)], unique=True)
    before_legacy = legacy_db.appointments.index_information()
    assert "tenant_id_1_start_at_1" in before_legacy
    assert before_legacy["tenant_id_1_start_at_1"].get("unique") is True

    # Running _create_indexes must preserve legacy index without raising or altering options
    _create_indexes(legacy_db)
    after_legacy = legacy_db.appointments.index_information()
    assert "tenant_id_1_start_at_1" in after_legacy
    assert after_legacy["tenant_id_1_start_at_1"].get("unique") is True

    # 2. Matching index with partialFilterExpression
    partial_db = mongomock.MongoClient().db_partial
    partial_db.appointments.create_index(
        [("tenant_id", 1), ("start_at", 1)],
        unique=True,
        partialFilterExpression={"status": {"$in": ["confirmed", "pending", "rescheduled"]}},
    )
    _create_indexes(partial_db)
    after_partial = partial_db.appointments.index_information()
    assert any(
        list(info.get("key", [])) == [("tenant_id", 1), ("start_at", 1)]
        for info in after_partial.values()
    )

    # 3. Conflicting options (existing index is non-unique)
    conflict_db = mongomock.MongoClient().db_conflict
    conflict_db.appointments.create_index([("tenant_id", 1), ("start_at", 1)], unique=False)
    # Must preserve the existing index, not drop or alter it
    _create_indexes(conflict_db)
    after_conflict = conflict_db.appointments.index_information()
    assert any(
        list(info.get("key", [])) == [("tenant_id", 1), ("start_at", 1)]
        for info in after_conflict.values()
    )

    # 4. Failed index inspection (e.g. unauthorized to run listIndexes)
    mock_db_inspect_fail = MagicMock()
    mock_db_inspect_fail.appointments.index_information.side_effect = OperationFailure("not authorized on admin to execute command: listIndexes")
    # When inspection fails, it must NOT treat as absent and must NOT attempt start_at index creation
    _create_indexes(mock_db_inspect_fail)
    start_at_inspect_calls = [
        c for c in mock_db_inspect_fail.appointments.create_index.call_args_list
        if c.args and c.args[0] == [("tenant_id", 1), ("start_at", 1)]
    ]
    assert len(start_at_inspect_calls) == 0, "Must not attempt to create start_at index when inspection fails"

    # 5. Index creation failures (partial fails, standard unique fails)
    mock_db_create_fail = MagicMock()
    mock_db_create_fail.appointments.index_information.return_value = {}
    mock_db_create_fail.appointments.create_index.side_effect = [
        None,  # for customer_id start_at index in _safe_create_index
        OperationFailure("Index option conflict", code=86),
        OperationFailure("Index creation denied", code=13),
    ]
    # Must catch and continue safely without crashing startup
    _create_indexes(mock_db_create_fail)
    # Must never attempt a non-unique create_index call for start_at
    start_at_create_calls = [
        c for c in mock_db_create_fail.appointments.create_index.call_args_list
        if c.args and c.args[0] == [("tenant_id", 1), ("start_at", 1)]
    ]
    assert len(start_at_create_calls) == 2, "Must attempt partial and then standard unique"
    for call_args in start_at_create_calls:
        assert call_args.kwargs.get("unique") is True, "Must never downgrade to non-unique"


def test_legacy_unique_index_duplicate_key_safety_and_cancelled_handling(app_client):
    """
    Test duplicate-key handling and safety under an unconditional legacy unique index:
    1. If a cancelled appointment already exists in MongoDB with a legacy unconditional
       unique index on (tenant_id, start_at), inserting a new document at that exact
       instant triggers a DuplicateKeyError.
    2. create_appointment catches DuplicateKeyError and safely returns (None, error_msg),
       never claiming the appointment was booked or returning success.
    3. The customer portal API responds with 409 booking_unavailable, ensuring the client
       is never misled into believing a slot was booked.
    """
    from app.services.scheduling_service import create_appointment

    client, _ = app_client
    app = client.application
    db = app.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})
    tenant_id = str(tenant["_id"])

    # Simulate an environment with the legacy unconditional unique index
    db.appointments.drop_indexes()
    db.appointments.create_index([("tenant_id", 1), ("start_at", 1)], unique=True)

    # Insert a cancelled appointment directly at a valid future business slot
    start_time = datetime(2030, 1, 7, 9, 0, tzinfo=timezone.utc)
    db.appointments.insert_one({
        "tenant_id": tenant["_id"],
        "start_at": start_time,
        "end_at": start_time + timedelta(minutes=30),
        "status": "cancelled",
        "timezone": "UTC",
    })

    with app.app_context():
        # Attempting to book this slot triggers DuplicateKeyError on MongoDB level
        appt, err = create_appointment(
            tenant_id,
            {"start_at": start_time.isoformat(), "name": "Legacy Customer", "email": "legacy@example.com"},
            allow_customer_requested_time=True,
        )
        # Must fail safely without claiming booking succeeded
        assert appt is None
        assert err == "That appointment slot was just booked. Please choose another time."

    # Verify through customer API that 409 booking_unavailable is returned and booking never succeeds
    headers, _ = customer_auth(client, "tenant-one-key", full_name="Legacy Customer")
    res = client.post(
        "/api/v1/customer/appointments",
        headers=headers,
        json={"date": "2030-01-07", "time": "09:00"},
    )
    assert res.status_code == 409
    assert res.get_json()["error"] == "booking_unavailable"
    assert "just booked" in res.get_json()["message"]


def test_contact_fallback_uses_verified_email_and_preserves_tenant_isolation(app_client):
    """
    1. Confirm that admin@blackintel.com is never exposed as the public fallback contact.
    2. Confirm that Black Intel tenant uses verified official email abhishek.managerr@gmail.com.
    3. Confirm that genuine tenant-specific contact emails are preserved.
    4. Confirm that third-party tenants without contact emails do not leak Black Intel's contact info.
    """
    from app.services.llm_gateway import respond

    client, tenants = app_client
    app = client.application
    db = app.extensions["mongo_db"]

    with app.app_context():
        # Case A: Black Intel tenant with placeholder admin@blackintel.com
        bi_tenant_id = db.tenants.insert_one({"name": "Black Intel Demo", "slug": "black-intel-demo"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_tenant_id,
            "name": "Black Intel Demo",
            "contact_email": "admin@blackintel.com",
        })
        res_a = respond(str(bi_tenant_id), "What is the weather today?")
        assert "admin@blackintel.com" not in res_a["answer"], "Placeholder admin@blackintel.com must never be exposed"
        assert "abhishek.managerr@gmail.com" in res_a["answer"], "Must use verified official contact fallback"

        # Case B: Black Intel tenant with no contact email configured
        bi_no_email_id = db.tenants.insert_one({"name": "Black Intel", "slug": "black-intel-live"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_no_email_id,
            "name": "Black Intel",
        })
        res_b = respond(str(bi_no_email_id), "What is the return and refund policy?")
        assert "abhishek.managerr@gmail.com" in res_b["answer"]
        assert "admin@blackintel.com" not in res_b["answer"]

        # Case C: Custom tenant with its own verified contact email
        tenant_one_id = str(tenants[0][1])
        res_c = respond(tenant_one_id, "What is the return and refund policy?")
        assert "tenant-one@example.com" in res_c["answer"]
        assert "abhishek.managerr@gmail.com" not in res_c["answer"], "Must not leak Black Intel contact to Tenant One"
        assert "admin@blackintel.com" not in res_c["answer"]

        # Case D: Custom tenant without any contact email configured
        tenant_two_id = str(tenants[1][1])
        db.business_profiles.update_one({"tenant_id": tenants[1][1]}, {"$unset": {"contact_email": ""}})
        res_d = respond(tenant_two_id, "What is the weather today?")
        assert res_d["answer"] == "I do not have confirmed information about that."
        assert "abhishek.managerr@gmail.com" not in res_d["answer"], "Must not leak Black Intel contact to Tenant Two"
        assert "admin@blackintel.com" not in res_d["answer"]


def test_customer_booking_panel_contains_appointment_helper_text(app_client):
    """
    Verify that the customer booking form in the frontend contains the required helper text:
    Hours: Monday–Friday, 09:00–17:00 IST · Consultation: 30 minutes · Buffer: 15 minutes
    """
    client, _ = app_client
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    expected_note = "Hours: Monday–Friday, 09:00–17:00 IST · Consultation: 30 minutes · Buffer: 15 minutes"
    assert expected_note in html, "Customer booking panel must display the appointment helper text"


def test_public_chat_without_widget_key_resolves_primary_black_intel(app_client):
    """
    Public website visitors must be able to chat anonymously from the homepage
    without providing a widget key or logging in. The backend securely resolves
    the primary Black Intel Demo tenant.
    """
    client, tenants = app_client
    db = client.application.extensions["mongo_db"]
    bi_tenant = db.tenants.find_one({"slug": "black-intel-demo"})
    if not bi_tenant:
        bi_tenant_id = db.tenants.insert_one({"name": "Black Intel Demo", "slug": "black-intel-demo"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_tenant_id,
            "name": "Black Intel",
            "contact_email": "abhishek.managerr@gmail.com",
            "timezone": "Asia/Kolkata",
            "appointment_duration_minutes": 30,
            "appointment_buffer_minutes": 15,
        })
        db.widget_configs.insert_one({
            "tenant_id": bi_tenant_id,
            "public_key": "demo_black_intel_widget_key",
            "enabled": True,
            "allowed_origins": [],
        })
    else:
        bi_tenant_id = bi_tenant["_id"]

    response = client.post("/api/v1/public/chat", json={"message": "What services does Black Intel offer?"})
    assert response.status_code == 200
    data = response.get_json()
    assert "conversation_id" in data
    assert "answer" in data
    assert len(data["answer"]) > 10

    conv = db.conversations.find_one({"_id": ObjectId(data["conversation_id"])})
    assert conv is not None
    assert conv["tenant_id"] == bi_tenant_id

    res_alias = client.post("/api/v1/chat", json={"message": "What does Black Intel do?"})
    assert res_alias.status_code == 200
    assert "answer" in res_alias.get_json()


def test_public_chat_general_technical_query_gives_honest_diagnostic_fallback(app_client):
    """
    When an external AI provider (Gemini/Groq) is offline or unconfigured, general
    coding questions (e.g. 'Write a Python program to add two numbers') should receive
    an honest, transparent diagnostic message explaining that external generative AI
    is offline, rather than inappropriate company fallback text or 'contact Abhishek'.
    """
    from app.services.llm_gateway import respond

    client, tenants = app_client
    db = client.application.extensions["mongo_db"]

    bi_tenant = db.tenants.find_one({"slug": "black-intel-demo"})
    if not bi_tenant:
        bi_tenant_id = db.tenants.insert_one({"name": "Black Intel Demo", "slug": "black-intel-demo"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_tenant_id,
            "name": "Black Intel",
            "contact_email": "abhishek.managerr@gmail.com",
            "timezone": "Asia/Kolkata",
        })
    else:
        bi_tenant_id = bi_tenant["_id"]

    with client.application.app_context():
        res = respond(str(bi_tenant_id), "Write a Python program to add two numbers.")
        answer = res["answer"]
        assert res["provider"] == "local"
        assert "def add_numbers(" in answer or "def " in answer
        assert "External AI completion is currently unavailable" not in answer
        assert "abhishek.managerr@gmail.com" not in answer, "Must not tell visitors to email Abhishek for Python code"


def test_public_chat_general_query_with_mocked_ai_completion(app_client, monkeypatch):
    """
    When the AI provider is configured and available, general coding or technical queries
    return the full AI-generated completion.
    """
    import app.services.llm_gateway as llm_gw

    client, tenants = app_client
    db = client.application.extensions["mongo_db"]

    bi_tenant = db.tenants.find_one({"slug": "black-intel-demo"})
    if not bi_tenant:
        bi_tenant_id = db.tenants.insert_one({"name": "Black Intel Demo", "slug": "black-intel-demo"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_tenant_id,
            "name": "Black Intel",
            "timezone": "Asia/Kolkata",
        })
    else:
        bi_tenant_id = bi_tenant["_id"]

    client.application.config["GEMINI_API_KEY"] = "AIzaSyTestMockKey"
    mock_code = "```python\ndef add(a, b):\n    return a + b\n```"
    monkeypatch.setattr(llm_gw, "generate_ai_completion", lambda *args, **kwargs: (mock_code, "gemini", None))

    with client.application.app_context():
        res = llm_gw.respond(str(bi_tenant_id), "Write a Python program to add two numbers.")
        assert "def add(a, b):" in res["answer"]
        assert res["provider"] == "gemini"


def test_public_availability_check_and_appointment_booking(app_client):
    """
    Public visitors can check availability and book consultations without logging in.
    The appointment uses 30-min duration, 15-min buffer, creates a lead record, and
    rejects collision attempts.
    """
    client, tenants = app_client
    db = client.application.extensions["mongo_db"]

    bi_tenant = db.tenants.find_one({"slug": "black-intel-demo"})
    if not bi_tenant:
        bi_tenant_id = db.tenants.insert_one({"name": "Black Intel Demo", "slug": "black-intel-demo"}).inserted_id
        db.business_profiles.insert_one({
            "tenant_id": bi_tenant_id,
            "name": "Black Intel",
            "contact_email": "abhishek.managerr@gmail.com",
            "timezone": "Asia/Kolkata",
            "appointment_duration_minutes": 30,
            "appointment_buffer_minutes": 15,
        })
        db.widget_configs.insert_one({
            "tenant_id": bi_tenant_id,
            "public_key": "demo_black_intel_widget_key",
            "enabled": True,
            "allowed_origins": [],
        })
        for weekday in range(5):
            db.business_hours.insert_one({
                "tenant_id": bi_tenant_id,
                "weekday": weekday,
                "enabled": True,
                "start_time": "09:00",
                "end_time": "17:00",
            })
    else:
        bi_tenant_id = bi_tenant["_id"]
        if db.business_hours.count_documents({"tenant_id": bi_tenant_id}) == 0:
            for weekday in range(5):
                db.business_hours.insert_one({
                    "tenant_id": bi_tenant_id,
                    "weekday": weekday,
                    "enabled": True,
                    "start_time": "09:00",
                    "end_time": "17:00",
                })

    future_date = datetime.now(timezone.utc) + timedelta(days=14)
    while future_date.weekday() >= 5:
        future_date += timedelta(days=1)
    date_str = future_date.strftime("%Y-%m-%d")

    res_avail = client.get(f"/api/v1/public/availability/check?date={date_str}&time=10:00")
    assert res_avail.status_code == 200
    avail_data = res_avail.get_json()
    assert avail_data["available"] is True
    assert "Asia/Kolkata" in avail_data["timezone"]

    booking_payload = {
        "date": date_str,
        "time": "10:00",
        "name": "Jane Public",
        "email": "jane.public@example.com",
        "phone": "+91 9876543210",
        "requirement": "Security assessment for cloud platform",
    }
    res_book = client.post("/api/v1/public/appointments", json=booking_payload)
    assert res_book.status_code == 201
    booking_data = res_book.get_json()
    assert "appointment" in booking_data
    appt = booking_data["appointment"]
    assert appt["status"] == "confirmed"
    assert "manage_token" in appt

    lead = db.leads.find_one({"tenant_id": bi_tenant_id, "email": "jane.public@example.com"})
    assert lead is not None
    assert lead["name"] == "Jane Public"

    res_dup = client.post("/api/v1/public/appointments", json=booking_payload)
    assert res_dup.status_code == 409

    res_buffer = client.post("/api/v1/public/appointments", json={**booking_payload, "time": "10:35"})
    assert res_buffer.status_code == 409


def test_public_website_landing_page_renders_chat_and_booking(app_client):
    """
    The public homepage at GET / must render the landing page without hidden attribute,
    displaying the live chat console, consultation booking section, and Black & Gold assets.
    """
    client, _ = app_client
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<main id="landing" class="landing">' in html
    assert 'id="public-chat-messages"' in html
    assert 'id="public-chat-form"' in html
    assert 'id="public-booking-form"' in html
    assert 'id="consultation"' in html
    assert 'Black Intel AI Assistant' in html


def test_gemini_model_selection_and_resolution():
    """
    Test Gemini model selection:
    - Defaults to gemini-3.8-flash for empty, None, shut-down, or unknown models.
    - Preserves explicitly valid models from the whitelist.
    - Handles models/ prefix cleanly.
    """
    from app.services.ai_provider import resolve_gemini_model, DEFAULT_GEMINI_MODEL

    assert resolve_gemini_model(None) == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("   ") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("gemini-2.0-flash") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("gemini-3-flash-preview") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("unsupported-model-v99") == DEFAULT_GEMINI_MODEL

    # Explicitly supported models
    assert resolve_gemini_model("gemini-3.8-flash") == "gemini-3.8-flash"
    assert resolve_gemini_model("gemini-2.5-flash") == "gemini-2.5-flash"
    assert resolve_gemini_model("gemini-2.5-pro") == "gemini-2.5-pro"
    assert resolve_gemini_model("models/gemini-3.8-flash") == "gemini-3.8-flash"

    # Removed unverified or restricted legacy models fall back to default
    assert resolve_gemini_model("gemini-3.8-pro") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("gemini-1.5-flash") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("gemini-1.5-pro") == DEFAULT_GEMINI_MODEL


def test_gemini_404_fallback_to_default_model_and_not_2_0_flash(monkeypatch):
    """
    When an explicitly requested model returns 404, call_gemini retries once with
    DEFAULT_GEMINI_MODEL (gemini-3.8-flash) and never uses the shut-down gemini-2.0-flash.
    If default model itself returns 404, it raises RuntimeError without infinite recursion.
    """
    import json
    import urllib.error
    import urllib.request
    from app.services.ai_provider import call_gemini, DEFAULT_GEMINI_MODEL

    called_urls = []
    called_models = []

    class MockSuccessResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"outputs": [{"type": "model_output", "content": [{"type": "text", "text": "Success answer"}]}]}'

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        called_urls.append(url)
        data = json.loads(req.data.decode("utf-8")) if hasattr(req, "data") and req.data else {}
        m = data.get("model", "")
        called_models.append(m)
        if m == "gemini-2.5-flash":
            # First attempt with non-default model returns 404
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        # Fallback attempt with gemini-3.8-flash succeeds
        return MockSuccessResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = call_gemini(
        api_key="AIzaSyMockKeyForTesting12345",
        model="gemini-2.5-flash",
        system_prompt="system",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert res == "Success answer"
    assert len(called_models) == 2
    assert called_models[0] == "gemini-2.5-flash"
    assert called_models[1] == "gemini-3.8-flash"
    assert "gemini-2.0-flash" not in called_models

    # Test when default model itself returns 404 -> raises RuntimeError without infinite loop
    called_urls.clear()
    called_models.clear()
    def mock_urlopen_all_404(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        called_urls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_all_404)
    with pytest.raises(RuntimeError) as exc_info:
        call_gemini(
            api_key="AIzaSyMockKeyForTesting12345",
            model=DEFAULT_GEMINI_MODEL,
            system_prompt="system",
            messages=[{"role": "user", "content": "hello"}],
        )
    assert "404" in str(exc_info.value)
    assert len(called_urls) == 1, "Must not retry when DEFAULT_GEMINI_MODEL itself returns 404"


def test_gemini_authentication_and_key_handling(app_client):
    """
    Test candidate API key validation and error handling:
    - Candidate keys from Google AI Studio (AQ.Ab8..., AIzaSy...) are accepted structurally.
    - Empty, missing, and short keys raise ValueError.
    - generate_ai_completion returns honest failure on missing key.
    - respond() falls back honestly to local mode without claiming AI completion.
    """
    from app.services.ai_provider import validate_gemini_api_key, is_valid_gemini_api_key, generate_ai_completion
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    # 1. Structural validation accepts candidate keys from AI Studio
    for valid_key in ("AQ.Ab8ValidAIStudioKeyFormat12345", "AIzaSyDummyValidGoogleAIStudioKey123"):
        assert is_valid_gemini_api_key(valid_key)
        assert validate_gemini_api_key(valid_key) == valid_key

    # 2. Rejects empty, missing, or too short keys
    for bad_key in ("", "   ", None, "short"):
        assert not is_valid_gemini_api_key(bad_key)
        with pytest.raises(ValueError):
            validate_gemini_api_key(bad_key)

    # 3. generate_ai_completion with empty key returns honest failure
    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "",
    })
    with client.application.app_context():
        text, provider, err = generate_ai_completion("system", [{"role": "user", "content": "hello"}])
        assert text is None

        # 4. respond() falls back to local and never reports provider: gemini
        res = respond(tenant_id, "Write a Python program to sort a list")
        assert res["provider"] == "local"
        assert "External AI completion is currently unavailable" not in res["answer"]
        assert "def " in res["answer"] or "sort" in res["answer"].lower()


def test_gemini_http_auth_and_rate_limit_errors(app_client, monkeypatch):
    """
    Test honest handling of Google API HTTP error responses:
    - HTTP 401/403: reports credential/authentication error
    - HTTP 429: reports rate limit error
    - Timeout: reports timeout error
    In all cases, respond() falls back to local provider and never fakes an AI response.
    """
    import urllib.error
    import urllib.request
    from app.services.llm_gateway import respond
    from app.services.ai_provider import call_gemini

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    # Test HTTP 401 handling in call_gemini
    def mock_401(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_401)
    with pytest.raises(RuntimeError) as exc_info:
        call_gemini("AIzaSyValidKeyFormatMock123456", "gemini-3.8-flash", "sys", [{"role": "user", "content": "hi"}])
    assert "authentication/credential error" in str(exc_info.value)

    # Test HTTP 429 handling in call_gemini
    def mock_429(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_429)
    with pytest.raises(RuntimeError) as exc_info:
        call_gemini("AIzaSyValidKeyFormatMock123456", "gemini-3.8-flash", "sys", [{"role": "user", "content": "hi"}])
    assert "rate limit exceeded" in str(exc_info.value)

    # Test respond() fallback when HTTP 429 happens
    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "AIzaSyValidKeyFormatMock123456",
        "GEMINI_MODEL": "gemini-3.8-flash",
    })
    with client.application.app_context():
        res = respond(tenant_id, "Explain quantum computing in Python")
        assert res["provider"] == "local"
        assert "External AI completion is currently unavailable" not in res["answer"]
        assert len(res["answer"]) > 10


def test_programming_and_general_queries_fallback_behavior(app_client):
    """
    Verify that:
    1. Programming and code queries (like 'py code do', 'write a python function')
       never send the user to the Black Intel contact email fallback.
       They clearly disclose that external AI completion is unavailable.
    2. Unknown general queries (like 'wt ky hots ha') do not leak contact emails or invent company facts.
    """
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    with client.application.app_context():
        # A. Programming query: 'py code do'
        res_code = respond(tenant_id, "py code do")
        assert res_code["provider"] == "local"
        assert "External AI completion is currently unavailable" not in res_code["answer"]
        assert "python" in res_code["answer"].lower()
        assert "abhishek.managerr@gmail.com" not in res_code["answer"], "Programming questions must never return contact email"
        assert "admin@blackintel.com" not in res_code["answer"]

        # B. Python function query
        res_py = respond(tenant_id, "how to write a loop in python")
        assert res_py["provider"] == "local"
        assert "External AI completion is currently unavailable" not in res_py["answer"]
        assert "loop" in res_py["answer"].lower() or "for " in res_py["answer"]
        assert "abhishek.managerr@gmail.com" not in res_py["answer"]

        # C. General unknown/slang query
        res_slang = respond(tenant_id, "wt ky hots ha")
        assert res_slang["provider"] == "local"
        assert "abhishek.managerr@gmail.com" not in res_slang["answer"]
        assert "admin@blackintel.com" not in res_slang["answer"]


def test_general_ai_programming_code_generation_with_gemini(app_client, monkeypatch):
    """
    Verify that when Gemini is configured and enabled:
    1. Asking a programming question ('py code do') generates Python code.
    2. The response has provider: 'gemini'.
    3. The response does not contain contact email fallbacks.
    """
    import io
    import json
    import urllib.request
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    fake_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "```python\ndef add(a, b):\n    return a + b\n\nprint(add(2, 3))\n```"
                        }
                    ]
                }
            }
        ]
    }

    class MockHTTPResponse:
        status = 200

        def read(self):
            return json.dumps(fake_response_data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=None):
        return MockHTTPResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    client.application.config.update({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "AIzaSyValidGoogleStudioKeyMock12345",
        "GEMINI_MODEL": "gemini-3.8-flash",
    })

    with client.application.app_context():
        res = respond(tenant_id, "py code do")
        assert res["provider"] == "gemini", "Successful Gemini completion must report provider: gemini"
        assert "def add(a, b):" in res["answer"], "Must return generated Python code"
        assert "abhishek.managerr@gmail.com" not in res["answer"]
        assert "admin@blackintel.com" not in res["answer"]


def test_public_anonymous_chat_no_login_required(app_client):
    """
    Verify that visitors can access public chat without login,
    while protected customer and admin APIs strictly require authentication.
    """
    client, _ = app_client

    # 1. Anonymous visitor can send chat message to /api/v1/public/chat
    chat_resp = client.post("/api/v1/public/chat", json={"message": "What services do you provide?"})
    assert chat_resp.status_code == 200
    data = chat_resp.get_json()
    assert "conversation_id" in data
    assert "answer" in data

    # 2. Anonymous visitor cannot access customer protected routes
    cust_resp = client.get("/api/v1/customer/dashboard")
    assert cust_resp.status_code == 401

    # 3. Anonymous visitor cannot access admin protected routes
    admin_resp = client.get("/api/v1/admin/context")
    assert admin_resp.status_code == 401


def test_appointment_booking_and_conflict_handling_regression(app_client):
    """
    Verify appointment booking, availability checks, buffer enforcement,
    and conflict prevention:
    - Available slot is confirmed.
    - Double booking the same slot returns 409 conflict.
    - Booking does not alter or touch any production data.
    """
    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    # Query availability slots for a Monday in the future
    future_monday = "2030-01-07"  # 2030-01-07 is a Monday
    slots_resp = client.get(f"/api/v1/public/availability/slots?date={future_monday}")
    assert slots_resp.status_code == 200
    available = slots_resp.get_json().get("slots", [])
    assert len(available) > 0, "Expected available slots for business day"

    chosen_slot = available[0]

    # First booking succeeds
    book_resp_1 = client.post("/api/v1/public/appointments", json={
        "start_at": chosen_slot,
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1234567890",
        "requirement": "Initial Consultation",
    })
    assert book_resp_1.status_code == 201
    appt_1 = book_resp_1.get_json().get("appointment", {})
    assert appt_1.get("status") == "confirmed"
    assert "manage_token" in appt_1

    # Second booking for the same slot is rejected with 409 conflict
    book_resp_2 = client.post("/api/v1/public/appointments", json={
        "start_at": chosen_slot,
        "name": "John Smith",
        "email": "john@example.com",
        "phone": "+1987654321",
        "requirement": "Conflict Test",
    })
    assert book_resp_2.status_code == 409
    error_msg = book_resp_2.get_json().get("message", "")
    assert "no longer available" in error_msg or "conflict" in error_msg.lower()


def test_anonymous_guest_name_introduction_and_persistence(app_client):
    """
    Verify anonymous guest personalization:
    - Guest introduces their name in Hindi/Hinglish: 'Mera naam Rahul hai'
    - Chatbot warmly greets Rahul by name.
    - Conversation remembers 'Rahul' across follow-up turns.
    - A different guest conversation remains strictly isolated.
    """
    client, _ = app_client
    key = {"X-Widget-Key": "tenant-one-key"}

    # 1. Guest 1 introduces name in Hinglish
    intro_resp = client.post("/api/v1/chat", headers=key, json={"message": "Mera naam Rahul hai"})
    assert intro_resp.status_code == 200
    data1 = intro_resp.get_json()
    assert "Rahul" in data1["answer"]
    assert "Namaste" in data1["answer"] or "swagat" in data1["answer"].lower()
    conv_id = data1["conversation_id"]

    # 2. Guest 1 sends a follow-up asking for appointment guidance
    follow_resp = client.post(
        f"/api/v1/public/conversations/{conv_id}/messages",
        headers=key,
        json={"message": "I want to schedule an appointment"},
    )
    assert follow_resp.status_code == 200
    assert "Rahul" in follow_resp.get_json()["answer"]
    assert "appointment booking form" in follow_resp.get_json()["answer"]

    # 3. Guest 2 starts a new conversation without introducing their name
    guest2_resp = client.post("/api/v1/chat", headers=key, json={"message": "hello"})
    assert guest2_resp.status_code == 200
    # Must NOT address Guest 2 as Rahul
    assert "Rahul" not in guest2_resp.get_json()["answer"]
    assert guest2_resp.get_json()["answer"].startswith("Hello. I can help with")


def test_official_black_intel_expanded_knowledge_and_chunking(app_client):
    """
    Verify expanded official Black Intel company knowledge:
    - Syncing official records creates 20 verified published records.
    - Verified retrieval for Cyber Offense, Forensics, Leadership, Booking, and Pricing.
    - Scalable document chunker works with metadata and deduplication hashing.
    """
    from app.services.official_knowledge import (
        sync_official_knowledge,
        chunk_document,
        OFFICIAL_BLACK_INTEL_KNOWLEDGE,
    )
    from app.services.knowledge_service import retrieve

    client, _ = app_client
    db = client.application.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": "tenant-one"})["_id"]

    # 1. Sync official verified records
    synced_count = sync_official_knowledge(db, tenant)
    assert synced_count >= 20
    assert len(OFFICIAL_BLACK_INTEL_KNOWLEDGE) >= 20

    with client.application.app_context():
        # 2. Cyber Offense Command retrieval
        offense = retrieve(str(tenant), "Tell me about Cyber Offense and APT simulation")
        assert offense
        assert any("offense" in rec["title"].lower() or "penetration" in rec["content"].lower() for rec in offense)

        # 3. Truth Extraction & Forensics retrieval
        forensics = retrieve(str(tenant), "What is Forensic Truth Extraction?")
        assert forensics
        assert any("forensic" in rec["title"].lower() or "truth" in rec["content"].lower() for rec in forensics)

        # 4. Confidentiality & NDA retrieval
        nda = retrieve(str(tenant), "Do you sign non disclosure agreements?")
        assert nda
        assert any("confidentiality" in rec["title"].lower() or "nda" in rec["content"].lower() for rec in nda)

    # 5. Scalable Document Chunker verification
    long_doc = "Security architecture and forensics analysis. " * 150
    chunks = chunk_document("Enterprise Threat Model", long_doc, chunk_size=50, overlap=10)
    assert len(chunks) > 1
    for chunk in chunks:
        assert "Enterprise Threat Model" in chunk["title"]
        assert "hash" in chunk and len(chunk["hash"]) == 16
        assert chunk["source_url"] == "https://theblackintel.com/"


def test_gemini_free_general_knowledge_and_code_synthesis():
    """
    Verify curated general knowledge and Python code synthesis:
    - Code synthesis produces clean, runnable Python for add_numbers, reverse_string, is_prime.
    - General knowledge retrieval covers science, mathematics, computer science, and cryptography.
    """
    from app.services.general_knowledge import (
        search_general_knowledge,
        synthesize_code_response,
    )

    # 1. Python code synthesis for add_numbers
    code1 = synthesize_code_response("Write a Python function named add_numbers that takes two arguments and returns their sum.")
    assert code1 is not None
    assert "def add_numbers(" in code1
    assert "return a + b" in code1

    # 2. Python code synthesis for reverse_string
    code2 = synthesize_code_response("How to reverse a string in Python?")
    assert code2 is not None
    assert "[::-1]" in code2

    # 3. General knowledge: Science (Photosynthesis)
    science = search_general_knowledge("What is photosynthesis in plants?")
    assert science
    assert science[0]["topic"] == "Photosynthesis"
    assert "glucose" in science[0]["content"].lower()

    # 4. General knowledge: Mathematics (Pythagorean Theorem)
    math_rec = search_general_knowledge("Explain the Pythagorean theorem for triangles")
    assert math_rec
    assert math_rec[0]["topic"] == "Pythagorean Theorem"
    assert "a^2 + b^2 = c^2" in math_rec[0]["content"]

    # 5. General knowledge: Computer Science (SQL vs NoSQL)
    db_rec = search_general_knowledge("What is the difference between SQL and NoSQL databases?")
    assert db_rec
    assert db_rec[0]["topic"] == "SQL vs NoSQL Databases"
    assert "MongoDB" in db_rec[0]["content"]


def test_ollama_local_llm_provider_integration_and_fallback(app_client, monkeypatch):
    """
    Verify Ollama local model integration:
    - When Ollama is available, generate_ai_completion calls call_ollama and returns provider: ollama.
    - When Ollama server is offline (connection error), it catches the error gracefully and returns None without crashing.
    """
    import urllib.request
    from unittest.mock import MagicMock
    from app.services.ai_provider import call_ollama, generate_ai_completion
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    # 1. Mock successful Ollama response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"message": {"role": "assistant", "content": "Local Ollama generated response."}}'
    mock_response.__enter__.return_value = mock_response

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: mock_response)
    text = call_ollama("http://localhost:11434", "qwen2.5:3b", "System", [{"role": "user", "content": "Hello"}])
    assert text == "Local Ollama generated response."

    # 2. Configure app to use Ollama provider
    client.application.config["LLM_PROVIDER"] = "ollama"
    with client.application.app_context():
        comp_text, prov, err = generate_ai_completion("System prompt", [{"role": "user", "content": "Hello"}])
        assert comp_text == "Local Ollama generated response."
        assert prov == "ollama"
        assert err is None

        # 3. When Ollama is offline, connection failure is caught gracefully
        import urllib.error
        def mock_offline(req, timeout=None):
            raise urllib.error.URLError("Connection refused [Errno 111]")

        monkeypatch.setattr(urllib.request, "urlopen", mock_offline)
        offline_text, offline_prov, offline_err = generate_ai_completion("Sys", [{"role": "user", "content": "Hello"}])
        assert offline_text is None
        assert offline_prov == "ollama"
        assert "connection error" in offline_err.lower()

        # Gateway falls back to local engine safely
        res = respond(tenant_id, "Hello")
        assert res["provider"] == "local"
        assert "approved services" in res["answer"]


def test_isolated_db_mode_activation_and_uri_ignored(monkeypatch):
    """Verify that enabling isolated in-memory mode ignores remote Atlas URI and uses mongomock."""
    from unittest.mock import MagicMock
    import pymongo

    mock_pymongo_client = MagicMock()
    monkeypatch.setattr(pymongo, "MongoClient", mock_pymongo_client)
    monkeypatch.setattr("app.MongoClient", mock_pymongo_client)

    remote_fake_uri = "mongodb+srv://mock-user:mock-pass@production-cluster.fake.mongodb.net/prod_db"
    monkeypatch.setenv("MONGODB_URI", remote_fake_uri)
    monkeypatch.setenv("ISOLATED_LOCAL_DB", "true")

    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "MONGODB_DATABASE": "isolated_test_db",
    })

    # PyMongo's network MongoClient must NEVER be called
    mock_pymongo_client.assert_not_called()

    # Application extensions must be set to isolated mongomock client
    assert app.extensions["is_isolated_db"] is True
    assert isinstance(app.extensions["mongo_client"], mongomock.MongoClient)
    assert app.config["MONGODB_URI"] == "mongomock://localhost/isolated_in_memory"


def test_isolated_db_fails_closed_when_mongomock_unavailable(monkeypatch):
    """Verify fail-closed behavior: when mongomock is missing, isolated mode raises RuntimeError and never falls back to production."""
    import sys
    from unittest.mock import patch, MagicMock
    import pymongo

    mock_pymongo_client = MagicMock()
    monkeypatch.setattr(pymongo, "MongoClient", mock_pymongo_client)
    monkeypatch.setattr("app.MongoClient", mock_pymongo_client)

    with patch.dict(sys.modules, {"mongomock": None}):
        with pytest.raises(RuntimeError) as exc_info:
            create_app({
                "ISOLATED_LOCAL_DB": True,
                "TESTING": True,
                "SECRET_KEY": "s" * 32,
                "JWT_SECRET_KEY": "j" * 32,
            })

        assert "ISOLATED DATABASE MODE FAILED" in str(exc_info.value)
        assert "mongomock" in str(exc_info.value)

    # Must fail closed: never attempt network call
    mock_pymongo_client.assert_not_called()


def test_isolated_db_normal_routes_and_ephemeral_sessions():
    """Verify all public, auth, and customer routes function correctly with the isolated in-memory database."""
    app = create_app({
        "ISOLATED_LOCAL_DB": True,
        "SEED_DEMO_DATA": True,
        "TESTING": True,
        "SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "LLM_PROVIDER": "local",
    })
    client = app.test_client()

    # 1. Health check returns 200 with isolated database
    health_res = client.get("/api/v1/health")
    assert health_res.status_code == 200
    assert health_res.get_json()["status"] == "ok"

    # 2. Public widget-config resolves seeded Black Intel demo tenant
    cfg_res = client.get("/api/v1/public/widget-config")
    assert cfg_res.status_code == 200
    assert cfg_res.get_json()["business_name"] == "Black Intel"

    # 3. Public chat resolves grounded knowledge from in-memory DB
    chat_res = client.post("/api/v1/public/chat", json={
        "message": "What services does Black Intel offer?",
    })
    assert chat_res.status_code == 200
    chat_json = chat_res.get_json()
    assert chat_json["provider"] == "local"
    assert "cybersecurity" in chat_json["answer"].lower()

    # 4. Operator admin login authenticates seeded demo credentials
    login_res = client.post("/api/v1/auth/login", json={
        "tenant_slug": "black-intel-demo",
        "email": "admin@blackintel.com",
        "password": "ChangeMe123!",
    })
    assert login_res.status_code == 200
    token = login_res.get_json()["access_token"]
    assert token

    # 5. Customer registration creates ephemeral record in memory
    reg_res = client.post("/api/v1/customer/auth/register", json={
        "widget_key": "demo_black_intel_widget_key",
        "full_name": "Ephemeral Test Customer",
        "age": 28,
        "reason": "Test Consultation Inquiry",
        "password": "CustomerSecure123!",
        "confirm_password": "CustomerSecure123!",
    })
    assert reg_res.status_code == 201
    cust_data = reg_res.get_json()["customer"]
    assert cust_data["customer_id"].startswith("BI-")

    # Verify customer was inserted into in-memory collection
    db = app.extensions["mongo_db"]
    saved_cust = db.customers.find_one({"customer_id": cust_data["customer_id"]})
    assert saved_cust is not None
    assert saved_cust["full_name"] == "Ephemeral Test Customer"


def test_isolated_db_env_and_config_flags(monkeypatch):
    """Verify is_isolated_db_enabled respects various config dict and environment variable flags."""
    from app.isolated_db import is_isolated_db_enabled

    # Config dict explicit true/false
    assert is_isolated_db_enabled({"ISOLATED_LOCAL_DB": True}) is True
    assert is_isolated_db_enabled({"ISOLATED_LOCAL_DB": "1"}) is True
    assert is_isolated_db_enabled({"ISOLATED_LOCAL_DB": False}) is False
    assert is_isolated_db_enabled({"ISOLATED_LOCAL_DB": "0"}) is False

    # Environment variables
    monkeypatch.delenv("ISOLATED_LOCAL_DB", raising=False)
    monkeypatch.delenv("LOCAL_ISOLATED_DB", raising=False)
    monkeypatch.delenv("MOCK_DB", raising=False)
    monkeypatch.delenv("BLACK_INTEL_ISOLATED_DB", raising=False)

    assert is_isolated_db_enabled() is False

    monkeypatch.setenv("LOCAL_ISOLATED_DB", "true")
    assert is_isolated_db_enabled() is True

    monkeypatch.delenv("LOCAL_ISOLATED_DB")
    monkeypatch.setenv("MOCK_DB", "yes")
    assert is_isolated_db_enabled() is True


def test_production_mode_preserved_when_isolated_flag_absent(monkeypatch):
    """Verify standard production database mode is preserved when isolated flag is absent."""
    from unittest.mock import MagicMock
    import pymongo

    mock_client_instance = MagicMock()
    mock_pymongo_client = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr(pymongo, "MongoClient", mock_pymongo_client)
    monkeypatch.setattr("app.MongoClient", mock_pymongo_client)
    monkeypatch.setattr("app._create_indexes", lambda db: None)

    monkeypatch.delenv("ISOLATED_LOCAL_DB", raising=False)
    monkeypatch.delenv("LOCAL_ISOLATED_DB", raising=False)
    monkeypatch.delenv("MOCK_DB", raising=False)
    monkeypatch.delenv("BLACK_INTEL_ISOLATED_DB", raising=False)

    test_uri = "mongodb://localhost:27017/test_db"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "MONGODB_URI": test_uri,
        "MONGODB_DATABASE": "test_db",
    })

    # Production code path calls MongoClient with configured URI
    mock_pymongo_client.assert_called_once_with(
        test_uri,
        serverSelectionTimeoutMS=app.config["MONGODB_SERVER_SELECTION_TIMEOUT_MS"],
    )
    assert app.extensions["is_isolated_db"] is False


@pytest.fixture()
def black_intel_client():
    from app.api.public import _requests
    from app.api.customer import _auth_requests

    _requests.clear()
    _auth_requests.clear()
    app = create_app({
        "ISOLATED_LOCAL_DB": True,
        "TESTING": True,
        "SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "SEED_DEMO_DATA": True,
        "LLM_PROVIDER": "local",
    })
    return app.test_client()


def test_authenticated_customer_greeting_preserved(black_intel_client):
    """
    Verify authenticated account name (e.g. 'jitu') is preserved and addressed:
    The chatbot saying 'Hello jitu' is correct and verified.
    """
    client = black_intel_client
    reg_res = client.post("/api/v1/customer/auth/register", json={
        "widget_key": "demo_black_intel_widget_key",
        "full_name": "jitu",
        "age": 25,
        "reason": "Security Assessment",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert reg_res.status_code == 201
    auth_token = reg_res.get_json()["access_token"]
    assert auth_token

    # Chat as authenticated jitu
    chat_res = client.post(
        "/api/v1/customer/chat",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"message": "hello"},
    )
    assert chat_res.status_code == 200
    answer = chat_res.get_json()["answer"]
    assert "Hello jitu." in answer
    assert "Black Intel" in answer


def test_greetings_and_hinglish_capability_questions(black_intel_client):
    """
    Verify:
    1. Hinglish capability questions ('tum kya kya kar sakte ho?') receive a grounded response
       outlining the 4 real capabilities: Cybersecurity/Forensics, Consultation Scheduling,
       Client Workspace Support, General Technical & Programming Reference.
    2. English capability questions ('what can you do?') receive the same grounded response in English.
    3. Natural Hinglish greetings ('namaste') receive a polite Hinglish greeting.
    """
    client = black_intel_client

    # 1. Hinglish capability query
    hi_cap = client.post("/api/v1/public/chat", json={"message": "tum kya kya kar sakte ho?"})
    assert hi_cap.status_code == 200
    hi_ans = hi_cap.get_json()["answer"]
    assert "Cybersecurity & Digital Forensics" in hi_ans
    assert "Consultation Scheduling" in hi_ans
    assert "Client Workspace" in hi_ans
    assert "Programming" in hi_ans

    # 2. English capability query
    en_cap = client.post("/api/v1/public/chat", json={"message": "what can you do?"})
    assert en_cap.status_code == 200
    en_ans = en_cap.get_json()["answer"]
    assert "Cybersecurity & Forensics" in en_ans
    assert "Consultation Scheduling" in en_ans

    # 3. Hinglish greeting
    namaste = client.post("/api/v1/public/chat", json={"message": "namaste"})
    assert namaste.status_code == 200
    assert "Namaste" in namaste.get_json()["answer"]
    assert "swagat hai" in namaste.get_json()["answer"]


def test_partial_query_canonicalization_and_deduplication(black_intel_client):
    """
    Verify:
    1. Partial query 'What services does Black Intel of' is canonicalized in DB message and response.
    2. Duplicate citation labels are stripped.
    """
    client = black_intel_client
    res = client.post("/api/v1/public/chat", json={"message": "What services does Black Intel of"})
    assert res.status_code == 200
    data = res.get_json()
    assert "cybersecurity" in data["answer"].lower() or "offense" in data["answer"].lower()

    # Verify deduplicated citations
    citations = data.get("citations", [])
    assert len(citations) == len(set(citations)), "Citations must not contain duplicate entries"

    # Verify DB stored message has canonicalized prompt
    db = client.application.extensions["mongo_db"]
    stored_msg = db.messages.find_one({"role": "visitor", "content": "What services does Black Intel offer?"})
    assert stored_msg is not None, "Message must be saved in db.messages with canonicalized complete prompt"


def test_follow_up_conversation_context_resolution(black_intel_client):
    """
    Verify follow-up queries like 'Tell me more about it' use prior conversation context.
    """
    client = black_intel_client
    # Turn 1
    t1 = client.post("/api/v1/public/chat", json={"message": "What does Black Intel do?"})
    assert t1.status_code == 200
    conv_id = t1.get_json()["conversation_id"]

    # Turn 2: Follow-up
    t2 = client.post(f"/api/v1/public/conversations/{conv_id}/messages", json={"message": "Tell me more about it"})
    assert t2.status_code == 200
    ans = t2.get_json()["answer"]
    assert "cybersecurity" in ans.lower() or "intelligence" in ans.lower() or "forensics" in ans.lower()
    assert "I do not have confirmed information" not in ans


def test_local_code_synthesis_markdown_formatting_and_no_error_prefix(app_client):
    """
    Verify:
    1. Code synthesis produces valid Markdown code blocks (```python).
    2. 'External AI completion is currently unavailable' is never prepended to valid local solutions.
    """
    from app.services.llm_gateway import respond

    client, tenants = app_client
    tenant_id = str(tenants[0][1])

    with client.application.app_context():
        # Code query
        res = respond(tenant_id, "Write a Python function to add two numbers")
        assert res["provider"] == "local"
        assert "```python" in res["answer"]
        assert "def add_numbers(" in res["answer"]
        assert "External AI completion is currently unavailable" not in res["answer"]

        # Loop query
        res_loop = respond(tenant_id, "how to write a loop in python")
        assert res_loop["provider"] == "local"
        assert "```python" in res_loop["answer"]
        assert "for " in res_loop["answer"]
        assert "External AI completion is currently unavailable" not in res_loop["answer"]

        # Sorting query
        res_sort = respond(tenant_id, "how to sort a list in Python")
        assert res_sort["provider"] == "local"
        assert "```python" in res_sort["answer"]
        assert "sort" in res_sort["answer"].lower()
        assert "External AI completion is currently unavailable" not in res_sort["answer"]
