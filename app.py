import html
import hmac
import json
import smtplib
import threading
import uuid
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import streamlit as st

DATA_PATH = Path(__file__).resolve().parent / "bookings.json"
CONTACT_EMAIL = "prowashdetailco5@gmail.com"
ADMIN_EMAIL = "chasejrose50@gmail.com"
ADMIN_PASSWORD = "1463dragon"
LOOKAHEAD_DAYS = 14
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
_LOCK = threading.Lock()


class BookingStoreError(Exception):
    """bookings.json is missing its expected shape or cannot be read."""


class SlotTaken(Exception):
    """Another booking already holds this date and time."""


def calendar_bounds(today: date) -> tuple[date, date]:
    first = today + timedelta(days=1)
    last = today + timedelta(days=LOOKAHEAD_DAYS)
    return first, last


def visible_days(today: date) -> list[date]:
    first, last = calendar_bounds(today)
    days: list[date] = []
    day = first
    while day <= last:
        days.append(day)
        day += timedelta(days=1)
    return days


def format_long_date(iso_date: str) -> str:
    try:
        day = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return iso_date or "—"
    return f"{day.strftime('%A, %B')} {day.day}, {day.year}"


def format_month_day(day: date) -> str:
    return f"{day.strftime('%B')} {day.day}"


def _read_bookings() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    try:
        raw = DATA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BookingStoreError("Saved appointments could not be read.") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BookingStoreError("Saved appointments could not be read.") from exc
    if not isinstance(data, list):
        raise BookingStoreError("Saved appointments could not be read.")
    return [item for item in data if isinstance(item, dict)]


