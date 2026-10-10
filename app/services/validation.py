"""Per-recipient validation. Never raises: problems are returned as error text."""
from dataclasses import dataclass
from typing import Any

from email_validator import EmailNotValidError, validate_email

from app.config import settings


@dataclass
class CheckedRecipient:
    name: str
    email: str
    error: str | None = None  # None means the recipient is valid


def validate_recipients(raw_recipients: list[Any]) -> list[CheckedRecipient]:
    """Check every recipient and return one result per input, in order."""
    results = []
    seen_emails = set()  # lower-cased emails already used in this request

    for raw in raw_recipients:
        if not isinstance(raw, dict):
            results.append(CheckedRecipient("", "", "recipient must be an object with name and email"))
            continue

        name = _clean(raw.get("name"))
        email = _clean(raw.get("email"))
        error = _find_error(name, email, seen_emails)
        if error is None:
            seen_emails.add(email.lower())
        results.append(CheckedRecipient(name, email, error))

    return results


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _find_error(name: str, email: str, seen_emails: set[str]) -> str | None:
    if not name:
        return "name is required"
    if len(name) > settings.max_name_length:
        return f"name is longer than {settings.max_name_length} characters"
    if not email:
        return "email is required"
    try:
        # Format check only; we don't want DNS lookups here.
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return "invalid email format"
    if email.lower() in seen_emails:
        return "duplicate email"  # the first occurrence stays valid
    return None
