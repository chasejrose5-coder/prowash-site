import html
import hmac
import json
import threading
import uuid
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

DATA_PATH = Path(__file__).resolve().parent / "bookings.json"
CONTACT_EMAIL = "prowashdetailco5@gmail.com"
CONTACT_PHONE = "(925) 915-6541"
CONTACT_PHONE_TEL = "+19259156541"
ADMIN_EMAIL = "chasejrose50@gmail.com"
ADMIN_PASSWORD = "1463dragon"
LOOKAHEAD_DAYS = 14
BLACKOUT_HORIZON_DAYS = 120
TIME_SLOTS = ["8:00 AM", "10:00 AM", "12:00 PM", "2:00 PM", "4:00 PM"]
SERVICES = [
    (
        "Car Detailing",
        "Interior and exterior car care that restores the finish, protects the paint, and leaves the cabin immaculate.",
    ),
    (
        "Power Washing",
        "Driveways, patios, siding, and storefronts cleaned with controlled pressure and a light touch.",
    ),
    (
        "Solar Panel Cleaning",
        "Gentle washing that clears dust and debris so your panels can perform as they should.",
    ),
    (
        "Trash Can Cleaning",
        "Bins sanitized inside and out, so the curb looks as considered as the rest of the property.",
    ),
]
SERVICE_NAMES = [title for title, _description in SERVICES]
STAFF_VIEW = "staff"
COMPLETED_VIEW = "completed"
WORKERS = ("Mason", "Luke", "Noah", "Chase")
WORKER_VIEWS = tuple(name.casefold() for name in WORKERS)
# Accepted and claimed hold the public slot. Pending, declined, and completed do not.
BLOCKING_STATUSES = frozenset({"accepted", "claimed"})
STATUS_LABELS = {
    "pending": "Pending",
    "accepted": "Accepted",
    "claimed": "Claimed",
    "completed": "Completed",
    "declined": "Declined",
}
SECTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "pending",
        "Pending",
        "These requests are not on the public calendar. Accept one to hold the time, or decline it.",
        "No requests waiting.",
    ),
    (
        "accepted",
        "Accepted",
        "Confirmed, and still unclaimed. Choose Mason, Luke, Noah, or Chase to claim the shift.",
        "No jobs waiting for a worker.",
    ),
    (
        "claimed",
        "Claimed",
        "These shifts have a worker. Their times stay booked on the public calendar.",
        "No jobs have been claimed yet.",
    ),
    (
        "completed",
        "Completed",
        "Finished jobs. These times are open on the public calendar again.",
        "No completed jobs yet.",
    ),
    (
        "declined",
        "Declined",
        "Turned down. These times stay open on the public calendar.",
        "No declined requests.",
    ),
)
_LOCK = threading.Lock()


class BookingStoreError(Exception):
    """bookings.json is missing its expected shape or cannot be read."""


class SlotTaken(Exception):
    """Another accepted or claimed booking already holds this date and time."""


class DateClosed(Exception):
    """The chosen day is on the blackout list."""


def calendar_bounds(today: date) -> tuple[date, date]:
    first = today + timedelta(days=1)
    last = today + timedelta(days=LOOKAHEAD_DAYS)
    return first, last


def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def visible_days(today: date) -> list[date]:
    first, last = calendar_bounds(today)
    days: list[date] = []
    day = first
    while day <= last:
        days.append(day)
        day += timedelta(days=1)
    return days


def first_open_day(today: date, blackouts: list[str]) -> date:
    closed = set(blackouts)
    for day in visible_days(today):
        if day.isoformat() not in closed:
            return day
    return visible_days(today)[0]


def format_long_date(iso_date: str) -> str:
    try:
        day = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return iso_date or "—"
    return f"{day.strftime('%A, %B')} {day.day}, {day.year}"


def format_month_day(day: date) -> str:
    return f"{day.strftime('%B')} {day.day}"


def _clean_blackouts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    days: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        try:
            days.append(date.fromisoformat(item).isoformat())
        except ValueError:
            continue
    return sorted(set(days))


def _read_store() -> tuple[list[dict], list[str], bool]:
    if not DATA_PATH.exists():
        return [], [], False
    try:
        raw = DATA_PATH.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BookingStoreError("Saved appointments could not be read.") from exc
    if not raw.strip():
        return [], [], False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BookingStoreError("Saved appointments could not be read.") from exc

    migrated = False
    if isinstance(data, list):
        bookings = [item for item in data if isinstance(item, dict)]
        return bookings, [], len(bookings) != len(data)
    if not isinstance(data, dict):
        raise BookingStoreError("Saved appointments could not be read.")

    raw_bookings = data.get("bookings", [])
    if not isinstance(raw_bookings, list):
        raw_bookings = []
        migrated = True
    bookings = [item for item in raw_bookings if isinstance(item, dict)]
    if len(bookings) != len(raw_bookings):
        migrated = True
    blackouts = _clean_blackouts(data.get("blackouts"))
    if data.get("blackouts") != blackouts:
        migrated = True
    return bookings, blackouts, migrated


