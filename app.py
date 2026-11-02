import streamlit as st

st.set_page_config(
    page_title="ProWash & Detail Co.",
    page_icon="✦",
    layout="centered",
)

st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&display=swap');

        html, body, [class*="css"] {
            font-family: "Manrope", "Helvetica Neue", Helvetica, Arial, sans-serif;
        }

        .stApp {
            background: #ffffff !important;
            color: #2a2a2a;
        }

        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stHeaderActionElements"],
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

        div[data-testid="stForm"] {
            border: none;
            padding: 8px 0 0;
        }

        div[data-testid="stForm"] label {
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
        [data-testid="stForm"] textarea {
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

        [data-testid="stFormSubmitButton"] button {
            margin-top: 8px;
            padding: 0.65rem 1.35rem;
            border: none;
            border-radius: 2px;
            background: #3d5636 !important;
            color: #ffffff !important;
            font-weight: 500;
            letter-spacing: 0.04em;
        }

        [data-testid="stFormSubmitButton"] button:hover {
            border: none;
            background: #2e424e !important;
            color: #ffffff !important;
        }

        div[data-testid="stAlert"] {
            margin-top: 16px;
            border: none;
            border-radius: 2px;
            background: #f3f6f1;
            color: #2e424e;
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
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <p class="eyebrow">Mobile detailing and power washing</p>
    <h1 class="brand">ProWash &amp; Detail Co.</h1>
    <p class="tagline">A careful, unhurried clean for your vehicle, home, and property.</p>
    """,
    unsafe_allow_html=True,
)

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

st.markdown('<p class="section-label">Services</p>', unsafe_allow_html=True)

for title, description in SERVICES:
    st.markdown(
        f'<div class="service"><h3>{title}</h3><p>{description}</p></div>',
        unsafe_allow_html=True,
    )

st.markdown('<p class="section-label">Book</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="section-note">Share a few details and we’ll confirm a time by phone or email.</p>',
    unsafe_allow_html=True,
)

with st.form("booking", clear_on_submit=True):
    st.text_input("Name")
    st.text_input("Phone")
    st.text_input("Email")
    st.text_input("Address")
    st.selectbox(
        "Service",
        [
            "Car Detailing",
            "Power Washing",
            "Solar Panel Cleaning",
            "Trash Can Cleaning",
        ],
    )
    st.date_input("Preferred Date")
    st.text_area("Notes", placeholder="Gate code, vehicle, or anything we should know")
    submitted = st.form_submit_button("Book a Service")

if submitted:
    st.success("Request received. We’ll confirm your appointment by phone or email.")

st.markdown('<p class="section-label">Contact</p>', unsafe_allow_html=True)
st.markdown(
    """
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
            <dd><a href="mailto:hello@prowashdetail.co">hello@prowashdetail.co</a></dd>
        </div>
    </dl>
    <p class="fine-print">ProWash &amp; Detail Co. · Mobile detailing and power washing</p>
    """,
    unsafe_allow_html=True,
)
