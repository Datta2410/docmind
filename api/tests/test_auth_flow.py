import pytest
from app.auth import normalize_userinfo

def test_normalize_google():
    raw = {"sub": "g1", "email": "g@x.com", "name": "G User", "picture": "http://p"}
    out = normalize_userinfo("google", raw)
    assert out == {"subject": "g1", "email": "g@x.com",
                   "name": "G User", "avatar_url": "http://p"}

def test_normalize_github():
    raw = {"id": 555, "email": "h@x.com", "name": "H", "avatar_url": "http://a"}
    out = normalize_userinfo("github", raw)
    assert out["subject"] == "555" and out["avatar_url"] == "http://a"

def test_normalize_unknown_raises():
    with pytest.raises(ValueError):
        normalize_userinfo("myspace", {})

async def test_login_unknown_provider_404(client):
    resp = await client.get("/api/auth/myspace/login")
    assert resp.status_code == 404
