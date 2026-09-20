import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("sampletracker.email")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "notifications@jandjsourcing.com")
SMTP_NOTIFY_DEFAULT = [
    e.strip() for e in os.getenv("SMTP_NOTIFY_DEFAULT", "").split(",") if e.strip()
]


def build_html_report(
    title: str,
    subtitle: str,
    headers: list[str],
    rows: list[list],
    highlighted_indices: set[int] = None,
    section_title: str = "Sample Details",
) -> str:
    """Renders HTML emails with explicit non-wrapping on code fields and dates to prevent awkward letter-breaking."""
    highlighted_indices = highlighted_indices or set()

    th_cells = []
    for h in headers:
        th_cells.append(
            f'<th style="padding: 10px 12px; border: 1px solid #1d4ed8; '
            f'background-color: #0066e6; color: #ffffff; font-weight: 700; '
            f'text-align: left; font-size: 13px; white-space: nowrap;">{h}</th>'
        )
    th_html = "".join(th_cells)

    tr_html = ""
    for idx, row in enumerate(rows):
        is_highlighted = idx in highlighted_indices
        bg_color = "#fee2e2" if is_highlighted else "#ffffff"

        cells = ""
        for cell_idx, cell in enumerate(row):
            header_name = headers[cell_idx] if cell_idx < len(headers) else ""
            cell_str = str(cell or "-")

            if cell_str.startswith("http://") or cell_str.startswith("https://"):
                cell_content = f'<a href="{cell_str}" style="color: #0066e6; text-decoration: underline;" target="_blank">Link</a>'
            else:
                cell_content = cell_str

            if header_name in ["Buyer Ref No", "PO No", "SKU", "Renewal Date", "Disposal Date", "Return Date"]:
                cell_style = "white-space: nowrap;"
            else:
                cell_style = "word-break: break-word;"

            cells += (
                f'<td style="padding: 10px 12px; border: 1px solid #e2e8f0; '
                f'font-size: 13px; color: #1e293b; {cell_style} '
                f'font-weight: normal;">{cell_content}</td>'
            )

        tr_html += f'<tr style="background-color: {bg_color};">{cells}</tr>'

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 20px; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #0f172a;">
        <div style="max-width: 950px; margin: 0 auto; background-color: #ffffff; padding: 24px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); overflow-x: auto;">
            <h1 style="color: #0f2752; margin: 0 0 10px 0; font-size: 22px; font-weight: 800; line-height: 1.3;">{title}</h1>
            <p style="color: #334155; font-size: 13px; margin: 0 0 20px 0; font-weight: 500;">📅 <strong>Report Date:</strong> {subtitle}</p>
            <div style="margin-bottom: 16px; border-bottom: 2px solid #0066e6; padding-bottom: 6px;">
                <h3 style="color: #0066e6; margin: 0; font-size: 15px; font-weight: 700; display: inline-block;">{section_title}</h3>
            </div>
            <table style="width: 100%; border-collapse: collapse; text-align: left; border: 1px solid #e2e8f0;">
                <thead><tr>{th_html}</tr></thead>
                <tbody>{tr_html}</tbody>
            </table>
        </div>
    </body>
    </html>
    """


def build_summary_report(
    title: str,
    subtitle: str,
    summary: dict,
    sections: list[dict],
) -> str:
    """Renders a report with a summary key/value table followed by multiple
    grouped detail tables. Each section dict:
    {"title": str, "headers": list[str], "rows": list[list],
     "highlighted_indices": set[int] (optional), "nowrap_headers": set[str] (optional)}."""

    summary_rows = "".join(
        f'<tr>'
        f'<td style="padding: 10px 14px; border: 1px solid #e2e8f0; background-color: #f8fafc; '
        f'font-weight: 700; color: #1e293b; width: 240px;">{k}</td>'
        f'<td style="padding: 10px 14px; border: 1px solid #e2e8f0; color: #1e293b;">{v}</td>'
        f'</tr>'
        for k, v in summary.items()
    )

    sections_html = ""
    for sec in sections:
        headers = sec["headers"]
        rows = sec["rows"]
        sec_title = sec["title"]
        highlighted_indices = sec.get("highlighted_indices") or set()
        nowrap_headers = sec.get("nowrap_headers") or set()

        th_cells = "".join(
            f'<th style="padding: 10px 12px; border: 1px solid #1d4ed8; '
            f'background-color: #0066e6; color: #ffffff; font-weight: 700; '
            f'text-align: left; font-size: 13px; white-space: nowrap;">{h}</th>'
            for h in headers
        )

        if rows:
            tr_html = ""
            for idx, row in enumerate(rows):
                bg_color = "#fee2e2" if idx in highlighted_indices else "#ffffff"
                cells = ""
                for cell_idx, cell in enumerate(row):
                    header_name = headers[cell_idx] if cell_idx < len(headers) else ""
                    cell_str = str(cell or "-")

                    if cell_str.startswith("http://") or cell_str.startswith("https://"):
                        cell_content = f'<a href="{cell_str}" style="color: #0066e6; text-decoration: underline;" target="_blank">Link</a>'
                    else:
                        cell_content = cell_str

                    cell_style = "white-space: nowrap;" if header_name in nowrap_headers else "word-break: break-word;"

                    cells += (
                        f'<td style="padding: 10px 12px; border: 1px solid #e2e8f0; '
                        f'font-size: 13px; color: #1e293b; {cell_style}">{cell_content}</td>'
                    )
                tr_html += f'<tr style="background-color: {bg_color};">{cells}</tr>'
        else:
            tr_html = (
                f'<tr><td colspan="{len(headers)}" style="padding: 16px; text-align: center; '
                f'color: #64748b; font-size: 13px;">No records</td></tr>'
            )

        sections_html += f"""
        <div style="margin: 26px 0 12px; border-bottom: 2px solid #0066e6; padding-bottom: 6px;">
            <h3 style="color: #0066e6; margin: 0; font-size: 15px; font-weight: 700;">{sec_title}</h3>
        </div>
        <table style="width: 100%; border-collapse: collapse; text-align: left; border: 1px solid #e2e8f0;">
            <thead><tr>{th_cells}</tr></thead>
            <tbody>{tr_html}</tbody>
        </table>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 20px; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #0f172a;">
        <div style="max-width: 950px; margin: 0 auto; background-color: #ffffff; padding: 24px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); overflow-x: auto;">
            <h1 style="color: #0f2752; margin: 0 0 10px 0; font-size: 22px; font-weight: 800; line-height: 1.3;">📦 {title}</h1>
            <p style="color: #334155; font-size: 13px; margin: 0 0 20px 0; font-weight: 500;">📅 <strong>Generated On:</strong> {subtitle}</p>
            <div style="margin-bottom: 16px; border-bottom: 2px solid #0066e6; padding-bottom: 6px;">
                <h3 style="color: #0066e6; margin: 0; font-size: 15px; font-weight: 700;">📊 Summary</h3>
            </div>
            <table style="width: 100%; border-collapse: collapse; text-align: left; border: 1px solid #e2e8f0; margin-bottom: 8px;">
                <tbody>{summary_rows}</tbody>
            </table>
            {sections_html}
        </div>
    </body>
    </html>
    """


def send_golden_samples_monthly_report(items: list[dict], report_date: str, to: list[str] | None = None):
    if not items:
        return

    headers = ["SKU", "Description", "Client", "Supplier", "Renewal Date"]
    rows = [[i["sku"], i["description"], i["client"], i["supplier"], i["renewal_due_date"]] for i in items]

    subject = f"[Sample Tracker] Golden Samples -- {len(items)} item(s) approaching renewal"
    plain_body = f"Golden Samples Report: {len(items)} item(s) approaching renewal soon."
    html_body = build_html_report(
        title="✨ Golden Samples – Approaching Renewal Report",
        subtitle=report_date,
        headers=headers,
        rows=rows,
        highlighted_indices=None,
        section_title="✨ Samples Approaching Renewal Soon",
    )
    send_email(subject, plain_body, to=to, html_body=html_body)


def send_shipment_disposal_report(items: list[dict], report_date: str, to: list[str] | None = None):
    if not items:
        return

    headers = ["Buyer Ref No", "PO No", "Description", "Vendor", "Buyer", "Location", "Disposal Date"]
    rows = [[i["buyer_ref"], i["po_no"], i["description"], i["vendor"], i["buyer"], i["location"], i["disposal_due_date"]] for i in items]

    subject = f"[Sample Tracker] Shipment Samples -- {len(items)} item(s) approaching disposal"
    plain_body = f"Shipment Samples Report: {len(items)} item(s) approaching disposal soon."
    html_body = build_html_report(
        title="🗑️ Shipment Samples – Approaching Disposal Report",
        subtitle=report_date,
        headers=headers,
        rows=rows,
        highlighted_indices=None,
        section_title="🗑️ Samples Approaching Disposal Soon",
    )
    send_email(subject, plain_body, to=to, html_body=html_body)


def notify_pending_return_by_client(client: str, items: list[dict], team_emails: list[str], report_date: str):
    if not items:
        return

    headers = ["SKU", "Description", "Product Link", "Client", "Supplier", "Return Date"]
    rows = [[i["sku"], i["description"], i["product_link"], i["client"], i["supplier"], i["return_date"]] for i in items]
    highlighted_indices = {idx for idx, item in enumerate(items) if item.get("is_overdue_1mo")}

    subject = f"[Sample Tracker] {len(items)} sample(s) pending return -- {client or 'Unassigned client'}"
    plain_body = f"Development Samples pending return for {client}."
    html_body = build_html_report(
        title="❗ Development Samples – Pending Return Report",
        subtitle=report_date,
        headers=headers,
        rows=rows,
        highlighted_indices=highlighted_indices,
        section_title="📋 Pending Return Samples",
    )
    send_email(subject, plain_body, to=team_emails, html_body=html_body)


def send_dev_samples_quarterly_report(
    client: str,
    summary: dict,
    sections: list[dict],
    report_date: str,
    recipient_emails: list[str],
):
    if not recipient_emails:
        logger.info("Quarterly dev samples report skipped for %s -- no recipients configured.", client or "(unassigned)")
        return

    client_label = client or "Unassigned client"
    total = summary.get("Total Samples", 0)
    subject = f"[Sample Tracker] Development Samples -- quarterly report ({total} records) -- {client_label}"
    plain_body = f"Development Samples quarterly report for {client_label}."

    html_body = build_summary_report(
        title=f"Development Samples Report — {client_label}",
        subtitle=report_date,
        summary=summary,
        sections=sections,
    )
    send_email(subject, plain_body, to=recipient_emails, html_body=html_body)


def send_shipment_samples_quarterly_report(
    summary: dict,
    sections: list[dict],
    report_date: str,
    recipient_emails: list[str],
):
    if not recipient_emails:
        logger.info("Quarterly shipment samples report skipped -- no recipients configured.")
        return

    total = summary.get("Total Samples", 0)
    subject = f"[Sample Tracker] Shipment Samples -- quarterly report ({total} records)"
    plain_body = "Shipment Samples quarterly report generated."

    html_body = build_summary_report(
        title="Shipment Samples Report",
        subtitle=report_date,
        summary=summary,
        sections=sections,
    )
    send_email(subject, plain_body, to=recipient_emails, html_body=html_body)


def send_golden_samples_quarterly_report(
    summary: dict,
    sections: list[dict],
    report_date: str,
    recipient_emails: list[str],
):
    if not recipient_emails:
        logger.info("Quarterly golden samples report skipped -- no recipients configured.")
        return

    total = summary.get("Total Samples", 0)
    subject = f"[Sample Tracker] Golden Samples -- quarterly report ({total} records)"
    plain_body = "Golden Samples quarterly report generated."

    html_body = build_summary_report(
        title="Golden Samples Report",
        subtitle=report_date,
        summary=summary,
        sections=sections,
    )
    send_email(subject, plain_body, to=recipient_emails, html_body=html_body)


def send_email(
    subject: str,
    body: str,
    to: list[str] | None = None,
    html_body: str | None = None,
) -> bool:
    """Best-effort email send. Returns True on success, logs and returns False on failure."""
    recipients = to or SMTP_NOTIFY_DEFAULT
    if not SMTP_HOST or not recipients:
        logger.info("Email skipped (no SMTP host or no recipients): %s", subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
        return True
    except Exception as e:
        logger.warning("Email send failed: %s", e)
        return False


def notify_status_change(
    page_label: str,
    record_label: str,
    old_status: str,
    new_status: str,
    actor_email: str,
):
    subject = f"[Sample Tracker] {page_label}: {record_label} -> {new_status}"
    body = (
        f"{record_label} on {page_label} changed status:\n"
        f"  {old_status or '(none)'} -> {new_status}\n\n"
        f"Changed by: {actor_email}"
    )
    send_email(subject, body)


def notify_overdue(page_label: str, items: list[str]):
    if not items:
        return
    subject = f"[Sample Tracker] {len(items)} overdue item(s) in {page_label}"
    body = "The following items are overdue for return:\n\n" + "\n".join(items)
    send_email(subject, body)


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """New: used by the forgot-password flow in routers/auth.py. Reuses
    the existing send_email() so it goes through the same SMTP settings,
    guard clauses, and logging as every other email in this file."""
    subject = "Reset your Sample Tracker password"
    body = (
        f"Someone requested a password reset for your Sample Tracker account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link expires in 1 hour. If you didn't request this, you can ignore this email."
    )
    return send_email(subject, body, to=[to_email])