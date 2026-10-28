import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Appointment
from tests.conftest import at

TUE = "2030-01-08"


def code(resp):
    return resp.json()["error"]["code"]


class TestBook:
    def test_books_a_valid_slot(self, book):
        r = book(at(TUE, "10:00"))
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "booked"
        assert body["start_time"] == "2030-01-08T10:00:00+03:00"
        assert body["end_time"] == "2030-01-08T10:30:00+03:00"

    def test_naive_datetime_is_treated_as_clinic_local(self, book):
        r = book(f"{TUE}T10:00:00")
        assert r.status_code == 201
        assert r.json()["start_time"] == "2030-01-08T10:00:00+03:00"

    def test_same_instant_in_other_timezone_is_the_same_slot(self, book):
        assert book(at(TUE, "10:00")).status_code == 201
        r = book(f"{TUE}T07:00:00Z", patient="p2")  # 07:00Z == 10:00 Nairobi
        assert r.status_code == 409

    def test_slot_already_taken_returns_409(self, book):
        assert book(at(TUE, "10:00")).status_code == 201
        r = book(at(TUE, "10:00"), patient="p2")
        assert r.status_code == 409
        assert code(r) == "slot_taken"

    def test_past_slot_returns_422(self, book):
        r = book(at("2030-01-04", "10:00"))
        assert r.status_code == 422
        assert code(r) == "slot_in_past"

    def test_slot_equal_to_now_is_past(self, book):
        assert code(book(at("2030-01-07", "08:00"))) == "slot_in_past"

    def test_within_one_hour_returns_422(self, book):
        r = book(at("2030-01-07", "08:30"))  # now is 08:00
        assert r.status_code == 422
        assert code(r) == "slot_too_soon"

    def test_exactly_one_hour_ahead_is_allowed(self, book):
        assert book(at("2030-01-07", "09:00")).status_code == 201

    @pytest.mark.parametrize("hhmm", ["07:30", "12:00", "12:30", "17:00", "20:00"])
    def test_outside_working_hours_returns_422(self, book, hhmm):
        r = book(at(TUE, hhmm))
        assert r.status_code == 422
        assert code(r) == "outside_working_hours"

    def test_weekend_returns_422(self, book):
        assert code(book(at("2030-01-12", "10:00"))) == "outside_working_hours"

    @pytest.mark.parametrize("hhmm", ["10:15", "10:01"])
    def test_misaligned_slot_returns_422(self, book, hhmm):
        r = book(at(TUE, hhmm))
        assert r.status_code == 422
        assert code(r) == "slot_not_aligned"

    def test_last_slot_of_each_block_is_bookable(self, book):
        assert book(at(TUE, "11:30")).status_code == 201
        assert book(at(TUE, "16:30")).status_code == 201

    def test_unknown_doctor_and_patient_return_404(self, book, client, world):
        assert book(at(TUE, "10:00"), doctor_id=999).status_code == 404
        r = client.post("/appointments", json={"doctor_id": world["doctor"].id, "patient_id": 999, "start_time": at(TUE, "10:00")})
        assert r.status_code == 404

    def test_invalid_payload_returns_structured_422(self, client):
        r = client.post("/appointments", json={"doctor_id": "x"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"
        assert r.json()["error"]["details"]


class TestAvailability:
    def test_full_day_has_16_slots_with_lunch_gap(self, client, world):
        r = client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": TUE})
        assert r.status_code == 200
        starts = [s["start_time"][11:16] for s in r.json()["slots"]]
        assert len(starts) == 16
        assert starts[0] == "08:00" and starts[-1] == "16:30"
        assert "12:00" not in starts and "12:30" not in starts

    def test_booked_slot_disappears(self, client, world, book):
        book(at(TUE, "10:00"))
        r = client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": TUE})
        starts = [s["start_time"][11:16] for s in r.json()["slots"]]
        assert len(starts) == 15 and "10:00" not in starts

    def test_weekend_is_empty(self, client, world):
        r = client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": "2030-01-12"})
        assert r.json()["slots"] == []

    def test_today_hides_past_and_too_soon_slots(self, client, world):
        r = client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": "2030-01-07"})
        starts = [s["start_time"][11:16] for s in r.json()["slots"]]
        assert starts[0] == "09:00"  # now=08:00 + 60 min lead
        assert len(starts) == 14

    def test_unknown_doctor_404_and_bad_date_422(self, client, world):
        assert client.get("/doctors/999/availability", params={"date": TUE}).status_code == 404
        assert client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": "nope"}).status_code == 422


class TestCancel:
    def test_cancel_frees_the_slot(self, client, world, book):
        appt = book(at(TUE, "10:00")).json()
        r = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Feeling better"})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "Feeling better"
        avail = client.get(f"/doctors/{world['doctor'].id}/availability", params={"date": TUE}).json()["slots"]
        assert "10:00" in [s["start_time"][11:16] for s in avail]
        assert book(at(TUE, "10:00"), patient="p2").status_code == 201  # rebookable by someone else

    def test_cancelling_twice_returns_409(self, client, book):
        appt = book(at(TUE, "10:00")).json()
        client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Changed plans"})
        r = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Changed plans"})
        assert r.status_code == 409 and code(r) == "already_cancelled"

    def test_reason_is_required(self, client, book):
        appt = book(at(TUE, "10:00")).json()
        assert client.patch(f"/appointments/{appt['id']}/cancel", json={}).status_code == 422
        assert client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": ""}).status_code == 422

    def test_unknown_appointment_404(self, client):
        assert client.patch("/appointments/999/cancel", json={"reason": "whatever"}).status_code == 404


class TestReschedule:
    def test_moves_appointment_and_frees_original(self, client, world, book):
        appt = book(at(TUE, "10:00")).json()
        r = client.patch(f"/appointments/{appt['id']}/reschedule", json={"new_start_time": at(TUE, "14:00")})
        assert r.status_code == 200
        assert r.json()["start_time"] == "2030-01-08T14:00:00+03:00"
        starts = [s["start_time"][11:16] for s in client.get(
            f"/doctors/{world['doctor'].id}/availability", params={"date": TUE}).json()["slots"]]
        assert "10:00" in starts and "14:00" not in starts

    def test_new_slot_taken_returns_409_and_keeps_original(self, client, book):
        mine = book(at(TUE, "10:00")).json()
        book(at(TUE, "14:00"), patient="p2")
        r = client.patch(f"/appointments/{mine['id']}/reschedule", json={"new_start_time": at(TUE, "14:00")})
        assert r.status_code == 409 and code(r) == "slot_taken"
        assert client.get(f"/appointments/{mine['id']}").json()["start_time"] == "2030-01-08T10:00:00+03:00"

    @pytest.mark.parametrize("hhmm,expected", [("12:00", "outside_working_hours"), ("10:10", "slot_not_aligned")])
    def test_new_slot_is_validated_like_a_fresh_booking(self, client, book, hhmm, expected):
        appt = book(at(TUE, "10:00")).json()
        r = client.patch(f"/appointments/{appt['id']}/reschedule", json={"new_start_time": at(TUE, hhmm)})
        assert r.status_code == 422 and code(r) == expected

    def test_cannot_reschedule_into_the_past(self, client, book):
        appt = book(at(TUE, "10:00")).json()
        r = client.patch(f"/appointments/{appt['id']}/reschedule", json={"new_start_time": at("2030-01-04", "10:00")})
        assert r.status_code == 422 and code(r) == "slot_in_past"

    def test_cancelled_appointment_cannot_be_rescheduled(self, client, book):
        appt = book(at(TUE, "10:00")).json()
        client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Changed plans"})
        r = client.patch(f"/appointments/{appt['id']}/reschedule", json={"new_start_time": at(TUE, "11:00")})
        assert r.status_code == 409 and code(r) == "appointment_cancelled"

    def test_same_slot_returns_422(self, client, book):
        appt = book(at(TUE, "10:00")).json()
        r = client.patch(f"/appointments/{appt['id']}/reschedule", json={"new_start_time": at(TUE, "10:00")})
        assert r.status_code == 422 and code(r) == "same_slot"


class TestPatientAppointments:
    def test_upcoming_sorted_and_excludes_cancelled(self, client, world, book):
        late = book(at("2030-01-09", "10:00")).json()
        early = book(at(TUE, "09:00")).json()
        gone = book(at(TUE, "15:00")).json()
        client.patch(f"/appointments/{gone['id']}/cancel", json={"reason": "Changed plans"})
        book(at(TUE, "11:00"), patient="p2")  # other patient's booking must not leak in
        r = client.get(f"/patients/{world['p1'].id}/appointments")
        assert r.status_code == 200
        assert [a["id"] for a in r.json()] == [early["id"], late["id"]]

    def test_unknown_patient_404(self, client):
        assert client.get("/patients/999/appointments").status_code == 404

    def test_create_patient_and_duplicate_email(self, client):
        payload = {"name": "New Person", "email": "New@Example.com"}
        assert client.post("/patients", json=payload).status_code == 201
        assert client.post("/patients", json=payload).status_code == 409


class TestDatabaseInvariant:
    """The DB, not just the app code, must refuse a double booking (race-condition safety net)."""

    def _appt(self, world, start, status="booked"):
        from datetime import timedelta
        return Appointment(doctor_id=world["doctor"].id, patient_id=world["p1"].id,
                           start_time=start, end_time=start + timedelta(minutes=30), status=status)

    def test_two_active_bookings_for_same_slot_are_rejected(self, db_session, world):
        from datetime import datetime, timezone
        start = datetime(2030, 1, 8, 7, 0, tzinfo=timezone.utc)
        db_session.add(self._appt(world, start))
        db_session.commit()
        db_session.add(self._appt(world, start))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_cancelled_rows_do_not_block_the_slot(self, db_session, world):
        from datetime import datetime, timezone
        start = datetime(2030, 1, 8, 7, 0, tzinfo=timezone.utc)
        db_session.add_all([self._appt(world, start, "cancelled"), self._appt(world, start, "cancelled"),
                            self._appt(world, start)])
        db_session.commit()
