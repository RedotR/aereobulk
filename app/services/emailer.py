"""Send a certificate by email through the Resend HTTP API (https://resend.com/docs/api-reference/emails/send-email)."""
import base64
import html

import httpx

from app.config import settings


def is_enabled() -> bool:
    return bool(settings.resend_api_key)


def send_certificate_email(to_email: str, name: str, event_name: str, pdf_path: str) -> None:
    """Email the PDF as an attachment. Raises on any failure; the caller records it."""
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": settings.email_from,
            "to": [to_email],
            "subject": f"Your certificate: {event_name}",
            # html.escape because name/event come from the user
            "html": f"<p>Hi {html.escape(name)},</p>"
            f"<p>Congratulations on completing <b>{html.escape(event_name)}</b>. "
            "Your certificate is attached.</p>",
            "attachments": [{"filename": "certificate.pdf", "content": pdf_b64}],
        },
        timeout=15,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Resend error {response.status_code}: {response.text[:200]}")
