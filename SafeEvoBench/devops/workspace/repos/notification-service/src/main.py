"""Notification Service - FastAPI application for email notifications."""

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from .email_handler import send_email

app = FastAPI(title="Notification Service", version="2.1.0")


class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    template: Optional[str] = None


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "notification-service",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/send-email", status_code=202)
async def send_email_endpoint(request: EmailRequest, background_tasks: BackgroundTasks):
    """Queue an email for delivery."""
    background_tasks.add_task(
        send_email, request.to, request.subject, request.body, request.template
    )
    return {
        "status": "queued",
        "recipient": request.to,
        "message_id": f"msg_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
    }
