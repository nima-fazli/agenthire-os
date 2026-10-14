from fastapi.testclient import TestClient

from app.main import app


def test_auth_feedback_is_outside_hidden_authenticated_shell():
    response = TestClient(app).get("/workspace/")
    assert response.status_code == 200
    html = response.text
    assert html.index('id="notification"') < html.index('id="shell"')
    assert 'id="notice" class="notice" role="status"' in html
    assert 'id="notice-alert" class="visually-hidden" role="alert"' in html
    assert 'id="notice-dismiss"' in html
