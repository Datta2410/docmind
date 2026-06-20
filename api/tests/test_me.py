from app.models import User
from app.session import current_user


async def test_me_requires_auth(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_me_returns_user_when_authenticated(app, client):
    fake = User(id=7, oauth_provider="google", oauth_subject="s",
                email="z@x.com", name="Zed", avatar_url=None)
    app.dependency_overrides[current_user] = lambda: fake
    resp = await client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "z@x.com"
    app.dependency_overrides.clear()
