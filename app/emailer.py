"""The daily email digest, sent over SMTP."""

import smtplib
from email.message import EmailMessage
from html import escape

from app.config import Settings
from app.schemas import DigestItem


def email_configured(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def build_digest_email(
    items: list[DigestItem], *, company_name: str, recipient: str, settings: Settings
) -> EmailMessage:
    strong = sum(item.fit == "strong" for item in items)
    message = EmailMessage()
    message["Subject"] = (
        f"{len(items)} new tender matches for {company_name}"
        + (f" ({strong} strong)" if strong else "")
    )
    message["From"] = settings.smtp_from
    message["To"] = recipient

    text_lines = [f"New tender matches for {company_name}", ""]
    html_parts = [
        f"<h2>New tender matches for {escape(company_name)}</h2>",
        "<p style='color:#5b6575'>Decision support only. Confirm every detail in the official "
        "notice before bidding.</p>",
    ]
    for item in items:
        tender = item.tender
        due = tender.response_deadline
        deadline = due.isoformat() if due else "not listed"
        link = str(tender.link) if tender.link else ""
        text_lines += [
            f"[{item.fit.upper()}] {tender.title}",
            f"  {tender.agency or 'Agency not listed'} · deadline {deadline}",
            f"  {item.summary}",
            f"  {link}",
            "",
        ]
        colour = "#17834c" if item.fit == "strong" else "#a36d00"
        title = escape(tender.title)
        html_parts.append(
            f"<div style='border-left:5px solid {colour};padding:6px 12px;margin:14px 0'>"
            f"<strong style='color:{colour}'>{item.fit.upper()}</strong> "
            + (f"<a href='{escape(link, quote=True)}'>{title}</a>" if link else title)
            + f"<div style='color:#5b6575'>{escape(tender.agency or 'Agency not listed')}"
            f" · deadline {escape(deadline)}</div>"
            f"<p>{escape(item.summary)}</p></div>"
        )
    app_url = settings.app_base_url.rstrip("/")
    text_lines.append(f"Review the checklists and give feedback: {app_url}")
    html_parts.append(
        f"<p><a href='{escape(app_url, quote=True)}'>Open the digest</a> to see each "
        "eligibility checklist and mark tenders pursue or not relevant.</p>"
    )
    message.set_content("\n".join(text_lines))
    message.add_alternative("\n".join(html_parts), subtype="html")
    return message


def send_email(message: EmailMessage, settings: Settings) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


def build_reset_email(recipient: str, token: str, settings: Settings) -> EmailMessage:
    link = f"{settings.app_base_url.rstrip('/')}/#reset={token}"
    message = EmailMessage()
    message["Subject"] = "Reset your Tender Matcher password"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "Someone asked to reset the password for this Tender Matcher account.\n\n"
        f"Choose a new password here (the link works once, for one hour):\n{link}\n\n"
        "If this wasn't you, ignore this email; your password stays the same."
    )
    return message


def build_alert_email(subject: str, body: str, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"[Tender Matcher] {subject}"
    message["From"] = settings.smtp_from
    message["To"] = settings.admin_email
    message.set_content(body)
    return message
