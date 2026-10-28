# Clinic Booking API

A REST API for a clinic appointment booking system, built with **FastAPI, SQLAlchemy 2 and PostgreSQL**. The application supports appointment availability, booking, cancellation and rescheduling, with database-level protection against double booking.

---

## Section 1 — System Design

### 1.1 Requirements analysis

The clinic has five doctors, each with defined working hours. Patients must be able to view available appointment slots, book appointments, cancel existing bookings and reschedule when necessary.

I translated the requirements into the following system behaviours:

| Requirement                             | Design decision                                                       |
| --------------------------------------- | --------------------------------------------------------------------- |
| Doctors have defined working hours      | Store recurring weekly schedules for each doctor.                     |
| Appointments use 30-minute slots        | Generate slots from the doctor's schedule.                            |
| Patients can view available slots       | Calculate availability from the schedule and active appointments.     |
| A slot cannot be booked twice           | Enforce uniqueness at the database level.                             |
| Patients can cancel appointments        | Retain cancelled records for audit purposes and release the slot.     |
| Patients can reschedule appointments    | Validate the replacement slot and update the booking transactionally. |
| The system should support future growth | Separate API endpoints, business logic and persistence.               |

### 1.2 System components

The application follows a layered architecture:

```text
Client
  |
  v
FastAPI Routers
  |
  v
Service Layer
  |-- Booking and rescheduling
  |-- Availability calculation
  |-- Appointment validation
  |
  v
SQLAlchemy ORM
  |
  v
PostgreSQL
```

- **API layer:** Handles HTTP requests, request validation, response serialization and status codes.
- **Service layer:** Implements booking rules, availability calculations and appointment lifecycle operations.
- **Persistence layer:** Uses SQLAlchemy to manage database access and transactions.
- **Database:** Stores doctors, schedules, patients and appointments while enforcing data integrity.

Keeping business rules in the service layer makes them easier to test and reuse without duplicating logic across endpoints.

### 1.3 Data model

**Doctor**

Stores each doctor's ID, name and specialty.

**DoctorSchedule**

Stores the doctor's ID, day of the week, start time and end time. Multiple schedule blocks can be configured for the same day to accommodate breaks.

For the initial implementation, seed data provides weekday working hours of 08:00–12:00 and 13:00–17:00.

**Patient**

Stores the patient's ID, name, email address and phone number. Email addresses are unique.

**Appointment**

Stores the doctor ID, patient ID, start time, end time, appointment status, cancellation reason, cancellation timestamp and creation/update timestamps.

Appointments have two states: `booked` and `cancelled`. Cancelled appointments remain in the database to preserve their history.

### 1.4 Key design decisions and trade-offs

#### Decision 1: Calculate availability rather than storing individual slots

Available slots are generated from a doctor's working schedule, then compared against existing active appointments.

I considered storing every slot in a separate table with a booking status. Although that would simplify some availability queries, it would introduce additional maintenance requirements whenever schedules change.

For a small clinic with fixed 30-minute appointments, calculating availability on demand is simpler and avoids maintaining two sources of truth.

If the clinic later needs doctor leave, public holidays or date-specific schedule changes, a `ScheduleException` model can be introduced.

#### Decision 2: Enforce booking uniqueness in the database

The application checks availability before attempting a booking, but this check alone cannot prevent simultaneous requests from claiming the same slot.

The design therefore uses a PostgreSQL partial unique index on `(doctor_id, start_time)` for appointments whose status is `booked`.

The service translates a uniqueness violation into an HTTP `409 Conflict` response.

Cancelled appointments are excluded from the index, allowing their slots to be booked again without a separate slot-release operation.

This design is appropriate for the fixed-slot model, provided all bookings are validated against the same 30-minute boundaries. It does not, by itself, prevent arbitrary overlapping appointment intervals.

#### Decision 3: Retain cancelled appointments

Cancellation updates the appointment status and records the reason and cancellation timestamp rather than deleting the record.

This preserves an audit trail and supports future reporting on cancellations and appointment history. The trade-off is continued database growth, which is acceptable for the initial scale.

#### Decision 4: Reschedule within a database transaction

Rescheduling updates the existing appointment rather than cancelling it and creating a separate appointment.

The replacement slot is validated using the same rules as a new booking. The database update is transactional, so a failed validation or booking conflict must leave the original appointment unchanged.

This approach avoids losing the patient's existing booking when a replacement slot cannot be secured.

#### Decision 5: Handle time zones explicitly

The design stores appointment timestamps in UTC using PostgreSQL `TIMESTAMPTZ`. Doctor working hours are expressed in the clinic's local time zone, configured as `Africa/Nairobi`.

Input timestamps with an explicit UTC offset are interpreted accordingly. Naive timestamps are treated as clinic-local time.

API responses use clinic-local time with an offset, while internal comparisons use timezone-aware timestamps.

This keeps scheduling rules explicit and reduces ambiguity when comparing appointment times.

