"""Daily distress digest — categorized lead lists emailed for skip trace / drive-by."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Channels map to operator workflow
CHANNELS = {
    "lis_pendens": {
        "title": "Lis Pendens (pre-foreclosure)",
        "action": "Skip trace owner + bank party; mail within 48h of record date",
        "lead_types": ("pre_foreclosure",),
        "source_keys": ("ecclix_batch",),
        "instrument_match": ("LP",),
    },
    "probate": {
        "title": "Probate / Estate",
        "action": "Skip trace heirs; compassionate outreach",
        "lead_types": ("probate", "estate", "death"),
        "source_keys": ("ecclix_batch", "kcoj_courtnet", "legal_notices"),
    },
    "code_violations": {
        "title": "Code violations / city liens",
        "action": "Drive-by + skip trace; vacant/distressed visual",
        "lead_types": ("code_violation",),
        "source_keys": ("ecclix_batch", "georgetown_water"),
        "signal_channels": ("city_lien", "water_shutoff", "water_outage"),
    },
    "water_shutoff": {
        "title": "Water shutoff / utility distress",
        "action": "Skip trace or drive-by; FOIA list rows prioritized",
        "lead_types": ("vacancy", "code_violation"),
        "source_keys": ("georgetown_water",),
        "signal_channels": ("water_shutoff", "water_outage"),
    },
}


def _lead_matches_channel(lead: dict[str, Any], spec: dict) -> bool:
    lt = (lead.get("lead_type") or "").lower()
    sk = lead.get("source_key") or ""
    payload = lead.get("raw_payload") or {}
    if isinstance(payload, str):
        payload = {}
    inst = (payload.get("instrument_type") or "").upper()
    ch = payload.get("signal_channel") or ""

    if spec.get("instrument_match") and inst in spec["instrument_match"]:
        return True
    if spec.get("signal_channels") and ch in spec["signal_channels"]:
        return True
    if spec.get("lead_types") and lt in spec["lead_types"]:
        if not spec.get("source_keys") or sk in spec["source_keys"]:
            return True
    return False


def bucket_leads(leads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in CHANNELS}
    for lead in leads:
        for key, spec in CHANNELS.items():
            if _lead_matches_channel(lead, spec):
                buckets[key].append(lead)
    for key in buckets:
        buckets[key].sort(key=lambda x: -(x.get("hot_score") or 0))
    return buckets


def leads_to_csv_rows(leads: list[dict[str, Any]]) -> str:
    """Skip-trace friendly columns."""
    fields = [
        "hot_score",
        "owner_name",
        "property_address",
        "mailing_address",
        "city",
        "parcel_number",
        "lead_type",
        "source_key",
        "case_id",
        "grantor",
        "grantee",
        "legal_description",
        "instrument_type",
        "recorded_date",
        "amount_due",
        "action",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for lead in leads:
        payload = lead.get("raw_payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        w.writerow({
            "hot_score": lead.get("hot_score"),
            "owner_name": lead.get("owner_name") or payload.get("grantor"),
            "property_address": lead.get("property_address"),
            "mailing_address": lead.get("mailing_address") or payload.get("mailing_address"),
            "city": lead.get("city") or "Georgetown",
            "parcel_number": lead.get("parcel_number"),
            "lead_type": lead.get("lead_type"),
            "source_key": lead.get("source_key"),
            "case_id": lead.get("case_id"),
            "grantor": payload.get("grantor"),
            "grantee": payload.get("grantee"),
            "legal_description": (payload.get("legal_description") or "")[:300],
            "instrument_type": payload.get("instrument_type"),
            "recorded_date": payload.get("recorded_date"),
            "amount_due": payload.get("amount_due"),
            "action": payload.get("action", "skip_trace"),
        })
    return buf.getvalue()


def build_html_digest(buckets: dict[str, list[dict[str, Any]]], *, run_summary: str) -> str:
    lines = [
        "<h2>Foretrust Daily Signal Digest</h2>",
        f"<p>{run_summary}</p>",
        "<p><b>Next steps:</b> Import CSVs to BatchData/Direct Skip OR assign drive-by routes.</p>",
    ]
    for key, spec in CHANNELS.items():
        items = buckets.get(key, [])
        lines.append(f"<h3>{spec['title']} ({len(items)})</h3>")
        lines.append(f"<p><i>{spec['action']}</i></p>")
        if not items:
            lines.append("<p><i>No new rows this run.</i></p>")
            continue
        lines.append("<table border='1' cellpadding='4' style='border-collapse:collapse;font-size:12px'>")
        lines.append(
            "<tr><th>Score</th><th>Owner</th><th>Address</th><th>Source</th></tr>"
        )
        for item in items[:25]:
            lines.append(
                f"<tr><td>{item.get('hot_score', '')}</td>"
                f"<td>{(item.get('owner_name') or '')[:40]}</td>"
                f"<td>{(item.get('property_address') or '')[:50]}</td>"
                f"<td>{item.get('source_key', '')}</td></tr>"
            )
        if len(items) > 25:
            lines.append(f"<tr><td colspan='4'>+ {len(items) - 25} more in attached CSV</td></tr>")
        lines.append("</table>")
    return "\n".join(lines)


async def send_digest_email(
    buckets: dict[str, list[dict[str, Any]]],
    *,
    run_summary: str,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    """Send via Resend API or SMTP. Saves CSVs to export_dir either way."""
    to_addrs = [a.strip() for a in (settings.alert_digest_to or "").split(",") if a.strip()]
    if not to_addrs:
        logger.warning("[digest] ALERT_DIGEST_TO not set — skipping send")
        return {"sent": False, "reason": "no_recipients"}

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    export_dir = export_dir or (
        Path(__file__).resolve().parents[2] / "exports" / "digest"
    )
    export_dir.mkdir(parents=True, exist_ok=True)

    attachments_meta: list[dict[str, str]] = []
    for key, items in buckets.items():
        if not items:
            continue
        path = export_dir / f"{key}-{stamp}.csv"
        path.write_text(leads_to_csv_rows(items), encoding="utf-8")
        attachments_meta.append({"channel": key, "path": str(path), "count": len(items)})

    html = build_html_digest(buckets, run_summary=run_summary)
    subject = f"Foretrust Signals — LP/Probate/Code/Water — {stamp} UTC"

    if settings.resend_api_key:
        return await _send_resend(to_addrs, subject, html, attachments_meta, export_dir, stamp)

    if settings.smtp_host:
        return await _send_smtp(to_addrs, subject, html, attachments_meta)

    logger.warning("[digest] No RESEND_API_KEY or SMTP_HOST — files only at %s", export_dir)
    return {"sent": False, "reason": "no_email_provider", "exports": attachments_meta}


async def _send_resend(
    to_addrs: list[str],
    subject: str,
    html: str,
    attachments_meta: list[dict],
    export_dir: Path,
    stamp: str,
) -> dict[str, Any]:
    import base64

    att_payload = []
    for meta in attachments_meta:
        path = Path(meta["path"])
        if path.exists():
            att_payload.append({
                "filename": path.name,
                "content": base64.b64encode(path.read_bytes()).decode(),
            })

    body: dict[str, Any] = {
        "from": settings.alert_digest_from,
        "to": to_addrs,
        "subject": subject,
        "html": html,
    }
    if att_payload:
        body["attachments"] = att_payload

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=body,
        )
        if resp.status_code >= 400:
            logger.error("[digest] Resend error %s: %s", resp.status_code, resp.text)
            return {"sent": False, "error": resp.text, "exports": attachments_meta}
    logger.info("[digest] sent via Resend to %s", to_addrs)
    return {"sent": True, "provider": "resend", "to": to_addrs, "exports": attachments_meta}


async def _send_smtp(
    to_addrs: list[str],
    subject: str,
    html: str,
    attachments_meta: list[dict],
) -> dict[str, Any]:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.alert_digest_from
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html, "html"))

    for meta in attachments_meta:
        path = Path(meta["path"])
        if not path.exists():
            continue
        part = MIMEBase("application", "octet-stream")
        part.set_payload(path.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={path.name}")
        msg.attach(part)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.alert_digest_from, to_addrs, msg.as_string())

    logger.info("[digest] sent via SMTP to %s", to_addrs)
    return {"sent": True, "provider": "smtp", "to": to_addrs, "exports": attachments_meta}
