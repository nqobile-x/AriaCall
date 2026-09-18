from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _ticket_html(ticket_id: str, issue: str, customer_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Support Ticket Confirmation</title>
</head>
<body style="margin:0;padding:0;background:#0f1114;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1114;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#17181d;border-radius:8px;overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:#ff6d4a;padding:28px 36px;">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:22px;font-weight:700;letter-spacing:.12em;color:#fff;font-family:'Helvetica Neue',Arial,sans-serif;">
                  ARIA
                </td>
                <td style="padding-left:10px;font-size:11px;color:rgba(255,255,255,.7);letter-spacing:.06em;padding-top:4px;">
                  / PULSEFLOW SUPPORT
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 36px 8px;">
            <p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;color:#a7f3d0;font-family:monospace;">
              TICKET CONFIRMED
            </p>
            <h1 style="margin:0 0 20px;font-size:26px;font-weight:400;color:#f5f1ea;line-height:1.2;">
              We've got your request,<br/>{customer_name}.
            </h1>
            <p style="margin:0 0 24px;font-size:15px;color:#9696a0;line-height:1.6;">
              A human support specialist is reviewing your case and will be in touch shortly.
            </p>
          </td>
        </tr>

        <!-- Ticket card -->
        <tr>
          <td style="padding:0 36px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0"
              style="background:#1e2028;border:1px solid #35363d;border-radius:6px;padding:20px 22px;">
              <tr>
                <td>
                  <p style="margin:0 0 4px;font-size:10px;letter-spacing:.1em;color:#686872;font-family:monospace;">
                    TICKET ID
                  </p>
                  <p style="margin:0 0 16px;font-size:18px;font-weight:600;color:#a7f3d0;font-family:monospace;">
                    #{ticket_id}
                  </p>
                  <p style="margin:0 0 4px;font-size:10px;letter-spacing:.1em;color:#686872;font-family:monospace;">
                    YOUR ISSUE
                  </p>
                  <p style="margin:0;font-size:14px;color:#f5f1ea;line-height:1.5;">
                    {issue}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- SLA row -->
        <tr>
          <td style="padding:0 36px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="33%" style="text-align:center;padding:12px 8px;background:#1e2028;border-radius:6px;">
                  <p style="margin:0 0 4px;font-size:10px;color:#686872;letter-spacing:.06em;font-family:monospace;">FREE</p>
                  <p style="margin:0;font-size:13px;color:#f5f1ea;">Community</p>
                </td>
                <td width="4%"></td>
                <td width="29%" style="text-align:center;padding:12px 8px;background:#1e2028;border-radius:6px;">
                  <p style="margin:0 0 4px;font-size:10px;color:#686872;letter-spacing:.06em;font-family:monospace;">PRO</p>
                  <p style="margin:0;font-size:13px;color:#f5f1ea;">24h email</p>
                </td>
                <td width="4%"></td>
                <td width="30%" style="text-align:center;padding:12px 8px;background:#ff6d4a20;border:1px solid #ff6d4a40;border-radius:6px;">
                  <p style="margin:0 0 4px;font-size:10px;color:#ff6d4a;letter-spacing:.06em;font-family:monospace;">BUSINESS</p>
                  <p style="margin:0;font-size:13px;color:#f5f1ea;">24/7 chat</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 36px 36px;text-align:center;">
            <a href="https://aria-support-v2.onrender.com"
              style="display:inline-block;padding:13px 28px;background:#ff6d4a;color:#fff;
                     text-decoration:none;font-size:13px;font-weight:600;letter-spacing:.04em;
                     border-radius:4px;">
              VIEW HELP CENTRE
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 36px;border-top:1px solid #35363d;">
            <p style="margin:0;font-size:11px;color:#686872;line-height:1.6;">
              You are receiving this because you contacted PulseFlow support.<br/>
              Questions? Email <a href="mailto:support@pulseflow.io" style="color:#a7f3d0;">support@pulseflow.io</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_ticket_email(to_email: str, customer_name: str, ticket_id: str, issue: str) -> bool:
    """Send a ticket confirmation email via Resend. Returns True on success."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email")
        return False
    try:
        import httpx
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": "Aria Support <onboarding@resend.dev>",
                "to": [to_email],
                "subject": f"Your PulseFlow support ticket #{ticket_id}",
                "html": _ticket_html(ticket_id, issue, customer_name),
            },
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            logger.info("Ticket email sent to %s (ticket %s)", to_email, ticket_id)
            return True
        logger.error("Resend error %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("Resend exception: %s", exc)
    return False
