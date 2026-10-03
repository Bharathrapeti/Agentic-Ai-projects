"""Password hashing and registration email verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
from email.message import EmailMessage
from typing import Mapping


_PASSWORD_ROUNDS = 240_000
_OTP_LIFETIME_MINUTES = 10


def smtp_config(secrets_values: Mapping[str, object] | None = None) -> dict[str, str]:
    """Load SMTP settings from environment variables, then Streamlit secrets."""
    secrets_values = secrets_values or {}

    def setting(name: str, default: str = "") -> str:
        value = os.getenv(name)
        if value:
            return value.strip()
        secret_value = secrets_values.get(name, default)
        return str(secret_value).strip()

    config = {
        "host": setting("SMTP_HOST"),
        "port": setting("SMTP_PORT", "587"),
        "username": setting("SMTP_USERNAME"),
        "password": setting("SMTP_PASSWORD"),
        "from_email": setting("SMTP_FROM"),
    }
    if not config["from_email"]:
        config["from_email"] = config["username"]
    missing = [key for key in ("host", "username", "password", "from_email") if not config[key]]
    placeholders = [
        key for key, value in config.items()
        if value.lower() in {
            "your-gmail-address@gmail.com",
            "your-google-app-password",
            "your-email@gmail.com",
        }
    ]
    if missing:
        raise OSError(
            "Email is not configured. Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, "
            "SMTP_PASSWORD, and SMTP_FROM to .streamlit/secrets.toml, then restart Streamlit."
        )
    if placeholders:
        raise OSError(
            "SMTP configuration contains placeholders. Replace the placeholder "
            "values in .streamlit/secrets.toml with your own Gmail address and App Password."
        )
    try:
        if not 1 <= int(config["port"]) <= 65535:
            raise ValueError
    except ValueError as error:
        raise OSError("SMTP_PORT must be a valid port number, such as 587 or 465.") from error
    return config


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PASSWORD_ROUNDS
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def send_otp(*, recipient: str, code: str, smtp: dict[str, str]) -> None:
    message = EmailMessage()
    message["Subject"] = "Your Interview Coach verification code"
    message["From"] = smtp["from_email"]
    message["To"] = recipient
    message.set_content(
        f"Your Interview Coach verification code is {code}.\n\n"
        f"It expires in {_OTP_LIFETIME_MINUTES} minutes. "
        "If you did not create this account, ignore this email."
    )
    port = int(smtp.get("port", "587"))
    if port == 465:
        server_context = smtplib.SMTP_SSL(smtp["host"], port, timeout=20)
    else:
        server_context = smtplib.SMTP(smtp["host"], port, timeout=20)
    with server_context as server:
        if port != 465:
            server.starttls()
        server.login(smtp["username"], smtp["password"])
        server.send_message(message)


def send_password_reset_otp(
    *, recipient: str, username: str, code: str, smtp: dict[str, str]
) -> None:
    message = EmailMessage()
    message["Subject"] = "AI Interview Coach password reset verification"
    message["From"] = smtp["from_email"]
    message["To"] = recipient
    message.set_content(
        "AI Interview Coach\n"
        "Password Reset Verification\n\n"
        f"Hello {username},\n\n"
        "We received a request to reset the password for your account.\n\n"
        f"Username: {username}\n"
        f"Verification OTP: {code}\n\n"
        "This OTP will expire in 5 minutes.\n\n"
        "If you did not request this password reset, you can ignore this email."
    )
    port = int(smtp.get("port", "587"))
    if port == 465:
        server_context = smtplib.SMTP_SSL(smtp["host"], port, timeout=20)
    else:
        server_context = smtplib.SMTP(smtp["host"], port, timeout=20)
    with server_context as server:
        if port != 465:
            server.starttls()
        server.login(smtp["username"], smtp["password"])
        server.send_message(message)
