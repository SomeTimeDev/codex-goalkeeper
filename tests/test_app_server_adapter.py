import json
import queue

from goalkeeper import codex_adapter
from goalkeeper.codex_adapter import CodexAppServerJsonRpcAdapter, inspect_app_server_capabilities


class FakeStdout:
    def __init__(self):
        self.lines = queue.Queue()

    def put_json(self, payload):
        self.lines.put(json.dumps(payload) + "\n")

    def close(self):
        self.lines.put(None)

    def __iter__(self):
        return self

    def __next__(self):
        line = self.lines.get(timeout=5)
        if line is None:
            raise StopIteration
        return line


class FakeStderr:
    def __iter__(self):
        return iter([])


class FakeStdin:
    def __init__(self, process):
        self.process = process

    def write(self, line):
        self.process.handle(json.loads(line))

    def flush(self):
        return None

    def close(self):
        return None


class FakeAppServerProcess:
    goal_set_payloads = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.stdout = FakeStdout()
        self.stderr = FakeStderr()
        self.stdin = FakeStdin(self)
        self.returncode = None
        self.thread_id = "thread_fake"
        self.goal = None

    def handle(self, message):
        method = message["method"]
        request_id = message.get("id")
        params = message.get("params", {})
        if request_id is None:
            return
        if method == "initialize":
            self.stdout.put_json({"id": request_id, "result": {"userAgent": "fake"}})
        elif method == "thread/start":
            self.stdout.put_json(
                {
                    "id": request_id,
                    "result": {
                        "thread": {
                            "id": self.thread_id,
                            "status": {"type": "idle"},
                            "turns": [],
                        }
                    },
                }
            )
        elif method == "thread/goal/get":
            self.stdout.put_json({"id": request_id, "result": {"goal": self.goal}})
        elif method == "thread/goal/set":
            FakeAppServerProcess.goal_set_payloads.append(dict(params))
            if self.goal is None:
                self.goal = {
                    "threadId": params["threadId"],
                    "objective": params.get("objective"),
                    "status": params.get("status", "active"),
                    "tokenBudget": params.get("tokenBudget"),
                    "tokensUsed": 0,
                    "timeUsedSeconds": 0,
                }
            else:
                if "objective" in params:
                    self.goal["objective"] = params["objective"]
                if "status" in params:
                    self.goal["status"] = params["status"]
                if "tokenBudget" in params:
                    self.goal["tokenBudget"] = params["tokenBudget"]
            self.stdout.put_json({"id": request_id, "result": {"goal": self.goal}})
        elif method == "thread/goal/clear":
            self.goal = None
            self.stdout.put_json({"id": request_id, "result": {"cleared": True}})
        elif method == "thread/read":
            self.stdout.put_json(
                {
                    "id": request_id,
                    "result": {
                        "thread": {
                            "id": params["threadId"],
                            "preview": "fake preview",
                            "turns": [],
                            "updatedAt": 1,
                        }
                    },
                }
            )
        else:
            self.stdout.put_json(
                {
                    "id": request_id,
                    "error": {"code": -32601, "message": f"unknown method {method}"},
                }
            )

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stdout.close()

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminate()


def test_app_server_adapter_starts_persisted_thread_and_sets_goal():
    FakeAppServerProcess.goal_set_payloads = []
    adapter = CodexAppServerJsonRpcAdapter(
        codex_bin="codex",
        process_factory=FakeAppServerProcess,
    )

    result = adapter.start_goal_thread("contract objective", cwd="C:/repo", token_budget=123)

    assert result.success is True
    assert result.mode == "true_goal"
    assert result.thread_id == "thread_fake"
    assert result.goal_id is None
    assert "status=active" in result.final_response


def test_app_server_adapter_pause_resume_status_only_and_read():
    FakeAppServerProcess.goal_set_payloads = []
    adapter = CodexAppServerJsonRpcAdapter(
        codex_bin="codex",
        process_factory=FakeAppServerProcess,
    )

    with adapter:
        thread_id = adapter.thread_start(cwd="C:/repo")
        adapter.set_goal(thread_id, "objective")
        paused = adapter.set_goal_status(thread_id, "paused")
        resumed = adapter.set_goal_status(thread_id, "active")
        snapshot = adapter.read_thread(thread_id)

    assert paused.status == "paused"
    assert resumed.status == "active"
    assert snapshot.thread_id == thread_id
    assert FakeAppServerProcess.goal_set_payloads[0]["objective"] == "objective"
    assert FakeAppServerProcess.goal_set_payloads[1] == {
        "threadId": "thread_fake",
        "status": "paused",
    }
    assert FakeAppServerProcess.goal_set_payloads[2] == {
        "threadId": "thread_fake",
        "status": "active",
    }


def test_app_server_capability_probe_with_mock_process(monkeypatch):
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(codex_adapter.subprocess, "Popen", FakeAppServerProcess)

    capabilities = inspect_app_server_capabilities(cwd="C:/repo", live_probe=True)

    assert capabilities.app_server_available is True
    assert capabilities.initialize is True
    assert capabilities.thread_start is True
    assert capabilities.goal_get is True
    assert capabilities.goal_set is True
    assert capabilities.goal_pause is True
    assert capabilities.goal_clear is True
    assert capabilities.true_goal_control is True
