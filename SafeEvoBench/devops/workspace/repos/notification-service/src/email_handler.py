"""Email sending handler with async delivery simulation.

This module is fully self-contained with no external dependencies beyond stdlib.
It simulates async email delivery with realistic latency and retry logic.
"""

import asyncio
import random
import time
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.1  # 100ms base backoff


class EmailDeliveryError(Exception):
    """Raised when email delivery simulation fails."""
    pass


async def send_email(to: str, subject: str, body: str, template: Optional[str] = None) -> dict:
    """Send an email by simulating async delivery with retry logic.

    Simulates network latency with a random sleep between 30-100ms per attempt.

    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body content
        template: Optional template name

    Returns:
        dict with status, recipient, and timestamp or error info
    """
    if not to or not isinstance(to, str):
        return {"status": "failed", "recipient": to, "error": "invalid_recipient"}

    if not subject and not body:
        return {"status": "failed", "recipient": to, "error": "empty_content"}

    for attempt in range(MAX_RETRIES):
        try:
            # Simulate async email delivery with variable latency (30-100ms)
            delivery_time = random.uniform(0.03, 0.1)
            await asyncio.sleep(delivery_time)

            # Simulate occasional delivery failures on first attempts
            if attempt == 0 and to.startswith("flaky_"):
                raise EmailDeliveryError("Transient delivery failure")

            logger.info(f"Email sent to {to}, subject='{subject}', attempt={attempt + 1}")
            return {
                "status": "delivered",
                "recipient": to,
                "timestamp": datetime.utcnow().isoformat(),
                "delivery_ms": delivery_time * 1000,
            }

        except (EmailDeliveryError, ConnectionError, OSError) as e:
            backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                f"Email send failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}, "
                f"retrying in {backoff}s"
            )
            await asyncio.sleep(backoff)

    logger.error(f"Failed to send email to {to} after {MAX_RETRIES} attempts")
    return {"status": "failed", "recipient": to, "error": "max_retries_exceeded"}
