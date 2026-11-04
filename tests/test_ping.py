def test_ping():
    """最简健康检查：/api/ping 返回成功"""

    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.json()["code"] == "success"
