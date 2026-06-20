import pytest
from starlette.requests import Request
from app.session import login_session, logout_session

def make_request():
    scope = {"type": "http", "session": {}}
    return Request(scope)

def test_login_and_logout_mutate_session():
    req = make_request()
    login_session(req, 42)
    assert req.session["user_id"] == 42
    logout_session(req)
    assert "user_id" not in req.session