def _write_store(bookings: list[dict], blackouts: list[str]) -> None:
    payload = {"bookings": bookings, "blackouts": _clean_blackouts(blackouts)}
    temporary = DATA_PATH.with_name("bookings.json.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(DATA_PATH)
    except OSError as exc:
        raise BookingStoreError("That change could not be saved.") from exc


def booking_status(record: dict) -> str:
    status = str(record.get("status") or "").strip().lower()
    claimed_by = str(record.get("claimed_by") or "").strip()
    if record.get("completed") is True or status == "completed":
        return "completed"
    if status == "declined":
        return "declined"
    if status == "claimed" or (status == "accepted" and claimed_by):
        return "claimed"
    if status == "accepted":
        return "accepted"
    return "pending"


def booking_section(record: dict) -> str:
    status = booking_status(record)
    if status in {"pending", "accepted", "claimed", "completed", "declined"}:
        return status
    return "pending"


def _stamp_records(bookings: list[dict]) -> bool:
    changed = False
    for item in bookings:
        if not str(item.get("id") or "").strip():
            item["id"] = uuid.uuid4().hex
            changed = True
        if "claimed_by" not in item or not isinstance(item.get("claimed_by"), str):
            item["claimed_by"] = str(item.get("claimed_by") or "").strip()
            changed = True
        if not isinstance(item.get("customer_confirmed"), bool):
            item["customer_confirmed"] = bool(item.get("customer_confirmed"))
            changed = True
        if not isinstance(item.get("completed"), bool):
            item["completed"] = str(item.get("status") or "").strip().lower() == "completed"
            changed = True
        if not str(item.get("status") or "").strip():
            item["status"] = "pending"
            changed = True
        normalized = booking_status(item)
        if item.get("status") != normalized:
            item["status"] = normalized
            changed = True
        if item.get("completed") is not (normalized == "completed"):
            item["completed"] = normalized == "completed"
            changed = True
        if normalized in {"pending", "declined"} and item.get("claimed_by"):
            item["claimed_by"] = ""
            changed = True
    return changed


def load_store() -> tuple[list[dict], list[str]]:
    with _LOCK:
        bookings, blackouts, migrated = _read_store()
        if _stamp_records(bookings) or migrated:
            _write_store(bookings, blackouts)
        return bookings, blackouts


def _find(bookings: list[dict], booking_id: str) -> dict | None:
    return next((item for item in bookings if item.get("id") == booking_id), None)


def _slot_blocked(
    bookings: list[dict],
    iso_date: str,
    slot: str,
    skip: dict | None = None,
) -> bool:
    return any(
        item is not skip
        and item.get("date") == iso_date
        and item.get("time") == slot
        and booking_status(item) in BLOCKING_STATUSES
        for item in bookings
    )


def add_booking(record: dict) -> None:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        if record["date"] in set(blackouts):
            raise DateClosed()
        if _slot_blocked(bookings, record["date"], record["time"]):
            raise SlotTaken()
        record["id"] = uuid.uuid4().hex
        record["status"] = "pending"
        record["claimed_by"] = ""
        record["completed"] = False
        record["customer_confirmed"] = False
        bookings.append(record)
        _write_store(bookings, blackouts)


def accept_booking(booking_id: str) -> dict:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        target = _find(bookings, booking_id)
        if target is None:
            raise BookingStoreError("That booking could not be saved.")
        status = booking_status(target)
        if status == "accepted":
            return dict(target)
        if status != "pending":
            raise BookingStoreError("That booking is no longer pending.")
        iso_date = str(target.get("date") or "")
        if iso_date in set(blackouts):
            raise DateClosed()
        if _slot_blocked(
            bookings,
            iso_date,
            str(target.get("time") or ""),
            skip=target,
        ):
            raise SlotTaken()
        target["status"] = "accepted"
        target["completed"] = False
        target["claimed_by"] = ""
        _write_store(bookings, blackouts)
        return dict(target)


def decline_booking(booking_id: str) -> dict:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        target = _find(bookings, booking_id)
        if target is None:
            raise BookingStoreError("That booking could not be saved.")
        if booking_status(target) != "pending":
            raise BookingStoreError("That booking is no longer pending.")
        target["status"] = "declined"
        target["completed"] = False
        target["claimed_by"] = ""
        _write_store(bookings, blackouts)
        return dict(target)


def canonical_worker(name: object) -> str | None:
    text = str(name or "").strip().casefold()
    for worker in WORKERS:
        if worker.casefold() == text:
            return worker
    return None


def claim_booking(booking_id: str, worker_name: str) -> dict:
    name = canonical_worker(worker_name)
    if name is None:
        raise BookingStoreError("Choose Mason, Luke, Noah, or Chase.")
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        target = _find(bookings, booking_id)
        if target is None:
            raise BookingStoreError("That shift could not be saved.")
        status = booking_status(target)
        current = str(target.get("claimed_by") or "").strip()
        if status == "claimed" or (status == "completed" and current):
            who = canonical_worker(current) or current or "someone"
            raise BookingStoreError(f"{who} already claimed this shift.")
        if status != "accepted":
            raise BookingStoreError("That shift is not open.")
        target["status"] = "claimed"
        target["claimed_by"] = name
        target["completed"] = False
        _write_store(bookings, blackouts)
        return dict(target)


def complete_booking(booking_id: str) -> dict:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        target = _find(bookings, booking_id)
        if target is None:
            raise BookingStoreError("That job could not be saved.")
        if booking_status(target) not in {"accepted", "claimed"}:
            raise BookingStoreError("That job cannot be marked completed.")
        target["status"] = "completed"
        target["completed"] = True
        _write_store(bookings, blackouts)
        return dict(target)


def set_customer_confirmed(booking_id: str, confirmed: bool) -> None:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        target = _find(bookings, booking_id)
        if target is None:
            raise BookingStoreError("That booking could not be saved.")
        target["customer_confirmed"] = bool(confirmed)
        _write_store(bookings, blackouts)


def add_blackout(iso_date: str) -> None:
    try:
        cleaned = date.fromisoformat(iso_date).isoformat()
    except ValueError as exc:
        raise BookingStoreError("Choose a valid date.") from exc
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        if cleaned in blackouts:
            raise BookingStoreError("That date is already blocked.")
        blackouts.append(cleaned)
        _write_store(bookings, blackouts)


def remove_blackout(iso_date: str) -> None:
    with _LOCK:
        bookings, blackouts, _migrated = _read_store()
        remaining = [day for day in blackouts if day != iso_date]
        _write_store(bookings, remaining)


def slot_taken(bookings: list[dict], day: date, slot: str) -> bool:
    return _slot_blocked(bookings, day.isoformat(), slot)


def booking_sort_key(record: dict) -> tuple:
    raw_date = str(record.get("date") or "")
    try:
        iso_date = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        iso_date = "9999-12-31"
    raw_time = str(record.get("time") or "")
    try:
        slot_index = TIME_SLOTS.index(raw_time)
    except ValueError:
        slot_index = len(TIME_SLOTS)
    return (iso_date, slot_index)


def job_counts(bookings: list[dict], today: date) -> tuple[int, int, int]:
    week_start, week_end = week_bounds(today)
    today_count = 0
    week_count = 0
    unclaimed = 0
    for record in bookings:
        status = booking_status(record)
        if status == "accepted":
            unclaimed += 1
        if status not in {"accepted", "claimed", "completed"}:
            continue
        try:
            day = date.fromisoformat(str(record.get("date") or ""))
        except ValueError:
            continue
        if day == today:
            today_count += 1
        if week_start <= day <= week_end:
            week_count += 1
    return today_count, week_count, unclaimed


def worker_week_counts(bookings: list[dict], today: date) -> dict[str, int]:
    week_start, week_end = week_bounds(today)
    counts = {name: 0 for name in WORKERS}
    for record in bookings:
        if booking_status(record) not in {"claimed", "completed"}:
            continue
        worker = canonical_worker(record.get("claimed_by"))
        if worker is None:
            continue
        try:
            day = date.fromisoformat(str(record.get("date") or ""))
        except ValueError:
            continue
        if week_start <= day <= week_end:
            counts[worker] += 1
    return counts


def record_matches(
    record: dict,
    *,
    service: str,
    iso_date: str | None,
    query: str,
) -> bool:
    if service != "All services" and str(record.get("service") or "") != service:
        return False
    if iso_date and str(record.get("date") or "") != iso_date:
        return False
    text = query.strip().casefold()
    if not text:
        return True
    raw_date = str(record.get("date") or "")
    haystack = " ".join(
        [
            str(record.get("name") or ""),
            str(record.get("phone") or ""),
            str(record.get("email") or ""),
            str(record.get("address") or ""),
            str(record.get("service") or ""),
            raw_date,
            format_long_date(raw_date),
            str(record.get("time") or ""),
            str(record.get("notes") or ""),
            str(record.get("claimed_by") or ""),
            STATUS_LABELS.get(booking_status(record), ""),
        ]
    ).casefold()
    return text in haystack


def date_choices(bookings: list[dict]) -> list[tuple[str, str | None]]:
    seen: set[str] = set()
    choices: list[tuple[str, str | None]] = [("All dates", None)]
    for record in sorted(bookings, key=booking_sort_key):
        raw_date = str(record.get("date") or "")
        try:
            iso_date = date.fromisoformat(raw_date).isoformat()
        except ValueError:
            continue
        if iso_date in seen:
            continue
        seen.add(iso_date)
        choices.append((format_long_date(iso_date), iso_date))
    return choices


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def display_value(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return esc(text) if text else "—"


def date_value(record: dict) -> str:
    raw_date = str(record.get("date") or "")
    if not raw_date:
        return "—"
    label = format_long_date(raw_date)
    return esc(label) if label != "—" else "—"


def calendar_markup(today: date, bookings: list[dict], blackouts: list[str]) -> str:
    closed_days = set(blackouts)
    days = []
    for day in visible_days(today):
        closed = day.isoformat() in closed_days
        rows = []
        for slot in TIME_SLOTS:
            if slot_taken(bookings, day, slot):
                state, label = "is-taken", "Booked"
            elif closed:
                state, label = "is-closed", "Unavailable"
            else:
                state, label = "is-open", "Available"
            rows.append(
                f'<li class="slot-row {state}"><span class="when">{esc(slot)}</span>'
                f'<span class="status">{label}</span></li>'
            )
        days.append(
            '<div class="cal-day">'
            f'<p class="cal-date">{esc(day.strftime("%A"))}'
            f"<span>{esc(format_month_day(day))}</span></p>"
            f'<ul class="slot-list">{"".join(rows)}</ul>'
            "</div>"
        )
    return f'<div class="calendar">{"".join(days)}</div>'


def detail_rows(record: dict) -> list[tuple[str, str]]:
    rows = [
        ("Name", display_value(record.get("name"))),
        ("Phone", display_value(record.get("phone"))),
        ("Email", display_value(record.get("email"))),
        ("Address", display_value(record.get("address"))),
        ("Service", display_value(record.get("service"))),
        ("Date", date_value(record)),
        ("Time", display_value(record.get("time"))),
    ]
    claimer = str(record.get("claimed_by") or "").strip()
    if claimer:
        rows.append(("Claimed by", display_value(claimer)))
    rows.append(("Notes", display_value(record.get("notes"))))
    return rows


def schedule_rows(record: dict) -> list[tuple[str, str]]:
    return [
        ("Customer", display_value(record.get("name"))),
        ("Service", display_value(record.get("service"))),
        ("Date", date_value(record)),
        ("Time", display_value(record.get("time"))),
        ("Address", display_value(record.get("address"))),
        ("Notes", display_value(record.get("notes"))),
    ]


def completed_rows(record: dict) -> list[tuple[str, str]]:
    worker = str(record.get("claimed_by") or "").strip()
    return [
        ("Service", display_value(record.get("service"))),
        ("Date", date_value(record)),
        ("Time", display_value(record.get("time"))),
        ("Worker", display_value(worker)),
        ("Address", display_value(record.get("address"))),
    ]


def rows_markup(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f'<div class="contact-row"><dt>{label}</dt><dd>{value}</dd></div>'
        for label, value in rows
    )


def contact_rows(record: dict) -> list[tuple[str, str]]:
    return [
        ("Name", display_value(record.get("name"))),
        ("Phone", display_value(record.get("phone"))),
        ("Email", display_value(record.get("email"))),
        ("Address", display_value(record.get("address"))),
    ]


def confirmation_markup(record: dict, *, note: str | None = None, compact: bool = False) -> str:
    subject, body = confirmation_copy(record)
    body_html = esc(body).replace("\r\n", "&#10;").replace("\n", "&#10;")
    note_html = f'<p class="confirm-note">{esc(note)}</p>' if note else ""
    size = " is-compact" if compact else ""
    return (
        '<div class="email-draft">'
        '<p class="confirm-label">Confirmation email</p>'
        f"{note_html}"
        '<label class="copy-field"><span>Subject</span>'
        f'<input class="email-subject-copy" type="text" readonly value="{esc(subject)}" '
        'onclick="this.select()"></label>'
        '<label class="copy-field"><span>Message</span>'
        f'<textarea class="email-copy{size}" readonly onclick="this.select()">{body_html}</textarea>'
        "</label></div>"
    )


def booking_card(record: dict) -> str:
    status = booking_status(record)
    label = STATUS_LABELS.get(status, "Pending")
    claimer = str(record.get("claimed_by") or "").strip()
    claimer_html = (
        f'<p class="booking-claimer">Claimed by {esc(claimer)}</p>' if claimer else ""
    )
    draft = ""
    if status in {"accepted", "claimed"}:
        draft = confirmation_markup(
            record,
            note="Copy this subject and message into your email to the customer.",
            compact=True,
        )
    return (
        f'<article class="booking is-{status}">'
        f'<p class="booking-status is-{status}">{label}</p>'
        f"{claimer_html}"
        f"<dl>{rows_markup(detail_rows(record))}</dl>"
        f"{draft}"
        "</article>"
    )


def completed_card(record: dict) -> str:
    return (
        '<article class="booking is-completed">'
        '<p class="booking-status is-completed">Completed</p>'
        f"<dl>{rows_markup(completed_rows(record))}</dl>"
        "</article>"
    )


def schedule_card(record: dict, label: str) -> str:
    status = "completed" if booking_status(record) == "completed" else "claimed"
    return (
        f'<article class="booking is-{status}">'
        f'<p class="booking-status is-{status}">{esc(label)}</p>'
        f"<dl>{rows_markup(schedule_rows(record))}</dl>"
        "</article>"
    )


def summary_markup(today_count: int, week_count: int, unclaimed: int) -> str:
    waiting = " is-waiting" if unclaimed else ""
    return (
        '<div class="summary">'
        f'<div class="summary-item"><span>Today</span><strong>{today_count}</strong></div>'
        f'<div class="summary-item"><span>This week</span><strong>{week_count}</strong></div>'
        f'<div class="summary-item{waiting}"><span>Unclaimed</span><strong>{unclaimed}</strong></div>'
        "</div>"
    )


def worker_summary_markup(counts: dict[str, int]) -> str:
    items = "".join(
        f'<div class="summary-item"><span>{esc(name)}</span><strong>{counts[name]}</strong></div>'
        for name in WORKERS
    )
    return (
        '<p class="summary-caption">Claimed this week</p>'
        f'<div class="summary summary-workers">{items}</div>'
    )


def confirmation_copy(record: dict) -> tuple[str, str]:
    name = str(record.get("name") or "").strip() or "there"
    service = str(record.get("service") or "").strip() or "appointment"
    when_date = format_long_date(str(record.get("date") or ""))
    when_time = str(record.get("time") or "").strip()
    address = str(record.get("address") or "").strip()
    notes = str(record.get("notes") or "").strip()
    subject = f"Your {service} appointment is confirmed"
    lines = [
        f"Hi {name},",
        "",
        f"Your {service} appointment with ProWash & Detail Co. is confirmed.",
        "",
        f"Date: {when_date}",
        f"Time: {when_time}",
        f"Address: {address}",
    ]
    if notes:
        lines.extend(["", f"Notes: {notes}"])
    lines.extend(
        [
            "",
            "If you need to change anything, reply to this email or call (925) 915-6541.",
            "",
            "ProWash & Detail Co.",
            CONTACT_EMAIL,
        ]
    )
    return subject, "\n".join(lines)


def render_acceptance(record: dict) -> None:
    name = str(record.get("name") or "").strip() or "This customer"
    service = str(record.get("service") or "").strip() or "the requested service"
    when_date = format_long_date(str(record.get("date") or ""))
    when_time = str(record.get("time") or "").strip()
    render_message(
        "success",
        f"Accepted. {name} is booked for {service} on {when_date} at {when_time}.",
    )
    st.markdown(
        '<p class="confirm-label">Customer</p>'
        f'<dl class="confirm-details">{rows_markup(contact_rows(record))}</dl>'
        + confirmation_markup(
            record,
            note="Select the subject and message, then copy them into your own email.",
        ),
        unsafe_allow_html=True,
    )


def credentials_ok(email: str, password: str) -> bool:
    email_ok = hmac.compare_digest(email.strip().casefold(), ADMIN_EMAIL.casefold())
    password_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return email_ok and password_ok


def current_view() -> str | None:
    raw = st.query_params.get("view")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if isinstance(raw, str) and raw == "workers":
        return STAFF_VIEW
    if isinstance(raw, str) and raw in {STAFF_VIEW, COMPLETED_VIEW, *WORKER_VIEWS}:
        return raw
    return None


def enter_staff() -> None:
    st.session_state["view-switch"] = "Staff"
    enter_view(STAFF_VIEW)


def enter_view(view: str) -> None:
    st.query_params["view"] = view
    st.rerun()


def leave_staff() -> None:
    if "view" in st.query_params:
        del st.query_params["view"]
    st.rerun()


def sign_out() -> None:
    st.session_state.admin = False
    st.session_state.accept_notice = None
    st.session_state.accept_error = None
    st.session_state.action_notice = None
    st.session_state.action_error = None
    st.session_state.pending_decline = None
    st.rerun()


def clear_action_messages() -> None:
    st.session_state.action_notice = None
    st.session_state.action_error = None


def clear_accept_panel() -> None:
    st.session_state.accept_notice = None
    st.session_state.accept_error = None


def render_message(kind: str, text: str) -> None:
    st.markdown(
        f'<p class="form-{kind}">{esc(text)}</p>',
        unsafe_allow_html=True,
    )


def render_notices(*, include_accept: bool = True) -> None:
    if include_accept:
        notice = st.session_state.get("accept_notice")
        accept_error = st.session_state.get("accept_error")
        if isinstance(notice, dict):
            render_acceptance(notice)
        if accept_error:
            render_message("error", str(accept_error))
    action_notice = st.session_state.get("action_notice")
    action_error = st.session_state.get("action_error")
    if action_notice:
        render_message("success", str(action_notice))
    if action_error:
        render_message("error", str(action_error))


def job_when(record: dict) -> tuple[str, str, str, str]:
    when_date = format_long_date(str(record.get("date") or ""))
    when_time = str(record.get("time") or "").strip()
    service = str(record.get("service") or "").strip() or "appointment"
    name = str(record.get("name") or "").strip() or "This customer"
    return name, service, when_date, when_time


def validate_booking(
    name: str,
    phone: str,
    email: str,
    address: str,
    service: str | None,
    preferred_date: date,
    slot: str | None,
    today: date,
    bookings: list[dict],
    blackouts: list[str],
) -> str | None:
    if not name.strip():
        return "Enter your name."
    if len("".join(character for character in phone if character.isdigit())) < 7:
        return "Enter a phone number."
    cleaned_email = email.strip()
    if cleaned_email.count("@") != 1:
        return "Enter a valid email."
    local, domain = cleaned_email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return "Enter a valid email."
    if not address.strip():
        return "Enter the service address."
    if service not in SERVICE_NAMES:
        return "Choose a service."
    first, last = calendar_bounds(today)
    if not isinstance(preferred_date, date) or not first <= preferred_date <= last:
        return "Choose a date after today, within the calendar."
    if slot not in TIME_SLOTS:
        return "Choose a time."
    if preferred_date.isoformat() in set(blackouts):
        return "That date is unavailable. Choose another day."
    if slot_taken(bookings, preferred_date, slot):
        return "That time is already booked. Choose an open slot above."
    return None


def inject_css() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&display=swap');

            html, body, [class*="css"] {
                font-family: "Manrope", "Helvetica Neue", Helvetica, Arial, sans-serif;
            }

            .stApp,
            [data-testid="stAppViewContainer"],
            [data-testid="stMain"] {
                background: #ffffff !important;
                color: #2a2a2a;
            }

            header[data-testid="stHeader"],
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stHeaderActionElements"],
            [data-testid="stSidebar"],
            #MainMenu,
            footer {
                display: none !important;
            }

            .block-container {
                max-width: 680px;
                padding-top: 4.5rem;
                padding-bottom: 5.5rem;
            }

            .page-intro {
                padding-bottom: 8px;
                border-bottom: 2px solid #ececec;
            }

            .page-intro.is-staff {
                border-bottom-color: #d7e0d3;
            }

            .page-intro.is-mason {
                border-bottom-color: #3d5636;
            }

            .page-intro.is-luke {
                border-bottom-color: #2e424e;
            }

            .page-intro.is-noah {
                border-bottom-color: #8a7a62;
            }

            .page-intro.is-chase {
                border-bottom-color: #5c5346;
            }

            .page-intro.is-completed {
                border-bottom-color: #c8c8c8;
            }

            .eyebrow {
                margin: 0 0 14px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                color: #3d5636;
            }

            .brand,
            .brand span {
                margin: 0;
                font-size: clamp(36px, 6vw, 48px);
                font-weight: 500;
                letter-spacing: -0.03em;
                line-height: 1.05;
                color: #2a2a2a !important;
            }

            .tagline {
                margin: 16px 0 0;
                max-width: 42ch;
                font-size: 18px;
                line-height: 1.5;
                color: #555555;
            }

            .section-label {
                margin: 80px 0 12px;
                padding-top: 32px;
                border-top: 1px solid #e6e6e6;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.18em;
                text-transform: uppercase;
                color: #8a8a8a;
            }

            .section-note {
                margin: 0 0 22px;
                max-width: 54ch;
                font-size: 15px;
                line-height: 1.6;
                color: #666666;
            }

            .group-heading + .section-note {
                margin: 12px 2px 18px;
            }

            .service {
                padding: 22px 0;
                border-bottom: 1px solid #e6e6e6;
            }

            .service h3,
            .service h3 span {
                margin: 0 0 6px;
                font-size: 20px;
                font-weight: 500;
                letter-spacing: -0.02em;
                color: #2a2a2a !important;
            }

            .service p {
                margin: 0;
                max-width: 62ch;
                font-size: 16px;
                line-height: 1.55;
                color: #555555;
            }

            .calendar {
                margin-top: 4px;
            }

            .cal-day {
                display: grid;
                grid-template-columns: 1fr;
                gap: 8px;
                padding: 18px 0 14px;
                border-bottom: 1px solid #eeeeee;
            }

            .cal-date {
                margin: 0;
                font-size: 16px;
                font-weight: 500;
                letter-spacing: -0.02em;
                color: #2a2a2a;
            }

            .cal-date span {
                display: block;
                margin-top: 3px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .slot-list {
                display: flex;
                flex-wrap: wrap;
                gap: 6px 20px;
                list-style: none;
                margin: 0;
                padding: 2px 0 0;
            }

            .slot-row {
                display: flex;
                flex-direction: row;
                align-items: baseline;
                gap: 8px;
                padding: 0;
                font-size: 14px;
                white-space: nowrap;
            }

            .slot-row .when,
            .slot-row .status {
                white-space: nowrap;
            }

            .slot-row .when {
                color: #2a2a2a;
            }

            .slot-row.is-open .status {
                color: #3d5636;
            }

            .slot-row.is-taken .when,
            .slot-row.is-taken .status,
            .slot-row.is-closed .when,
            .slot-row.is-closed .status {
                color: #a8a8a8;
            }

            .summary {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 12px;
                margin: 32px 0 8px;
            }

            .summary-item {
                margin: 0;
                padding: 16px 14px 14px;
                border: 1px solid #eeeeee;
                border-radius: 2px;
                background: #fafafa;
            }

            .summary-item span {
                display: block;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .summary-item strong {
                display: block;
                margin-top: 6px;
                font-size: 32px;
                font-weight: 500;
                letter-spacing: -0.03em;
                color: #2a2a2a;
            }

            .summary-caption {
                margin: 28px 0 0;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .summary-workers {
                margin-top: 10px;
                grid-template-columns: repeat(4, minmax(0, 1fr));
            }

            .summary-single {
                grid-template-columns: minmax(0, 180px);
            }

            .estimate-note {
                margin: 28px 0 4px;
                padding: 16px 18px;
                border: 1px solid #e6e6e6;
                border-left: 3px solid #3d5636;
                border-radius: 2px;
                background: #fafafa;
                font-size: 15px;
                line-height: 1.6;
                color: #2a2a2a;
            }

            .estimate-note a {
                color: #2a2a2a;
                text-decoration: none;
                border-bottom: 1px solid #cfcfcf;
                white-space: nowrap;
            }

            .estimate-note a:hover {
                color: #3d5636;
                border-bottom-color: #3d5636;
            }

            .summary-item.is-waiting strong {
                color: #8a5a12;
            }

            .group-heading {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 16px;
                margin: 40px 0 0;
                padding: 16px 16px 14px;
                border: 1px solid #ececec;
                border-radius: 2px;
                background: #f7f7f7;
                font-size: 13px;
                font-weight: 600;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                color: #555555;
            }

            .group-heading span {
                min-width: 1.75em;
                padding: 3px 8px;
                border-radius: 2px;
                background: #ffffff;
                letter-spacing: 0.04em;
                text-align: center;
                color: #2a2a2a;
            }

            .group-heading.is-pending {
                color: #6f675e;
                background: #f6f5f3;
                border-color: #e8e4de;
            }

            .group-heading.is-accepted {
                color: #3d5636;
                background: #f3f6f1;
                border-color: #e0e8dc;
            }

            .group-heading.is-claimed {
                color: #2e424e;
                background: #f2f5f6;
                border-color: #e0e6e8;
            }

            .group-heading.is-completed,
            .group-heading.is-filter,
            .group-heading.is-blackout {
                color: #777777;
                background: #f7f7f7;
                border-color: #ececec;
            }

            .group-heading.is-declined {
                color: #6b3a32;
                background: #faf6f4;
                border-color: #f0e4e0;
            }

            .empty-group,
            .filter-note,
            .blackout-line {
                margin: 14px 0 8px;
                font-size: 15px;
                line-height: 1.5;
                color: #888888;
            }

            .empty-group {
                padding: 16px;
                border: 1px dashed #e4e4e4;
                border-radius: 2px;
                background: #fcfcfc;
            }

            .blackout-line {
                margin-top: 16px;
                color: #2a2a2a;
            }

            .filter-note {
                margin-top: 8px;
            }

            .booking {
                margin: 16px 0 20px;
                padding: 18px 18px 8px;
                border: 1px solid #e8e8e8;
                border-left: 3px solid #d9d9d9;
                border-radius: 2px;
                background: #ffffff;
            }

            .booking.is-pending {
                border-color: #e7e3dc;
                border-left-color: #c8c2b8;
                background: #fcfbfa;
            }

            .booking.is-accepted {
                border-color: #e0e8dc;
                border-left-color: #3d5636;
                background: #fbfcfb;
            }

            .booking.is-claimed {
                border-color: #dde4e6;
                border-left-color: #2e424e;
                background: #fbfcfc;
            }

            .booking.is-completed {
                border-color: #e8e8e8;
                border-left-color: #c8c8c8;
                background: #fafafa;
            }

            .booking.is-declined {
                border-color: #efe4e1;
                border-left-color: #c9b2ac;
                background: #fdfbfb;
            }

            .booking dl,
            .confirm-details {
                margin: 0;
            }

            .booking-status {
                display: inline-block;
                margin: 0 0 14px;
                padding: 4px 9px;
                border-radius: 2px;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.14em;
                text-transform: uppercase;
            }

            .booking-status.is-pending {
                background: #f1efec;
                color: #6f675e;
            }

            .booking-status.is-accepted {
                background: #e7efe3;
                color: #3d5636;
            }

            .booking-status.is-claimed {
                background: #e4eeea;
                color: #2e424e;
            }

            .booking-status.is-completed {
                background: #f0f0f0;
                color: #777777;
            }

            .booking-status.is-declined {
                background: #f6eeeb;
                color: #6b3a32;
            }

            .booking-claimer {
                margin: 0 0 10px;
                font-size: 16px;
                font-weight: 500;
                letter-spacing: -0.02em;
                color: #2e424e;
            }

            .confirm-prompt {
                margin: 14px 0 4px;
                font-size: 15px;
                line-height: 1.5;
                color: #6b3a32;
            }

            .st-key-view-switch {
                margin: 8px 0 4px;
            }

            div[data-testid="stButtonGroup"],
            div[data-testid="stButtonGroup"] [role="radiogroup"] {
                width: 100%;
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
                gap: 0 !important;
            }

            div[data-testid="stButtonGroup"] button {
                flex: 1 1 0;
                background: #ffffff !important;
                background-color: #ffffff !important;
                color: #888888 !important;
                border: none !important;
                border-bottom: 2px solid #e6e6e6 !important;
                border-radius: 0 !important;
                box-shadow: none !important;
                padding: 10px 4px 12px !important;
            }

            div[data-testid="stButtonGroup"] button p {
                color: #888888 !important;
                font-weight: 500 !important;
            }

            div[data-testid="stButtonGroup"] button[aria-checked="true"] {
                background: #ffffff !important;
                background-color: #ffffff !important;
                color: #2a2a2a !important;
                border-bottom: 2px solid #3d5636 !important;
            }

            div[data-testid="stButtonGroup"] button[aria-checked="true"] p {
                color: #2a2a2a !important;
            }

            .confirm-label {
                margin: 32px 0 8px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .confirm-note {
                margin: 0 0 16px;
                max-width: 46ch;
                font-size: 15px;
                line-height: 1.55;
                color: #555555;
            }

            .copy-field {
                display: block;
                margin: 0 0 12px;
            }

            .copy-field span {
                display: block;
                margin-bottom: 6px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            input.email-subject-copy,
            textarea.email-copy {
                display: block;
                width: 100%;
                box-sizing: border-box;
                margin: 0;
                padding: 14px 16px;
                border: none;
                border-radius: 2px;
                background: #f6f6f4;
                font-family: "Manrope", "Helvetica Neue", Helvetica, Arial, sans-serif;
                font-size: 15px;
                line-height: 1.55;
                color: #2a2a2a;
            }

            input.email-subject-copy {
                margin-bottom: 12px;
            }

            textarea.email-copy {
                min-height: 380px;
                resize: vertical;
            }

            textarea.email-copy.is-compact {
                min-height: 220px;
            }

            .booking input.email-subject-copy,
            .booking textarea.email-copy {
                background: #ffffff;
            }

            div[data-testid="stForm"] {
                border: none;
                padding: 8px 0 0;
            }

            div[data-testid="stForm"] label,
            [data-testid="stWidgetLabel"] p {
                font-size: 13px;
                font-weight: 500;
                color: #444444;
            }

            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stDateInputField"],
            [data-testid="stSelectbox"] div:has(> input) {
                background: transparent !important;
                border: none !important;
                border-bottom: 1px solid #d5d5d5 !important;
                border-radius: 0 !important;
                box-shadow: none !important;
            }

            [data-testid="stTextInputRootElement"]:focus-within,
            [data-testid="stTextAreaRootElement"]:focus-within,
            [data-testid="stDateInputField"]:focus-within,
            [data-testid="stSelectbox"] div:has(> input):focus-within {
                border-bottom-color: #3d5636 !important;
            }

            [data-testid="stTextInputRootElement"] input,
            [data-testid="stTextAreaRootElement"] textarea,
            [data-testid="stDateInputField"] input {
                background: transparent !important;
                color: #2a2a2a !important;
                -webkit-text-fill-color: #2a2a2a;
                caret-color: #2a2a2a;
            }

            [data-testid="stTextInputRootElement"] input::placeholder,
            [data-testid="stTextAreaRootElement"] textarea::placeholder {
                color: #a3a3a3 !important;
                -webkit-text-fill-color: #a3a3a3;
            }

            [data-testid="stSelectbox"] svg,
            [data-testid="stDateInputField"] svg {
                fill: #2a2a2a;
            }

            [data-testid="stDateInputField"] span {
                color: #2a2a2a !important;
                -webkit-text-fill-color: #2a2a2a !important;
            }

            [data-testid="stCheckbox"] {
                margin: 2px 0 8px;
            }

            [data-testid="stCheckbox"] label p {
                font-size: 14px !important;
                font-weight: 500;
                color: #444444 !important;
            }

            [data-testid="stElementContainer"]:has([data-testid="stBaseButton-primary"]),
            [data-testid="stElementContainer"]:has([data-testid="stBaseButton-secondary"]),
            [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]),
            [data-testid="stButton"]:has([data-testid="stBaseButton-primary"]),
            [data-testid="stButton"]:has([data-testid="stBaseButton-secondary"]),
            [data-testid="stFormSubmitButton"] {
                width: 100% !important;
            }

            [data-testid="stFormSubmitButton"] button,
            [data-testid="stBaseButton-primary"],
            [data-testid="stBaseLinkButton-primary"] {
                width: 100% !important;
                min-height: 44px;
                margin-top: 4px;
                padding: 0.7rem 1.35rem;
                border: none !important;
                border-radius: 2px !important;
                background: #3d5636 !important;
                color: #ffffff !important;
                font-weight: 600;
                letter-spacing: 0.04em;
                text-decoration: none !important;
            }

            [data-testid="stFormSubmitButton"] button p,
            [data-testid="stBaseButton-primary"] p,
            [data-testid="stBaseLinkButton-primary"] p {
                color: #ffffff !important;
            }

            [data-testid="stFormSubmitButton"] button:hover,
            [data-testid="stBaseButton-primary"]:hover,
            [data-testid="stBaseLinkButton-primary"]:hover {
                border: none !important;
                background: #2e424e !important;
                color: #ffffff !important;
            }

            [data-testid="stBaseButton-secondary"] {
                width: 100% !important;
                min-height: 44px;
                margin-top: 4px;
                padding: 0.7rem 1.35rem;
                border: 1px solid #e0d0cb !important;
                border-radius: 2px !important;
                background: #fffafa !important;
                color: #6b3a32 !important;
                font-weight: 600;
                letter-spacing: 0.04em;
            }

            [data-testid="stBaseButton-secondary"] p,
            [data-testid="stBaseButton-secondary"]:hover p {
                color: #6b3a32 !important;
            }

            [data-testid="stBaseButton-secondary"]:hover {
                border-color: #6b3a32 !important;
                background: #faf6f4 !important;
                color: #6b3a32 !important;
            }

            [data-testid="stBaseButton-tertiary"] {
                height: auto !important;
                min-height: 0 !important;
                margin: 0 16px 0 0;
                padding: 0 0 2px !important;
                border: none !important;
                border-bottom: 1px solid #dddddd !important;
                border-radius: 0 !important;
                background: transparent !important;
                color: #2a2a2a !important;
                font-weight: 500;
            }

            [data-testid="stBaseButton-tertiary"] p {
                color: inherit !important;
            }

            [data-testid="stBaseButton-tertiary"]:hover {
                background: transparent !important;
                color: #3d5636 !important;
                border-bottom-color: #3d5636 !important;
            }

            .form-success,
            .form-error {
                margin: 16px 0 0;
                padding: 12px 14px;
                border-radius: 2px;
                font-size: 15px;
                line-height: 1.5;
            }

            .form-success {
                background: #f3f6f1;
                color: #2e424e;
            }

            .form-error {
                background: #faf6f4;
                color: #6b3a32;
            }

            .contact-row {
                display: grid;
                grid-template-columns: 108px 1fr;
                gap: 14px;
                padding: 11px 0;
                border-bottom: 1px solid #f0f0f0;
            }

            .booking .contact-row:last-child {
                border-bottom: none;
            }

            .contact-row dt {
                margin: 0;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .contact-row dd {
                margin: 0;
                font-size: 16px;
                overflow-wrap: anywhere;
            }

            .booking .contact-row dd {
                white-space: pre-wrap;
            }

            .contact-row a {
                color: #2a2a2a;
                text-decoration: none;
                border-bottom: 1px solid #dddddd;
            }

            .contact-row a:hover {
                color: #3d5636;
                border-bottom-color: #3d5636;
            }

            .fine-print {
                margin: 48px 0 0;
                font-size: 13px;
                color: #a8a8a8;
            }

            @media (max-width: 560px) {
                .block-container {
                    padding-top: 2.75rem;
                    padding-left: 1.1rem;
                    padding-right: 1.1rem;
                }

                .brand,
                .brand span {
                    font-size: 34px;
                }

                .tagline,
                .section-note,
                .service p {
                    font-size: 16px;
                }

                .summary,
                .summary-workers {
                    grid-template-columns: 1fr 1fr;
                    gap: 8px;
                }

                .group-heading {
                    margin-top: 32px;
                    padding: 14px 12px;
                }

                .booking {
                    padding: 16px 14px 6px;
                }

                .contact-row {
                    grid-template-columns: 1fr;
                    gap: 2px;
                    padding: 10px 0;
                }

                .slot-row {
                    font-size: 15px;
                }
            }

            @media (min-width: 720px) {
                .cal-day {
                    grid-template-columns: 132px 1fr;
                    column-gap: 24px;
                    align-items: start;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_public(
    today: date,
    bookings: list[dict],
    blackouts: list[str],
    store_error: str | None,
) -> None:
    notice = st.session_state.pop("booking_saved", None)
    generation = st.session_state.form_gen
    first_day, last_day = calendar_bounds(today)
    default_day = first_open_day(today, blackouts)

    st.markdown(
        """
        <p class="eyebrow">Mobile detailing and power washing</p>
        <h1 class="brand">ProWash &amp; Detail Co.</h1>
        <p class="tagline">A careful, unhurried clean for your vehicle, home, and property.</p>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<p class="section-label">Services</p>', unsafe_allow_html=True)
    for title, description in SERVICES:
        st.markdown(
            f'<div class="service"><h3>{esc(title)}</h3><p>{esc(description)}</p></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<p class="estimate-note">Pricing depends on size, condition, and other factors. '
        f'For an estimate, call or text <a href="tel:{CONTACT_PHONE_TEL}">{CONTACT_PHONE}</a> '
        f'or email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<p class="section-label">Calendar</p>', unsafe_allow_html=True)
    st.markdown(
        "<p class=\"section-note\">The next 14 days, starting tomorrow. "
        "Booked and unavailable times can’t be requested. Names and job details stay private.</p>",
        unsafe_allow_html=True,
    )
    if store_error:
        render_message("error", store_error)
    else:
        st.markdown(calendar_markup(today, bookings, blackouts), unsafe_allow_html=True)

    st.markdown('<p class="section-label">Book</p>', unsafe_allow_html=True)
    st.markdown(
        "<p class=\"section-note\">Choose an open time, then share a few details. "
        "We’ll confirm by phone or email.</p>",
        unsafe_allow_html=True,
    )

    with st.form("booking", clear_on_submit=False):
        name = st.text_input("Name", key=f"name-{generation}")
        phone = st.text_input("Phone", key=f"phone-{generation}")
        email = st.text_input("Email", key=f"email-{generation}")
        address = st.text_input("Address", key=f"address-{generation}")
        service = st.selectbox(
            "Service",
            SERVICE_NAMES,
            index=None,
            placeholder="Select a service",
            key=f"service-{generation}",
        )
        preferred_date = st.date_input(
            "Preferred date",
            value=default_day,
            min_value=first_day,
            max_value=last_day,
            format="MM/DD/YYYY",
            key=f"date-{generation}",
        )
        slot = st.selectbox(
            "Time",
            TIME_SLOTS,
            index=None,
            placeholder="Select a time",
            key=f"time-{generation}",
        )
        notes = st.text_area(
            "Notes",
            placeholder="Gate code, vehicle, or anything we should know",
            key=f"notes-{generation}",
        )
        submitted = st.form_submit_button("Book a Service", type="primary")

    error = None
    if submitted:
        if store_error:
            error = store_error
        elif not isinstance(preferred_date, date):
            error = "Choose a date after today, within the calendar."
        else:
            error = validate_booking(
                name,
                phone,
                email,
                address,
                service,
                preferred_date,
                slot,
                today,
                bookings,
                blackouts,
            )
        if error is None and isinstance(preferred_date, date) and slot is not None:
            record = {
                "name": name.strip(),
                "phone": phone.strip(),
                "email": email.strip(),
                "address": address.strip(),
                "service": service,
                "date": preferred_date.isoformat(),
                "time": slot,
                "notes": notes.strip(),
            }
            try:
                add_booking(record)
            except DateClosed:
                error = "That date is unavailable. Choose another day."
            except SlotTaken:
                error = "That time is already booked. Choose an open slot above."
            except BookingStoreError:
                error = "That request could not be saved."
            else:
                when = f"{format_long_date(record['date'])} at {record['time']}"
                st.session_state.booking_saved = (
                    f"Request received for {when}. "
                    "We’ll confirm your appointment by phone or email."
                )
                st.session_state.form_gen += 1
                st.rerun()

    if error:
        render_message("error", error)
    elif notice:
        render_message("success", notice)

    st.markdown('<p class="section-label">Contact</p>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <dl>
            <div class="contact-row">
                <dt>Phone</dt>
                <dd><a href="tel:+19259156541">(925) 915-6541</a></dd>
            </div>
            <div class="contact-row">
                <dt>Instagram</dt>
                <dd><a href="https://instagram.com/prowash.detail.co" target="_blank" rel="noopener noreferrer">@prowash.detail.co</a></dd>
            </div>
            <div class="contact-row">
                <dt>Email</dt>
                <dd><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></dd>
            </div>
        </dl>
        <p class="fine-print">ProWash &amp; Detail Co. · Mobile detailing and power washing</p>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<p class="section-label">Staff</p>', unsafe_allow_html=True)
    if st.session_state.admin:
        st.markdown(
            '<p class="section-note">You are signed in. Names, shifts, and blackout dates stay on the staff pages.</p>',
            unsafe_allow_html=True,
        )
        staff_label = "View appointments"
    else:
        st.markdown(
            '<p class="section-note">Sign in on a separate page to see names, claim shifts, and each worker’s schedule.</p>',
            unsafe_allow_html=True,
        )
        staff_label = "Staff sign in"
    if st.button(staff_label, type="tertiary", key="open-staff"):
        enter_staff()


def accept_request(booking_id: str) -> None:
    try:
        accepted = accept_booking(booking_id)
    except DateClosed:
        st.session_state.accept_notice = None
        st.session_state.accept_error = (
            "That date is blocked. Remove the blackout, or decline the request."
        )
        clear_action_messages()
    except SlotTaken:
        st.session_state.accept_notice = None
        st.session_state.accept_error = "That time is already accepted for another booking."
        clear_action_messages()
    except BookingStoreError as exc:
        st.session_state.accept_notice = None
        st.session_state.accept_error = str(exc)
        clear_action_messages()
    else:
        st.session_state.accept_notice = accepted
        st.session_state.accept_error = None
        clear_action_messages()
    st.rerun()


def decline_request(booking_id: str) -> None:
    try:
        record = decline_booking(booking_id)
    except BookingStoreError as exc:
        clear_accept_panel()
        st.session_state.action_notice = None
        st.session_state.action_error = str(exc)
    else:
        name, _service, when_date, when_time = job_when(record)
        clear_accept_panel()
        st.session_state.action_error = None
        st.session_state.action_notice = (
            f"Declined {name}’s request for {when_date} at {when_time}. That time is open."
        )
    st.rerun()


def complete_request(booking_id: str) -> None:
    try:
        record = complete_booking(booking_id)
    except BookingStoreError as exc:
        clear_accept_panel()
        st.session_state.action_notice = None
        st.session_state.action_error = str(exc)
    else:
        name, service, when_date, _when_time = job_when(record)
        clear_accept_panel()
        st.session_state.action_error = None
        st.session_state.action_notice = (
            f"Completed. {name}’s {service} on {when_date} is in the completed section, and that time is open."
        )
    st.rerun()


def render_confirmation_toggle(record: dict, pending: dict[str, bool]) -> None:
    booking_id = str(record.get("id") or "")
    if not booking_id:
        return
    current = bool(record.get("customer_confirmed"))
    key = f"confirmed-{booking_id}"
    if key not in st.session_state:
        st.session_state[key] = current
    checked = st.checkbox("Customer confirmed", key=key)
    if checked != current:
        pending[booking_id] = checked


def render_claim_form(record: dict) -> None:
    booking_id = str(record.get("id") or "")
    with st.form(f"claim-{booking_id}", clear_on_submit=False):
        worker_name = st.selectbox("Worker", list(WORKERS), key=f"worker-{booking_id}")
        submitted = st.form_submit_button("Claim shift", type="primary")
    if not submitted:
        return
    try:
        claimed = claim_booking(booking_id, str(worker_name))
    except BookingStoreError as exc:
        clear_accept_panel()
        st.session_state.action_notice = None
        st.session_state.action_error = str(exc)
    else:
        who = str(claimed.get("claimed_by") or "").strip()
        _name, service, when_date, when_time = job_when(claimed)
        clear_accept_panel()
        st.session_state.action_error = None
        st.session_state.pending_decline = None
        st.session_state.action_notice = (
            f"Claimed. {who} has {service} on {when_date} at {when_time}."
        )
    st.rerun()


def render_pending_actions(record: dict) -> None:
    booking_id = str(record.get("id") or "")
    if st.session_state.get("pending_decline") == booking_id:
        st.markdown(
            '<p class="confirm-prompt">Decline this request? The time stays open.</p>',
            unsafe_allow_html=True,
        )
        keep_col, decline_col = st.columns(2)
        with keep_col:
            if st.button("Keep request", type="tertiary", key=f"keep-{booking_id}"):
                st.session_state.pending_decline = None
                st.rerun()
        with decline_col:
            if st.button("Confirm decline", type="secondary", key=f"confirm-decline-{booking_id}"):
                st.session_state.pending_decline = None
                decline_request(booking_id)
        return
    accept_col, decline_col = st.columns(2)
    with accept_col:
        if st.button("Accept", type="primary", key=f"accept-{booking_id}"):
            st.session_state.pending_decline = None
            accept_request(booking_id)
    with decline_col:
        if st.button("Decline", type="secondary", key=f"decline-{booking_id}"):
            st.session_state.pending_decline = booking_id
            clear_accept_panel()
            clear_action_messages()
            st.rerun()


def render_staff_actions(record: dict, section: str) -> None:
    booking_id = str(record.get("id") or "")
    if not booking_id:
        return
    if section == "pending":
        render_pending_actions(record)
        return
    if section == "accepted":
        render_claim_form(record)
    if section in {"accepted", "claimed"}:
        if st.button("Mark completed", type="primary", key=f"complete-{booking_id}"):
            st.session_state.pending_decline = None
            complete_request(booking_id)


def render_booking_group(
    title: str,
    status: str,
    note: str,
    empty: str,
    records: list[dict],
    pending_confirmations: dict[str, bool],
) -> None:
    st.markdown(
        f'<p class="group-heading is-{status}">{esc(title)}<span>{len(records)}</span></p>'
        f'<p class="section-note">{esc(note)}</p>',
        unsafe_allow_html=True,
    )
    if not records:
        st.markdown(f'<p class="empty-group">{esc(empty)}</p>', unsafe_allow_html=True)
        return
    for record in records:
        st.markdown(booking_card(record), unsafe_allow_html=True)
        render_confirmation_toggle(record, pending_confirmations)
        render_staff_actions(record, status)


def save_confirmations(pending: dict[str, bool]) -> None:
    if not pending:
        return
    try:
        for booking_id, value in pending.items():
            set_customer_confirmed(booking_id, value)
    except BookingStoreError:
        st.session_state.action_error = "That confirmation could not be saved."
        for booking_id in pending:
            st.session_state.pop(f"confirmed-{booking_id}", None)
    else:
        st.session_state.action_error = None
    st.rerun()


def render_filters(bookings: list[dict]) -> tuple[list[dict], bool]:
    st.markdown(
        '<p class="group-heading is-filter">Filter</p>'
        '<p class="section-note">Search by name, address, or notes, or narrow the list to one service or date.</p>',
        unsafe_allow_html=True,
    )
    query = st.text_input(
        "Search",
        placeholder="Name, date, service, or address",
        key="staff-search",
    )
    service_choice = st.selectbox(
        "Service",
        ["All services", *SERVICE_NAMES],
        key="staff-service",
    )
    choices = date_choices(bookings)
    labels = [label for label, _iso in choices]
    selected = st.selectbox("Date", labels, key="staff-date")
    iso_date = dict(choices)[selected]
    filtering = bool(query.strip()) or service_choice != "All services" or iso_date is not None
    matched = [
        item
        for item in bookings
        if record_matches(item, service=service_choice, iso_date=iso_date, query=query)
    ]
    if filtering:
        noun = "appointment" if len(matched) == 1 else "appointments"
        st.markdown(
            f'<p class="filter-note">{len(matched)} {noun} match.</p>',
            unsafe_allow_html=True,
        )
    return matched, filtering


def render_blackouts(blackouts: list[str], today: date) -> None:
    st.markdown(
        f'<p class="group-heading is-blackout">Blackout dates<span>{len(blackouts)}</span></p>'
        '<p class="section-note">These days do not appear as available on the public calendar. '
        "Jobs already accepted stay on the books.</p>",
        unsafe_allow_html=True,
    )
    latest = today + timedelta(days=BLACKOUT_HORIZON_DAYS)
    default_day = today if today == latest else min(today + timedelta(days=1), latest)
    with st.form("add-blackout", clear_on_submit=False):
        chosen = st.date_input(
            "Blackout date",
            value=default_day,
            min_value=today,
            max_value=latest,
            format="MM/DD/YYYY",
            key="blackout-date",
        )
        submitted = st.form_submit_button("Add blackout", type="primary")
    if submitted:
        if not isinstance(chosen, date):
            clear_accept_panel()
            st.session_state.action_notice = None
            st.session_state.action_error = "Choose a valid date."
            st.rerun()
        try:
            add_blackout(chosen.isoformat())
        except BookingStoreError as exc:
            clear_accept_panel()
            st.session_state.action_notice = None
            st.session_state.action_error = str(exc)
        else:
            clear_accept_panel()
            st.session_state.action_error = None
            st.session_state.action_notice = (
                f"{format_long_date(chosen.isoformat())} is blocked. It will not show as available."
            )
        st.rerun()

    if not blackouts:
        st.markdown(
            '<p class="empty-group">No blackout dates. Open days on the public calendar can be requested.</p>',
            unsafe_allow_html=True,
        )
        return
    for iso_date in blackouts:
        st.markdown(
            f'<p class="blackout-line">{esc(format_long_date(iso_date))}</p>',
            unsafe_allow_html=True,
        )
        if st.button("Remove", type="tertiary", key=f"remove-blackout-{iso_date}"):
            try:
                remove_blackout(iso_date)
            except BookingStoreError as exc:
                clear_accept_panel()
                st.session_state.action_notice = None
                st.session_state.action_error = str(exc)
            else:
                clear_accept_panel()
                st.session_state.action_error = None
                st.session_state.action_notice = (
                    f"Blackout removed for {format_long_date(iso_date)}."
                )
            st.rerun()


def render_page_intro(
    heading: str,
    tagline: str,
    *,
    eyebrow: str = "Staff",
    tone: str = "staff",
) -> None:
    st.markdown(
        f"""
        <div class="page-intro is-{esc(tone)}">
        <p class="eyebrow">{esc(eyebrow)}</p>
        <h1 class="brand">{esc(heading)}</h1>
        <p class="tagline">{esc(tagline)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


VIEW_OPTIONS = (
    (STAFF_VIEW, "Staff"),
    *((name.casefold(), name) for name in WORKERS),
    (COMPLETED_VIEW, "Completed"),
)


def view_label(view: str) -> str:
    for key, label in VIEW_OPTIONS:
        if key == view:
            return label
    return "Staff"


def render_view_switcher(active: str) -> None:
    labels = [label for _view, label in VIEW_OPTIONS]
    by_label = {label: view for view, label in VIEW_OPTIONS}
    if st.session_state.get("view-switch") not in labels:
        st.session_state["view-switch"] = view_label(active)
    selected = st.segmented_control(
        "Schedule",
        labels,
        key="view-switch",
        label_visibility="collapsed",
        required=True,
        width="stretch",
        wrap=True,
    )
    if isinstance(selected, list):
        selected = selected[0] if selected else None
    chosen = by_label.get(selected) if isinstance(selected, str) else None
    if chosen and chosen != active:
        enter_view(chosen)


def render_nav(active: str, signed_in: bool) -> None:
    if signed_in:
        render_view_switcher(active)
    if st.button("Public site", type="tertiary", key=f"back-public-{active}"):
        leave_staff()
    if signed_in and st.button("Sign out", type="tertiary", key=f"sign-out-{active}"):
        sign_out()


def render_login() -> None:
    with st.form("staff-login", clear_on_submit=False):
        email = st.text_input("Email", key="staff-email")
        password = st.text_input("Password", type="password", key="staff-password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if credentials_ok(email, password):
            st.session_state.admin = True
            st.rerun()
        render_message("error", "That email or password is incorrect.")


def render_staff(
    today: date,
    bookings: list[dict],
    blackouts: list[str],
    store_error: str | None,
) -> None:
    signed_in = bool(st.session_state.admin)
    if signed_in:
        heading = "Appointments"
        tagline = (
            "Pending requests are waiting for a yes. "
            "Accepted and claimed times show as booked on the public calendar."
        )
    else:
        heading = "Sign in"
        tagline = "This page is separate from the public site. Visitors never see this list."

    render_page_intro(heading, tagline, tone="staff")
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    render_nav(STAFF_VIEW, signed_in)
    if not signed_in:
        render_login()
        return
    if store_error:
        render_message("error", store_error)
        return

    today_count, week_count, unclaimed = job_counts(bookings, today)
    claimed_week = worker_week_counts(bookings, today)
    st.markdown(
        summary_markup(today_count, week_count, unclaimed)
        + worker_summary_markup(claimed_week),
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class=\"section-note\">Today and this week, Monday through Sunday, "
        "count accepted, claimed, and completed jobs. Unclaimed is every accepted job still waiting for a worker. "
        "Claimed this week counts jobs Mason, Luke, Noah, and Chase have taken.</p>",
        unsafe_allow_html=True,
    )
    render_notices()
    render_blackouts(blackouts, today)
    filtered, filtering = render_filters(bookings)
    ordered = sorted(filtered, key=booking_sort_key)
    pending_confirmations: dict[str, bool] = {}
    shown = False
    for status, title, note, empty in SECTIONS:
        records = [item for item in ordered if booking_section(item) == status]
        if filtering and not records:
            continue
        shown = True
        render_booking_group(title, status, note, empty, records, pending_confirmations)
    if filtering and not shown:
        st.markdown(
            '<p class="empty-group">No appointments match.</p>',
            unsafe_allow_html=True,
        )
    save_confirmations(pending_confirmations)


def render_worker_group(title: str, status: str, note: str, empty: str, records: list[dict]) -> None:
    st.markdown(
        f'<p class="group-heading is-{status}">{esc(title)}<span>{len(records)}</span></p>'
        f'<p class="section-note">{esc(note)}</p>',
        unsafe_allow_html=True,
    )
    if not records:
        st.markdown(f'<p class="empty-group">{esc(empty)}</p>', unsafe_allow_html=True)


def worker_from_view(view: str) -> str:
    for name in WORKERS:
        if name.casefold() == view:
            return name
    return WORKERS[0]


def render_completed(
    bookings: list[dict],
    store_error: str | None,
) -> None:
    signed_in = bool(st.session_state.admin)
    if signed_in:
        heading = "Completed"
        tagline = "Finished jobs. The time is open on the public calendar again."
        eyebrow = "Archive"
    else:
        heading = "Sign in"
        tagline = "This page is separate from the public site. Visitors never see job details."
        eyebrow = "Staff"

    render_page_intro(heading, tagline, eyebrow=eyebrow, tone="completed" if signed_in else "staff")
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    render_nav(COMPLETED_VIEW, signed_in)
    if not signed_in:
        render_login()
        return
    if store_error:
        render_message("error", store_error)
        return

    render_notices(include_accept=False)
    finished = sorted(
        [item for item in bookings if booking_status(item) == "completed"],
        key=booking_sort_key,
    )
    st.markdown(
        '<div class="summary summary-single">'
        f'<div class="summary-item"><span>Completed</span><strong>{len(finished)}</strong></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    render_worker_group(
        "Completed",
        "completed",
        "Service, date, worker, and address for every finished job.",
        "No completed jobs yet.",
        finished,
    )
    for record in finished:
        st.markdown(completed_card(record), unsafe_allow_html=True)


def render_worker_schedule(
    worker: str,
    today: date,
    bookings: list[dict],
    store_error: str | None,
) -> None:
    signed_in = bool(st.session_state.admin)
    if signed_in:
        heading = f"{worker}’s jobs"
        tagline = "Your claimed jobs. Upcoming shifts are first, then finished ones."
        eyebrow = "Schedule"
    else:
        heading = "Sign in"
        tagline = "This page is separate from the public site. Visitors never see shift details."
        eyebrow = "Staff"

    render_page_intro(
        heading,
        tagline,
        eyebrow=eyebrow,
        tone=worker.casefold() if signed_in else "staff",
    )
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    render_nav(worker.casefold(), signed_in)
    if not signed_in:
        render_login()
        return
    if store_error:
        render_message("error", store_error)
        return

    render_notices(include_accept=False)
    mine = [
        item
        for item in bookings
        if canonical_worker(item.get("claimed_by")) == worker
        and booking_status(item) in {"claimed", "completed"}
    ]
    ordered = sorted(mine, key=booking_sort_key)
    upcoming = [item for item in ordered if booking_status(item) == "claimed"]
    finished = [item for item in ordered if booking_status(item) == "completed"]
    week_count = worker_week_counts(bookings, today)[worker]
    st.markdown(
        '<div class="summary">'
        f'<div class="summary-item"><span>Upcoming</span><strong>{len(upcoming)}</strong></div>'
        f'<div class="summary-item"><span>This week</span><strong>{week_count}</strong></div>'
        f'<div class="summary-item"><span>Completed</span><strong>{len(finished)}</strong></div>'
        "</div>"
        "<p class=\"section-note\">This week is Monday through Sunday and includes finished jobs you claimed.</p>",
        unsafe_allow_html=True,
    )
    render_worker_group(
        "Upcoming",
        "claimed",
        "Claimed jobs that are not finished yet.",
        "No jobs assigned yet.",
        upcoming,
    )
    for record in upcoming:
        st.markdown(schedule_card(record, "Upcoming"), unsafe_allow_html=True)
    render_worker_group(
        "Completed",
        "completed",
        "Finished jobs stay on your schedule. The time is open for a new booking.",
        "No completed jobs yet.",
        finished,
    )
    for record in finished:
        st.markdown(schedule_card(record, "Completed"), unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title="ProWash & Detail Co.",
        page_icon="✦",
        layout="centered",
    )
    inject_css()
    st.session_state.setdefault("admin", False)
    st.session_state.setdefault("form_gen", 0)
    st.session_state.setdefault("accept_notice", None)
    st.session_state.setdefault("accept_error", None)
    st.session_state.setdefault("action_notice", None)
    st.session_state.setdefault("action_error", None)
    st.session_state.setdefault("pending_decline", None)

    today = date.today()
    try:
        bookings, blackouts = load_store()
        store_error = None
    except BookingStoreError as exc:
        bookings = []
        blackouts = []
        store_error = str(exc)

    view = current_view()
    if view == COMPLETED_VIEW:
        render_completed(bookings, store_error)
    elif view in WORKER_VIEWS:
        render_worker_schedule(worker_from_view(view), today, bookings, store_error)
    elif view == STAFF_VIEW:
        render_staff(today, bookings, blackouts, store_error)
    else:
        render_public(today, bookings, blackouts, store_error)


if __name__ == "__main__":
    main()
