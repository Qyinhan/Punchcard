import io
import json
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.main import app

# 注意：本测试会重置登录状态（删除 users/sessions 后自建测试管理员），
# 请勿在已配置正式管理员的数据库上运行。

SMOKE_PLUGIN_CODE = (
    "from app.plugins.base import BasePlugin, CheckinResult, FieldSpec\n"
    "class SmokePlugin(BasePlugin):\n"
    "    platform='smoke'\n"
    "    name='烟测'\n"
    "    credential_fields=[FieldSpec(key='username', label='用户名', sensitive=False), FieldSpec(key='token', label='Token')]\n"
    "    default_schedule_time='10:00'\n"
    "    def checkin(self, credentials, extra):\n"
    "        return CheckinResult(True, '烟测签到成功: ' + credentials.get('username', ''))\n"
    "plugin = SmokePlugin()\n"
)


def install_smoke(client) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.py", SMOKE_PLUGIN_CODE)
    r = client.post("/api/plugins/install",
                    files={"file": ("smoke.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    return r.json()


with TestClient(app) as client:
    print("health:", client.get("/api/health").json())

    print("\n== auth ==")
    from app.models.user import Session, User

    with session_scope() as db:
        db.query(Session).delete()
        db.query(User).delete()
        db.commit()
    r = client.get("/api/accounts")
    print("  unauth ->", r.status_code)
    assert r.status_code == 401
    r = client.get("/api/auth/setup-state")
    print("  setup-state ->", r.json())
    assert r.json()["setup_required"] is True
    r = client.post("/api/auth/setup", json={"username": "smoke_admin", "password": "smoke_test_pass123"})
    assert r.status_code == 200, r.text
    print("  setup ->", r.status_code)
    r = client.get("/api/accounts")
    print("  authed ->", r.status_code)
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"username": "smoke_admin", "password": "wrong"})
    print("  bad login ->", r.status_code)
    assert r.status_code == 401
    r = client.post("/api/auth/setup", json={"username": "x", "password": "12345678"})
    print("  re-setup ->", r.status_code)
    assert r.status_code == 403

    print("\n== plugins ==")
    plugins = client.get("/api/plugins").json()
    assert all(p["platform"] != "demo" for p in plugins), "demo 不应存在"
    dy = [p for p in plugins if p["platform"] == "douyin"][0]
    print(f"  douyin installed: enabled={dy['enabled']} | fields={[f['key'] for f in dy['credential_fields']]}")
    assert "source" not in dy and "removable" not in dy

    print("\n== install smoke plugin ==")
    sm = install_smoke(client)
    print(" ", sm)
    plugins = client.get("/api/plugins").json()
    assert any(p["platform"] == "smoke" for p in plugins)

    print("\n== create account ==")
    r = client.post("/api/accounts", json={
        "platform": "smoke", "name": "测试号",
        "credentials": {"username": "alice", "token": "secret-123"},
        "extra_config": {},
        "schedule_time": "12:34",
    })
    print(r.status_code, json.dumps(r.json(), ensure_ascii=False))
    aid = r.json()["id"]
    assert r.status_code == 201

    print("\n== list accounts ==")
    for a in client.get("/api/accounts").json():
        print(" ", a)

    print("\n== manual checkin ==")
    r = client.post(f"/api/accounts/{aid}/checkin")
    print(r.status_code, json.dumps(r.json(), ensure_ascii=False))
    assert r.json()["status"] == "success"

    print("\n== logs ==")
    logs = client.get("/api/logs").json()
    print("  total:", logs["total"])
    for l in logs["items"][:5]:
        print(f"  [{l['status']}] {l['platform']} {l['account_name']} - {l['message']}")

    print("\n== dashboard stats ==")
    print(" ", client.get("/api/dashboard/stats").json())

    print("\n== invalid platform ==")
    r = client.post("/api/accounts", json={"platform": "nope", "name": "x", "credentials": {}})
    print(" ", r.status_code, r.json()["detail"])
    assert r.status_code == 400

    print("\n== missing required field ==")
    r = client.post("/api/accounts", json={"platform": "smoke", "name": "x", "credentials": {}})
    print(" ", r.status_code, r.json()["detail"])
    assert r.status_code == 422

    print("\n== update without credentials keeps them ==")
    r = client.put(f"/api/accounts/{aid}", json={"name": "改名测试"})
    assert r.status_code == 200, r.text
    keys = sorted(r.json()["credential_keys"])
    print("  credential_keys:", keys)
    assert keys == ["username"]
    assert r.json()["has_credentials"] is True

    print("\n== partial credential update merges ==")
    r = client.put(f"/api/accounts/{aid}", json={"credentials": {"token": "new-token"}})
    keys = sorted(r.json()["credential_keys"])
    assert keys == ["username"]
    assert r.json()["has_credentials"] is True
    print(" ", r.status_code, keys)

    print("\n== credential update validated ==")
    r = client.put(f"/api/accounts/{aid}", json={"credentials": {"token": ""}})
    print(" ", r.status_code, r.json().get("detail"))
    assert r.status_code == 422

    print("\n== schedule_time format validated ==")
    r = client.post("/api/accounts", json={
        "platform": "smoke", "name": "x", "credentials": {"username": "a", "token": "b"},
        "schedule_time": "9:00",
    })
    print("  create 9:00 ->", r.status_code)
    assert r.status_code == 422

    print("\n== spa fallback (deep link) ==")
    r = client.get("/accounts")
    print(" ", r.status_code, r.headers.get("content-type"))
    assert r.status_code == 200

    print("\n== update & delete ==")
    r = client.put(f"/api/accounts/{aid}", json={"enabled": False, "schedule_time": "23:59"})
    print("  update:", r.status_code, r.json()["enabled"], r.json()["schedule_time"])
    print("  delete:", client.delete(f"/api/accounts/{aid}").status_code)

    print("\n== douyin: account lifecycle (no browser) ==")
    r = client.post("/api/accounts", json={
        "platform": "douyin", "name": "抖音测试", "credentials": {"phone": "13800000000"},
        "extra_config": {"message": "[续火花]", "targets": ["张三"]},
    })
    assert r.status_code == 201, r.text
    dyid = r.json()["id"]
    print("  create:", r.status_code)

    print("\n== douyin: checkin without cookies fails fast ==")
    r = client.post(f"/api/accounts/{dyid}/checkin")
    print(" ", r.status_code, r.json())
    assert r.status_code == 200 and r.json()["status"] == "failed"

    print("\n== douyin: sync-friends job fails fast without cookies ==")
    r = client.post(f"/api/accounts/{dyid}/sync-friends")
    assert r.status_code == 200, r.text
    job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
    for _ in range(20):
        if job["status"] != "running":
            break
        time.sleep(0.5)
        job = client.get(f"/api/jobs/{job['job_id']}").json()
    print(" ", job["status"], "|", job.get("error"))
    assert job["status"] == "failed"

    print("\n== douyin: login endpoint validation (no browser launched) ==")
    r = client.post(f"/api/accounts/{dyid}/login", json={"phone": ""})
    print("  empty phone ->", r.status_code)
    assert r.status_code == 400
    r = client.get(f"/api/accounts/{dyid}/login")
    print("  status without session ->", r.status_code)
    assert r.status_code == 404

    print("\n== plugin management: disable blocks create ==")
    r = client.put("/api/plugins/smoke", json={"enabled": False})
    print("  disable smoke ->", r.status_code)
    assert r.status_code == 200
    r = client.post("/api/accounts", json={"platform": "smoke", "name": "x",
                                           "credentials": {"username": "a", "token": "b"}})
    print("  create smoke while disabled ->", r.status_code, r.json().get("detail"))
    assert r.status_code == 400 and "停用" in r.json()["detail"]
    client.put("/api/plugins/smoke", json={"enabled": True})

    print("\n== plugin management: uninstall blocked by account ==")
    r = client.post("/api/accounts", json={"platform": "smoke", "name": "占位",
                                           "credentials": {"username": "a", "token": "b"}})
    held_id = r.json()["id"]
    r = client.delete("/api/plugins/smoke")
    print("  uninstall with account ->", r.status_code, r.json().get("detail"))
    assert r.status_code == 400 and "账户" in r.json()["detail"]
    client.delete(f"/api/accounts/{held_id}")

    print("\n== plugin management: uninstall works ==")
    r = client.delete("/api/plugins/smoke")
    print("  uninstall ->", r.status_code)
    assert r.status_code == 200
    assert not [p for p in client.get("/api/plugins").json() if p["platform"] == "smoke"]
    # douyin 还有账户，卸载应被拦截（证明无内置概念、全部按安装算）
    r = client.delete("/api/plugins/douyin")
    print("  uninstall douyin (has account) ->", r.status_code, r.json().get("detail"))
    assert r.status_code == 400

    client.delete(f"/api/accounts/{dyid}")

    print("\n== auth: logout & re-login ==")
    r = client.post("/api/auth/logout")
    print("  logout ->", r.status_code)
    r = client.get("/api/auth/me")
    print("  me after logout ->", r.status_code)
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "smoke_admin", "password": "smoke_test_pass123"})
    print("  login ->", r.status_code)
    assert r.status_code == 200
    r = client.get("/api/auth/me")
    print("  me ->", r.status_code, r.json())
    assert r.json()["username"] == "smoke_admin"

    with session_scope() as db:
        db.query(Session).delete()
        db.query(User).delete()
        db.commit()
    print("  users/sessions cleaned")

print("\nALL OK")
