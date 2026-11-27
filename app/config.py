"""Configuration loaded from environment variables (and a local .env file).

Nothing secret is hard-coded here. Secrets live only in .env (local) or in the
hosting dashboard's environment variables (online).
"""
import os

try:
    # Load a local .env file if it exists (does nothing on the host if absent).
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


class Settings:
    # Empty -> use local SQLite. Otherwise a PostgreSQL connection string.
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    # Used to sign session cookies. MUST be set in production.
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-change-me")

    # Google OAuth (customers)
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    # Email OTP
    SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT = os.getenv("SMTP_PORT", "").strip()
    SMTP_USER = os.getenv("SMTP_USER", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
    EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()

    # Default hotel id used while the system is single-hotel.
    DEFAULT_HOTEL_ID = 1

    # First admin, created automatically at startup if no admin exists yet.
    # Set these in .env for the very first run, then you can leave them blank.
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # Set to 1 when serving over HTTPS (online). Keep 0 for local http dev,
    # otherwise the browser will not send the session cookie.
    COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"

    # Public base URL used inside printed QR codes, e.g. http://192.168.1.10:8000
    # or https://menu.yourhotel.com. If empty we fall back to the request host.
    BASE_URL = os.getenv("BASE_URL", "").strip()


settings = Settings()