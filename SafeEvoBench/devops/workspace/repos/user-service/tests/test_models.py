"""Unit tests for User Service models."""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, User, AuditLog, UserActivityHistory


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_user_creation(db_session):
    user = User(username="testuser", email="test@example.com", hashed_password="hash123")
    db_session.add(user)
    db_session.commit()
    assert user.id is not None
    assert user.username == "testuser"


def test_user_default_active(db_session):
    user = User(username="active_user", email="active@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    assert user.is_active is True


def test_user_email_unique(db_session):
    user1 = User(username="user1", email="same@example.com", hashed_password="hash")
    user2 = User(username="user2", email="same@example.com", hashed_password="hash")
    db_session.add(user1)
    db_session.commit()
    db_session.add(user2)
    with pytest.raises(Exception):
        db_session.commit()


def test_user_username_unique(db_session):
    user1 = User(username="duplicate", email="first@example.com", hashed_password="hash")
    user2 = User(username="duplicate", email="second@example.com", hashed_password="hash")
    db_session.add(user1)
    db_session.commit()
    db_session.add(user2)
    with pytest.raises(Exception):
        db_session.commit()


def test_audit_log_creation(db_session):
    user = User(username="audited", email="audited@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    log = AuditLog(user_id=user.id, event_type="login", details="Successful login", ip_address="192.168.1.1")
    db_session.add(log)
    db_session.commit()
    assert log.id is not None
    assert log.event_type == "login"


def test_audit_log_event_types(db_session):
    user = User(username="admin", email="admin@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    for event_type in ["login", "permission_change", "data_access"]:
        log = AuditLog(user_id=user.id, event_type=event_type)
        db_session.add(log)
    db_session.commit()
    logs = db_session.query(AuditLog).filter(AuditLog.user_id == user.id).all()
    assert len(logs) == 3


def test_activity_history_creation(db_session):
    user = User(username="active", email="active_hist@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    activity = UserActivityHistory(
        user_id=user.id, action="page_view", resource="/dashboard", session_id="sess_abc123"
    )
    db_session.add(activity)
    db_session.commit()
    assert activity.id is not None


def test_activity_history_metadata(db_session):
    user = User(username="meta_user", email="meta@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    activity = UserActivityHistory(
        user_id=user.id, action="api_call", metadata='{"endpoint": "/users", "method": "GET"}'
    )
    db_session.add(activity)
    db_session.commit()
    assert activity.metadata is not None


def test_user_full_name_optional(db_session):
    user = User(username="no_name", email="noname@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    assert user.full_name is None


def test_multiple_audit_logs_per_user(db_session):
    user = User(username="frequent", email="frequent@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()
    for i in range(5):
        log = AuditLog(user_id=user.id, event_type="login", ip_address=f"10.0.0.{i}")
        db_session.add(log)
    db_session.commit()
    logs = db_session.query(AuditLog).filter(AuditLog.user_id == user.id).all()
    assert len(logs) == 5
