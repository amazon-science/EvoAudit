"""User Service - FastAPI application for user management."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from .user_api import get_user, get_all_users, create_user, update_user, delete_user
from .models import UserActivityHistory

app = FastAPI(title="User Service", version="1.2.0")


class UserCreate(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "user-service", "timestamp": datetime.utcnow().isoformat()}


@app.get("/users")
async def list_users(skip: int = 0, limit: int = 100):
    users = get_all_users(skip=skip, limit=limit)
    return {"users": users, "count": len(users)}


@app.get("/users/{user_id}")
async def read_user(user_id: int):
    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/users", status_code=201)
async def create_new_user(user: UserCreate):
    return create_user(user.dict())


@app.put("/users/{user_id}")
async def update_existing_user(user_id: int, user: UserUpdate):
    updated = update_user(user_id, user.dict(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@app.get("/users/{user_id}/activity")
async def get_user_activity(user_id: int, days: int = 30):
    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user_id, "activity": [], "period_days": days}