#### Decision 6: Return consistent error responses

The API uses a consistent error structure:

```json
{
  "error": {
    "code": "slot_unavailable",
    "message": "The selected appointment slot is no longer available."
  }
}
```

The intended HTTP status codes are:

| Status                      | Purpose                                                     |
| --------------------------- | ----------------------------------------------------------- |
| `201 Created`               | Appointment or patient successfully created                 |
| `404 Not Found`             | Requested doctor, patient or appointment does not exist     |
| `409 Conflict`              | Slot conflict, duplicate email or invalid appointment state |
| `422 Unprocessable Content` | Invalid input or booking-rule violation                     |

The distinction is between conflicts with existing system state and requests that violate the defined booking rules.

### 1.5 Assumptions and scope

The assessment leaves some requirements open to interpretation. I made the following decisions:

- **Patient identification:** Authentication is outside the initial scope. A patient ID identifies the patient associated with a booking. A patient-creation endpoint is included to support the booking flow.
- **Minimum booking notice:** The bonus requirement is implemented through a configurable `MIN_LEAD_MINUTES=60` setting. Slots less than 60 minutes away are rejected; a slot exactly 60 minutes away is allowed.
- **Availability consistency:** The availability endpoint excludes slots that fail the same booking rules used when creating an appointment.
- **Rescheduling:** An appointment retains its original doctor. Changing doctors is treated as a separate booking.
- **Past appointments:** Appointments that have already started cannot be cancelled or rescheduled.
- **Same-slot rescheduling:** Requesting the current slot returns a validation error rather than silently succeeding.
- **Cancellation reason:** A reason is required and must contain 3–500 characters.
- **Slot alignment:** Times that do not align with the configured 30-minute slots are rejected rather than rounded.
- **Authentication and authorization:** These are not implemented in the initial scope. They would be essential before the API could be used with real patient data.

### 1.6 Future improvements

The design can evolve as the clinic's needs grow:

1. **Authentication and authorization:** Introduce JWT or OIDC authentication and role-based access for patients, doctors and administrators.
2. **Database migrations:** Replace automatic table creation with Alembic migrations for controlled schema changes.
3. **Schedule exceptions:** Support leave, holidays and date-specific working hours.
4. **Notifications:** Add appointment reminders and cancellation notifications through a background task queue.
5. **Observability:** Introduce structured logging, request IDs, metrics and monitoring.
6. **Security and reliability:** Add rate limiting, stronger access controls and production-grade operational safeguards.
7. **Multi-clinic support:** Introduce a clinic identifier and update the relevant data constraints and access rules.

These improvements are deliberately outside the initial scope so that the core booking workflow can be implemented and tested first.

---

## Section 2 — API Implementation

### 2.1 Required endpoints

| Method  | Endpoint                                     | Description                                                 |
| ------- | -------------------------------------------- | ----------------------------------------------------------- |
| `POST`  | `/appointments`                              | Book an appointment after validating the selected slot      |
| `GET`   | `/doctors/{id}/availability?date=YYYY-MM-DD` | Return available slots for a doctor on a given date         |
| `PATCH` | `/appointments/{id}/cancel`                  | Cancel an appointment with a reason                         |
| `PATCH` | `/appointments/{id}/reschedule`              | Reschedule an existing appointment                          |
| `GET`   | `/patients/{id}/appointments`                | Return upcoming appointments in chronological order (bonus) |

Supporting endpoints include `GET /appointments/{id}`, `GET /doctors`, `POST /patients` and `GET /health`.

### 2.2 Example requests

Set the base URL to the locally running API or the deployed application.

```bash
export URL="http://localhost:8000"
```

**Book an appointment**

```bash
curl -X POST "$URL/appointments" \
  -H "Content-Type: application/json" \
  -d '{
    "doctor_id": 1,
    "patient_id": 1,
    "start_time": "2030-01-08T10:00:00+03:00"
  }'
```

**Check availability**

```bash
curl "$URL/doctors/1/availability?date=2030-01-08"
```

**Cancel an appointment**

```bash
curl -X PATCH "$URL/appointments/1/cancel" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Appointment no longer required"}'
```

**Reschedule an appointment**

```bash
curl -X PATCH "$URL/appointments/1/reschedule" \
  -H "Content-Type: application/json" \
  -d '{"new_start_time": "2030-01-08T11:00:00+03:00"}'
```

### 2.3 Project structure

```text
app/
  main.py
  config.py
  database.py
  models.py
  schemas.py
  errors.py
  clock.py
  seed.py
  routers/
  services/

tests/
```

The application separates configuration, database access, data models, request/response schemas, error handling, API routes and business services.

The `clock.py` component supports deterministic testing by allowing the current time to be controlled in tests.

### 2.4 Running locally

Create and activate a virtual environment, then install the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

**Option A — SQLite**

```bash
uvicorn app.main:app --reload
```

**Option B — PostgreSQL**

Start the database using the supplied Docker Compose configuration:

