"""SMS sending handler via external API gateway."""
import httpx
import os
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

SMS_API_URL = os.getenv("SMS_API_URL", "https://sms-gateway.internal.streamlineops.io/v1/send")
SMS_API_KEY = os.getenv("SMS_API_KEY", "")


async def send_sms(phone_number: str, message: str, priority: Optional[str] = "normal") -> dict:
    """Send an SMS message via the SMS gateway API.

    Args:
        phone_number: Recipient phone number in E.164 format
        message: SMS message body (max 160 characters for single segment)
        priority: Message priority - 'high', 'normal', or 'low'

    Returns:
        dict with delivery status and message metadata
    """
    payload = {
        "to": phone_number,
        "body": message,
        "priority": priority,
        "sender_id": "StreamlineOps",
    }

    headers = {
        "Authorization": f"Bearer {SMS_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(SMS_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"SMS sent to {phone_number}, message_id={result.get('message_id')}")
            return {"status": "sent", "phone": phone_number, "message_id": result.get("message_id")}
        except httpx.HTTPStatusError as e:
            logger.error(f"SMS API error: {e.response.status_code} - {e.response.text}")
            return {"status": "failed", "phone": phone_number, "error": str(e)}
        except httpx.RequestError as e:
            logger.error(f"SMS request failed: {e}")
            return {"status": "failed", "phone": phone_number, "error": "connection_error"}
