"""CRUD operations for the User service."""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from .models import User, AuditLog


def get_db_session() -> Session:
    """Get database session from connection pool."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os

    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/userdb")
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    db = get_db_session()
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    return _serialize_user(user)


def get_all_users(skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    db = get_db_session()
    users = db.query(User).offset(skip).limit(limit).all()
    return [_serialize_user(u) for u in users]


def create_user(data: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db_session()
    user = User(**data, hashed_password="hashed_placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


def update_user(user_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_db_session()
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


def delete_user(user_id: int) -> bool:
    db = get_db_session()
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True


def _serialize_user(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "created_at": str(user.created_at),
    }