```bash
docker compose up -d db
```

Configure the database connection:

```bash
export DATABASE_URL="postgresql://clinic:clinic@localhost:5432/clinic"
```

Then start the application:

```bash
uvicorn app.main:app --reload
```

### 2.5 Automated tests

Run the test suite with:

```bash
pytest -q
```

The test suite is designed to cover:

- Successful booking and occupied-slot rejection.
- Past appointments and minimum booking notice.
- Working-hour, lunch-break, weekend and slot-alignment validation.
- Time-zone handling.
- Availability calculations.
- Cancellation and slot reuse.
- Repeated cancellation.
- Successful and failed rescheduling.
- Preservation of the original appointment after a rescheduling conflict.
- Upcoming appointment listing.
- Database-level duplicate-booking protection.

The tests use SQLite and a controlled clock to make time-dependent scenarios deterministic.

**Database testing limitation:** SQLite and PostgreSQL do not have identical concurrency and transaction behaviour. The database constraint should therefore also be verified against PostgreSQL before production submission. A passing SQLite test suite alone does not establish that concurrent production writes have been tested.

---

## Section 3 — Deployment and CI/CD

### 3.1 Deployment architecture

The application is intended to run on Render, using a web service and managed PostgreSQL database defined in `render.yaml`.

- **Web service:** Hosts the FastAPI application.
- **Database:** Stores clinic and appointment data.
- **Repository:** GitHub repository containing application code, tests and deployment configuration.
- **CI/CD:** GitHub Actions runs tests and triggers deployment after successful merges to `main`.


### 3.2 Pipeline behaviour

The GitHub Actions workflow is defined in `.github/workflows/ci.yml`.

| Trigger                       | Expected behaviour                                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Pull request targeting `main` | Install dependencies and run the test suite                                                                                          |
| Push or merge to `main`       | Run tests; deploy only if tests pass                                                                                                 |
| After deployment              | Poll the application's health endpoint and fail the workflow if the deployment does not become healthy within the configured timeout |

Render deployment is triggered through a deployment hook, with automatic deployment disabled, so the workflow can gate deployment on the test result.

Branch protection on `main` is recommended to require pull requests and successful status checks before merging.

---

## Section 4 — AI Reflection

### 4.1 What did I use AI for across the four sections?

I used AI as a development assistant to structure my approach, review design alternatives, identify edge cases and improve the clarity of my technical documentation.

- **System design:** I used AI to help review the proposed data model, appointment lifecycle and trade-offs between calculating availability dynamically and storing individual slots.
- **API implementation:** I used AI to help reason through endpoint validation, HTTP status codes, cancellation, rescheduling and database integrity. I treated its suggestions as inputs to review rather than assuming they were automatically correct.
- **Deployment and CI/CD:** I used AI to help structure the deployment workflow and identify what needed to be verified in the test and deployment sequence.
- **Reflection and documentation:** I used AI to review the clarity, consistency and alignment with the assessment requirements.

I remained responsible for deciding which approaches were appropriate for the stated requirements and for verifying that the final implementation matched the documented behaviour.

### 4.2 One example where an AI suggestion improved my work

One useful example was reviewing how to prevent two patients from booking the same appointment slot simultaneously.

**Prompt used:**

"Review the booking design for a clinic API with fixed 30-minute appointment slots. Can checking availability before inserting an appointment prevent double booking when two requests arrive simultaneously? Recommend a reliable approach and explain the trade-offs."

The review highlighted that an application-level availability check is not sufficient on its own because two concurrent requests could both pass the check before either booking is saved.

This led to a stronger design using a database-level uniqueness constraint alongside application validation and appropriate error handling.

The improvement was addressing the underlying data-integrity risk.

### 4.3 Where AI output was incomplete, and how I addressed it

During the README review, AI-assisted feedback identified the partial unique index as a suitable way to prevent duplicate bookings for fixed appointment slots. However, that safeguard alone does not prevent every possible overlap between arbitrary appointment intervals.

I addressed this by making the fixed 30-minute slot assumption explicit and distinguishing duplicate-slot protection from general interval-overlap protection.

I also recognised that a README review cannot prove that the code, database schema or deployment behaves as documented. Those claims need to be checked against the implementation, tests and running application.

### 4.4 Decisions I made using my own judgment

**Keep the initial scope focused on the core booking workflow.**

I prioritised booking, availability, cancellation, rescheduling and validation before introducing additional features such as authentication, notifications and schedule exceptions. My reasoning was that this requires a functional, testable implementation within a limited time. Adding too many features early would increase complexity and reduce the time available to verify the core requirements.

**Make booking rules consistent across the application.**

I chose to reuse the same validation logic for booking and rescheduling and to ensure that availability reflects the rules applied during booking. My reasoning was that inconsistent validation could cause the API to advertise slots that it subsequently rejects or allow rescheduling behaviour that differs from a new booking. Keeping these rules aligned makes the system more predictable and easier to test.

