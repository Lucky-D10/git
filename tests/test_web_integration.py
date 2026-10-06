"""HTTP/WebSocket integration with a real control thread and temporary SQLite."""
import tempfile
import time
import threading
import unittest
import uuid
from pathlib import Path
from contextlib import closing
import sqlite3

from settings import Config
from backend.service import BackendService
from backend.replay import replay_session
from web.runtime import OperatorLease
from web.queries import report_data

try:
    from fastapi.testclient import TestClient
    from web.app import create_app
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install requirements-dev.txt in .venv for HTTP/WS tests")
class WebIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lease = OperatorLease(.4)
        self.config = Config(mode="simulation", countdown_seconds=.05, data_timeout=.2,
                             storage_flush_seconds=.03, operator_timeout=.4,
                             storage_path=str(Path(self.temp.name) / "test.sqlite3"))
        self.outputs = []
        self.service = BackendService(self.config, operator=self.lease, output=lambda s:self.outputs.append(s))
        self.service.start()
        self.addCleanup(self.service.stop)
        self.stop = threading.Event()
        def feeder():
            sequence = 0
            while not self.stop.wait(.025):
                sequence += 1
                for lane in (1,2):
                    self.service.submit_frame(dict(lane=lane, raw=85 if lane==1 else 45, sequence=sequence,
                                              generation=1,received=time.monotonic(),connected=True,worn=True,state="normal"),absolute=True)
        self.feeder = threading.Thread(target=feeder,daemon=True)
        self.feeder.start()
        self.addCleanup(lambda:(self.stop.set(),self.feeder.join()))
        self.client = TestClient(create_app(self.service,self.lease,staff_pin="test-pin-123"))
        self.addCleanup(self.client.close)
        self.headers = {"Origin":"http://127.0.0.1:8000","X-Focus-Client":"web"}

    def wait_for(self,predicate,timeout=3):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=predicate()
            if value:return value
            time.sleep(.01)
        self.fail("condition timed out")

    def post(self,path,body):
        return self.client.post(path,json=body,headers=self.headers)

    def operator(self,ws):
        hello=ws.receive_json()
        self.assertEqual(hello["type"],"hello")
        result=self.post("/api/control/claim",{"connection":hello["connection"],"request_id":uuid.uuid4().hex})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()["token"]

    def command(self,token,action,**options):
        sid=options.pop("sid",self.service.session_id)
        request_id=options.pop("request_id",uuid.uuid4().hex)
        return self.post(f"/api/session/{sid}/action",dict(token=token,action=action,request_id=request_id,**options)).json()

    def test_full_flow_duplicate_prepare_report_distribution_and_export(self):
        with self.client.websocket_connect("/ws",headers={"Origin":self.headers["Origin"]}) as ws:
            token=self.operator(ws)
            old=self.service.session_id
            options=dict(players=1,activity="training",bindings=[2],references=[50],duration=10)
            first=self.command(token,"prepare",sid=old,request_id="create1",**options)
            second=self.command(token,"prepare",sid=old,request_id="create1",**options)
            self.assertTrue(first["ok"],first)
            self.assertEqual(first,second)
            sid=self.service.session_id
            self.wait_for(lambda:self.service.snapshot()["players"][0]["valid"])
            self.assertEqual(self.service.snapshot()["players"][0]["raw"],45)
            self.assertTrue(self.command(token,"start")["ok"])
            self.wait_for(lambda:self.service.snapshot()["state"]=="running")
            self.assertTrue(self.command(token,"pause")["ok"])
            self.lease.heartbeat(token,self.lease.connection)
            self.assertTrue(self.command(token,"resume")["ok"])
            self.wait_for(lambda:self.service.snapshot()["state"]=="running")
            self.assertTrue(self.command(token,"end")["ok"])
            self.wait_for(lambda:self.service.snapshot()["saved"])
            r=self.client.get(f"/api/sessions/{sid}/report").json()["report"]
            self.assertEqual(r["status"],"ready")
            self.assertAlmostEqual(r["charts"][0]["valid_seconds"],r["base"]["players"][0]["valid_seconds"],places=6)
            self.assertTrue(any(p[1] is None for p in r["charts"][0]["points"]))
            self.assertTrue(replay_session(self.service.store.path,sid)["matched"])
            self.lease.heartbeat(token,self.lease.connection)
            exported=self.post(f"/api/sessions/{sid}/export",{"token":token}).json()
            self.assertTrue(exported["ok"],exported)
            self.assertIn("lane,device",self.client.get(exported["files"][1]).text)
            self.assertEqual(self.client.get("/api/sessions?player_id=local-1").status_code,200)

    def test_teacher_preferences_persist_and_do_not_change_current_rules(self):
        from web.preferences import preferences, players
        original = self.service.engine.duration
        preset = self.client.get("/api/preferences").json()["preset"]
        preset.update(duration=120, references=[45, 65], reduced_motion=True)
        self.assertEqual(self.post("/api/preferences", {"preset": preset}).status_code, 403)
        with self.client.websocket_connect("/ws", headers={"Origin": self.headers["Origin"]}) as ws:
            token = self.operator(ws)
            result = self.post("/api/preferences", {"token": token, "preset": preset})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(preferences(self.service.store.path), preset)
            self.assertEqual(self.service.engine.duration, original)
            player = {"id": "local-1", "nickname": "蓝色伙伴", "avatar": "leaf"}
            staff = self.post("/api/staff/unlock", {"token": token, "pin": "test-pin-123"}).json()["staff_token"]
            self.headers["X-Focus-Staff"] = staff
            result = self.post("/api/players", {"token": token, "player": player})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn(player, players(self.service.store.path))
            self.assertEqual(self.post("/api/preferences", {"token": token, "preset": {**preset, "bindings": [1, 1]}}).status_code, 400)
            self.assertEqual(self.post("/api/players", {"token": token, "player": {**player, "nickname": " "}}).status_code, 400)
            self.wait_for(lambda: self.service.snapshot()["players"][0]["valid"])
            self.assertTrue(self.command(token, "start")["ok"])
            self.assertEqual(self.post("/api/preferences", {"token": token, "preset": preset}).status_code, 409)
            self.assertEqual(self.post("/api/players", {"token": token, "player": player}).status_code, 409)
        self.service.stop()
        reopened = BackendService(self.config)
        try:
            self.assertEqual(preferences(reopened.store.path), preset)
            self.assertIn(player, players(reopened.store.path))
            self.assertEqual(reopened.engine.safety, "inhibited")
        finally:
            reopened.stop()

    def test_disconnect_revokes_and_never_resumes_automatically(self):
        with self.client.websocket_connect("/ws",headers={"Origin":self.headers["Origin"]}) as ws:
            token=self.operator(ws)
            self.wait_for(lambda:self.service.snapshot()["players"][0]["valid"])
            self.assertTrue(self.command(token,"start")["ok"])
            self.wait_for(lambda:self.service.snapshot()["state"]=="running")
        self.wait_for(lambda:self.service.snapshot()["state"]=="paused")
        self.assertEqual(self.service.snapshot()["reason"],"operator_heartbeat_timeout")
        self.assertTrue(all(p["power"]==0 for p in self.outputs[-1]["players"]))
        with self.client.websocket_connect("/ws",headers={"Origin":self.headers["Origin"]}) as ws:
            self.operator(ws)
            self.assertEqual(self.service.snapshot()["state"],"paused")

    def test_only_one_tab_and_read_refresh_does_not_create(self):
        sid=self.service.session_id
        with self.client.websocket_connect("/ws",headers={"Origin":self.headers["Origin"]}) as one:
            token=self.operator(one)
            for _ in range(3):
                self.assertEqual(self.client.get("/api/session").json()["snapshot"]["session_id"],sid)
            with self.client.websocket_connect("/ws",headers={"Origin":self.headers["Origin"]}) as two:
                connection=two.receive_json()["connection"]
                denied=self.post("/api/control/claim",{"connection":connection,"request_id":"other"})
                self.assertEqual(denied.status_code,409)
                self.assertFalse(self.lease.heartbeat(token,connection))
            self.assertFalse(self.command("not-owner","start")["ok"])

    def test_origin_host_and_malformed_commands_rejected(self):
        self.assertEqual(self.client.post("/api/control/claim",json={},headers={"Origin":"http://evil.example","X-Focus-Client":"web"}).status_code,403)
        self.assertEqual(self.client.get("/api/session",headers={"Host":"evil.example"}).status_code,400)
        self.assertEqual(self.post("/api/session/x/action",{"action":"fault","request_id":"a","token":"b"}).status_code,400)
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws",headers={"Origin":"http://evil.example"}):
                pass

    def test_local_resources_maintenance_and_real_echarts(self):
        self.assertEqual(self.client.get("/").status_code,200)
        js=self.client.get("/static/echarts.min.js")
        self.assertGreater(len(js.content),500000)
        self.assertEqual(self.client.get("/api/maintenance").status_code,200)
        self.assertEqual(self.client.get("/api/maintenance/logs").content[:2],b"PK")


class LeaseRaceTests(unittest.TestCase):
    def test_reclaim_changes_generation_even_before_control_tick(self):
        now=[0.]
        lease=OperatorLease(.4,clock=lambda:now[0])
        token=lease.claim()
        generation=lease.generation
        now[0]=1
        self.assertTrue(lease.claim())
        self.assertNotEqual(generation,lease.generation)
        self.assertFalse(lease.authorized(token))

    def test_watchdog_uses_bound_headband_not_lane_number(self):
        import EEG
        from unittest.mock import patch
        from types import SimpleNamespace
        from unittest.mock import Mock
        motor = Mock()
        motor.enabled = True
        motor.update.return_value = (20, 0)
        with patch.multiple(EEG, controller=motor, _control_bindings=(2,)), patch.object(EEG,'get_samples',return_value=[SimpleNamespace(valid=False),SimpleNamespace(valid=True)]), patch.object(EEG,'_write_outputs'):
            EEG._motor_tick(1,.02)
        motor.update.assert_called_once_with(.02,(True,False))