def _write_bookings(bookings: list[dict]) -> None:
    temporary = DATA_PATH.with_name("bookings.json.tmp")
    temporary.write_text(
        json.dumps(bookings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(DATA_PATH)


def booking_status(record: dict) -> str:
    status = str(record.get("status") or "").strip().lower()
    if status == "accepted":
        return "accepted"
    return "pending"


def _stamp_records(bookings: list[dict]) -> bool:
    changed = False
    for item in bookings:
        if not str(item.get("id") or "").strip():
            item["id"] = uuid.uuid4().hex
            changed = True
        if not str(item.get("status") or "").strip():
            item["status"] = "pending"
            changed = True
    return changed


def load_bookings() -> list[dict]:
    with _LOCK:
        bookings = _read_bookings()
        if _stamp_records(bookings):
            _write_bookings(bookings)
        return bookings


def _accepted_conflict(
    bookings: list[dict],
    iso_date: str,
    slot: str,
    skip: dict | None = None,
) -> bool:
    return any(
        item is not skip
        and item.get("date") == iso_date
        and item.get("time") == slot
        and booking_status(item) == "accepted"
        for item in bookings
    )


def add_booking(record: dict) -> None:
    with _LOCK:
        bookings = _read_bookings()
        if _accepted_conflict(bookings, record["date"], record["time"]):
            raise SlotTaken()
        record["id"] = uuid.uuid4().hex
        record["status"] = "pending"
        bookings.append(record)
        _write_bookings(bookings)


def accept_booking(booking_id: str) -> dict:
    with _LOCK:
        bookings = _read_bookings()
        target = next((item for item in bookings if item.get("id") == booking_id), None)
        if target is None:
            raise BookingStoreError("That booking could not be saved.")
        if booking_status(target) != "accepted":
            if _accepted_conflict(
                bookings,
                str(target.get("date") or ""),
                str(target.get("time") or ""),
                skip=target,
            ):
                raise SlotTaken()
            target["status"] = "accepted"
            _write_bookings(bookings)
        return dict(target)


def slot_taken(bookings: list[dict], day: date, slot: str) -> bool:
    iso_date = day.isoformat()
    return _accepted_conflict(bookings, iso_date, slot)


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


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def display_value(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return esc(text) if text else "—"


def calendar_markup(today: date, bookings: list[dict]) -> str:
    days = []
    for day in visible_days(today):
        rows = []
        for slot in TIME_SLOTS:
            taken = slot_taken(bookings, day, slot)
            state = "is-taken" if taken else "is-open"
            status = "Booked" if taken else "Available"
            rows.append(
                f'<li class="slot-row {state}"><span class="when">{esc(slot)}</span>'
                f'<span class="status">{status}</span></li>'
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
    raw_date = str(record.get("date") or "")
    date_label = format_long_date(raw_date) if raw_date else "—"
    return [
        ("Name", display_value(record.get("name"))),
        ("Phone", display_value(record.get("phone"))),
        ("Email", display_value(record.get("email"))),
        ("Address", display_value(record.get("address"))),
        ("Service", display_value(record.get("service"))),
        ("Date", esc(date_label) if date_label != "—" else "—"),
        ("Time", display_value(record.get("time"))),
        ("Notes", display_value(record.get("notes"))),
    ]


def rows_markup(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f'<div class="contact-row"><dt>{label}</dt><dd>{value}</dd></div>'
        for label, value in rows
    )


def booking_card(record: dict) -> str:
    status = booking_status(record)
    label = "Accepted" if status == "accepted" else "Pending"
    return (
        '<article class="booking">'
        f'<p class="booking-status is-{status}">{label}</p>'
        f"<dl>{rows_markup(detail_rows(record))}</dl>"
        "</article>"
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


def mailto_for(record: dict) -> str:
    subject, body = confirmation_copy(record)
    email = str(record.get("email") or "").strip()
    return f"mailto:{email}?subject={quote(subject, safe='')}&body={quote(body, safe='')}"


def send_confirmation_email(record: dict) -> None:
    """Email the customer a confirmation. Raises if Gmail or the address fails."""
    recipient = str(record.get("email") or "").strip()
    if not recipient:
        raise ValueError("This booking has no email address.")
    gmail = st.secrets["gmail"]
    account = str(gmail["email"]).strip()
    password = str(gmail["app_password"]).replace(" ", "").strip()
    if not account or not password:
        raise ValueError("Gmail is not configured.")
    subject, body = confirmation_copy(record)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = CONTACT_EMAIL
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(account, password)
        smtp.send_message(message)


def render_acceptance(record: dict) -> None:
    name = str(record.get("name") or "").strip() or "This customer"
    service = str(record.get("service") or "").strip() or "the requested service"
    when_date = format_long_date(str(record.get("date") or ""))
    when_time = str(record.get("time") or "").strip()
    email = str(record.get("email") or "").strip()
    subject, body = confirmation_copy(record)
    # One HTML line, so Markdown does not split the message on blank lines.
    body_html = esc(body).replace("\r\n", "&#10;").replace("\n", "&#10;")
    render_message(
        "success",
        f"Accepted. {name} is booked for {service} on {when_date} at {when_time}.",
    )
    st.markdown(
        f'<dl class="confirm-details">{rows_markup(detail_rows(record))}</dl>'
        '<p class="confirm-label">Email to send</p>'
        f'<p class="confirm-note">Addressed to {esc(email)}. '
        "Select the message to copy it, or open it in your mail app.</p>"
        f'<p class="email-subject"><span>Subject</span>{esc(subject)}</p>'
        f'<textarea class="email-copy" readonly>{body_html}</textarea>',
        unsafe_allow_html=True,
    )
    st.link_button("Open email", mailto_for(record), type="primary")


def credentials_ok(email: str, password: str) -> bool:
    email_ok = hmac.compare_digest(email.strip().casefold(), ADMIN_EMAIL.casefold())
    password_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return email_ok and password_ok


def viewing_staff() -> bool:
    raw = st.query_params.get("view")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    return raw == STAFF_VIEW


def enter_staff() -> None:
    st.query_params["view"] = STAFF_VIEW
    st.rerun()


def leave_staff() -> None:
    if "view" in st.query_params:
        del st.query_params["view"]
    st.rerun()


def render_message(kind: str, text: str) -> None:
    st.markdown(
        f'<p class="form-{kind}">{esc(text)}</p>',
        unsafe_allow_html=True,
    )


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
                padding-bottom: 5rem;
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
                max-width: 36ch;
                font-size: 18px;
                line-height: 1.5;
                color: #555555;
            }

            .section-label {
                margin: 72px 0 8px;
                padding-top: 28px;
                border-top: 1px solid #e6e6e6;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.16em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            .section-note {
                margin: 0 0 28px;
                max-width: 42ch;
                font-size: 16px;
                line-height: 1.55;
                color: #555555;
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
            .slot-row.is-taken .status {
                color: #a8a8a8;
            }

            .booking {
                margin: 0;
                padding: 22px 0 4px;
                border-top: 1px solid #eeeeee;
            }

            .booking dl,
            .confirm-details {
                margin: 0;
            }

            .booking-status {
                margin: 0 0 2px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.14em;
                text-transform: uppercase;
            }

            .booking-status.is-pending {
                color: #a8a8a8;
            }

            .booking-status.is-accepted {
                color: #3d5636;
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

            .email-subject {
                margin: 0 0 10px;
                font-size: 16px;
                line-height: 1.45;
                color: #2a2a2a;
            }

            .email-subject span {
                display: block;
                margin-bottom: 4px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: #a8a8a8;
            }

            textarea.email-copy {
                display: block;
                width: 100%;
                box-sizing: border-box;
                min-height: 380px;
                margin: 0 0 8px;
                padding: 16px 18px;
                border: none;
                border-radius: 2px;
                background: #f6f6f4;
                resize: vertical;
                font-family: "Manrope", "Helvetica Neue", Helvetica, Arial, sans-serif;
                font-size: 15px;
                line-height: 1.55;
                color: #2a2a2a;
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

            [data-testid="stForm"] input,
            [data-testid="stForm"] textarea,
            [data-testid="stDateInputField"] input {
                background: transparent !important;
                color: #2a2a2a !important;
                -webkit-text-fill-color: #2a2a2a;
                caret-color: #2a2a2a;
            }

            [data-testid="stForm"] input::placeholder,
            [data-testid="stForm"] textarea::placeholder {
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

            [data-testid="stFormSubmitButton"] button,
            [data-testid="stBaseButton-primary"],
            [data-testid="stBaseLinkButton-primary"] {
                margin-top: 8px;
                padding: 0.65rem 1.35rem;
                border: none !important;
                border-radius: 2px !important;
                background: #3d5636 !important;
                color: #ffffff !important;
                font-weight: 500;
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
                grid-template-columns: 120px 1fr;
                gap: 12px;
                padding: 16px 0;
                border-bottom: 1px solid #eeeeee;
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


def render_public(today: date, bookings: list[dict], store_error: str | None) -> None:
    notice = st.session_state.pop("booking_saved", None)
    generation = st.session_state.form_gen
    first_day, last_day = calendar_bounds(today)

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

    st.markdown('<p class="section-label">Calendar</p>', unsafe_allow_html=True)
    st.markdown(
        "<p class=\"section-note\">The next 14 days, starting tomorrow. "
        "A time is either booked or available. Names and job details stay private.</p>",
        unsafe_allow_html=True,
    )
    if store_error:
        render_message("error", store_error)
    else:
        st.markdown(calendar_markup(today, bookings), unsafe_allow_html=True)

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
            value=first_day,
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
            '<p class="section-note">You are signed in. Appointment details stay on the staff page.</p>',
            unsafe_allow_html=True,
        )
        staff_label = "View appointments"
    else:
        st.markdown(
            '<p class="section-note">Sign in on a separate page to see names and appointment details.</p>',
            unsafe_allow_html=True,
        )
        staff_label = "Staff sign in"
    if st.button(staff_label, type="tertiary", key="open-staff"):
        enter_staff()


def render_staff(bookings: list[dict], store_error: str | None) -> None:
    signed_in = bool(st.session_state.admin)
    if signed_in:
        heading = "Appointments"
        tagline = "Accept a request to hold that time on the public calendar."
    else:
        heading = "Sign in"
        tagline = "This page is separate from the public site. Visitors never see this list."

    st.markdown(
        f"""
        <p class="eyebrow">Staff</p>
        <h1 class="brand">{heading}</h1>
        <p class="tagline">{tagline}</p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    if st.button("Public site", type="tertiary", key="back-public"):
        leave_staff()

    if not signed_in:
        with st.form("staff-login", clear_on_submit=False):
            email = st.text_input("Email", key="staff-email")
            password = st.text_input("Password", type="password", key="staff-password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            if credentials_ok(email, password):
                st.session_state.admin = True
                st.rerun()
            render_message("error", "That email or password is incorrect.")
        return

    if st.button("Sign out", type="tertiary", key="sign-out"):
        st.session_state.admin = False
        st.session_state.accept_notice = None
        st.session_state.accept_error = None
        st.session_state.accept_email_status = None
        st.rerun()

    if store_error:
        render_message("error", store_error)
        return

    notice = st.session_state.get("accept_notice")
    accept_error = st.session_state.get("accept_error")
    if isinstance(notice, dict):
        render_acceptance(notice)
        if st.session_state.get("accept_email_status") == "sent":
            sent_to = str(notice.get("email") or "").strip()
            render_message(
                "success",
                f"Confirmation email sent to {sent_to}."
                if sent_to
                else "Confirmation email sent.",
            )
        elif st.session_state.get("accept_email_status") == "failed":
            render_message(
                "error",
                "The booking was accepted, but the confirmation email could not be sent.",
            )
    if accept_error:
        render_message("error", str(accept_error))

    count = len(bookings)
    if count == 0:
        st.markdown(
            '<p class="section-note">No bookings yet. New requests from the public page will show up here.</p>',
            unsafe_allow_html=True,
        )
        return
    pending = sum(1 for item in bookings if booking_status(item) == "pending")
    noun = "booking" if count == 1 else "bookings"
    waiting = ""
    if pending:
        request_noun = "request" if pending == 1 else "requests"
        waiting = f" {pending} {request_noun} waiting to be accepted."
    st.markdown(
        f'<p class="section-note">{count} {noun} on file.{waiting}</p>',
        unsafe_allow_html=True,
    )
    for record in sorted(bookings, key=booking_sort_key):
        st.markdown(booking_card(record), unsafe_allow_html=True)
        if booking_status(record) != "pending":
            continue
        booking_id = str(record.get("id") or "")
        if not booking_id:
            continue
        if st.button("Accept", type="primary", key=f"accept-{booking_id}"):
            try:
                accepted = accept_booking(booking_id)
                st.session_state.accept_notice = accepted
                st.session_state.accept_error = None
                try:
                    send_confirmation_email(accepted)
                    st.session_state.accept_email_status = "sent"
                except Exception:
                    st.session_state.accept_email_status = "failed"
            except SlotTaken:
                st.session_state.accept_error = (
                    "That time is already accepted for another booking."
                )
            except BookingStoreError:
                st.session_state.accept_error = "That booking could not be saved."
            st.rerun()


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
    st.session_state.setdefault("accept_email_status", None)

    today = date.today()
    try:
        bookings = load_bookings()
        store_error = None
    except BookingStoreError as exc:
        bookings = []
        store_error = str(exc)

    if viewing_staff():
        render_staff(bookings, store_error)
    else:
        render_public(today, bookings, store_error)


if __name__ == "__main__":
    main()
