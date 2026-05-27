import streamlit as st

def load_config():
    """Load credentials from Streamlit Secrets (cloud) or config.py (local)."""
    try:
        # Streamlit Cloud
        return {
            "ANTHROPIC_API_KEY": st.secrets["ANTHROPIC_API_KEY"],
            "GMAIL_ADDRESS": st.secrets["GMAIL_ADDRESS"],
            "GMAIL_APP_PASSWORD": st.secrets["GMAIL_APP_PASSWORD"],
            "KINDLE_EMAIL": st.secrets["KINDLE_EMAIL"],
        }
    except Exception:
        # Local
        from config import ANTHROPIC_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, KINDLE_EMAIL
        return {
            "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
            "GMAIL_ADDRESS": GMAIL_ADDRESS,
            "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
            "KINDLE_EMAIL": KINDLE_EMAIL,
        }
