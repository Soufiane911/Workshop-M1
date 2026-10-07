import os
os.environ["API_TOKEN"] = "t"
from fastapi.testclient import TestClient
import main

sent = []
main.client.publish = lambda t, p, qos=0: (sent.append((t, p)), type("R", (), {"rc": 0})())[1]
c = TestClient(main.app)
H = {"Authorization": "Bearer t"}
OK = {"device_id": "esp-01", "actuator": "buzzer", "state": "on"}


def test_requires_token():
    assert c.post("/api/v1/commands", json=OK).status_code == 401


def test_rejects_unknown_actuator_and_bad_device():
    assert c.post("/api/v1/commands", json={**OK, "actuator": "relay"}, headers=H).status_code == 422
    assert c.post("/api/v1/commands", json={**OK, "device_id": "../x"}, headers=H).status_code == 422


def test_valid_command_published():
    assert c.post("/api/v1/commands", json=OK, headers=H).status_code == 202
    assert sent[-1][0] == "sentinel/esp-01/cmd"
    assert '"buzzer"' in sent[-1][1]
