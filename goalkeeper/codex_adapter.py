from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


AdapterMode = Literal["contract_only", "sdk_run", "true_goal", "unsupported"]


@dataclass
class StartGoalResult:
    success: bool
    supported: bool
    message: str
    goal_id: str | None = None
    thread_id: str | None = None
    paste_ready: str | None = None
    mode: AdapterMode = "unsupported"
    final_response: str | None = None


@dataclass
class PauseGoalResult:
    success: bool
    supported: bool
    message: str


@dataclass
class ResumeGoalResult:
    success: bool
    supported: bool
    message: str


@dataclass
class ThreadSnapshot:
    thread_id: str
    messages: list[Any] = field(default_factory=list)
    latest_event_id: str | None = None
    summary: str = ""
    raw: Any = None


@dataclass
class GoalState:
    thread_id: str
    objective: str | None = None
    status: str | None = None
    token_budget: int | None = None
    tokens_used: int | None = None
    time_used_seconds: int | None = None
    raw: dict[str, Any] | None = None


@dataclass
class CodexCapabilityMatrix:
    sdk_importable: bool
    sdk_version: str | None = None
    runtime_package_version: str | None = None
    codex_methods: list[str] = field(default_factory=list)
    thread_methods: list[str] = field(default_factory=list)
    goal_like_methods: list[str] = field(default_factory=list)
    sdk_run_mode: bool = False
    thread_read: bool = False
    true_goal_control: bool = False
    goal_start: bool = False
    goal_pause: bool = False
    goal_resume: bool = False
    low_level_json_rpc: bool = False
    safe_low_level_goal_control: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class AppServerCapabilityMatrix:
    codex_binary: str | None
    app_server_available: bool = False
    initialize: bool = False
    thread_start: bool = False
    goal_get: bool = False
    goal_set: bool = False
    goal_pause: bool = False
    goal_clear: bool = False
    thread_read: bool = False
    true_goal_control: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class CodexAdapter(ABC):
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def start_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        raise NotImplementedError

    @abstractmethod
    def pause_goal(self, thread_id: str) -> PauseGoalResult:
        raise NotImplementedError

    @abstractmethod
    def resume_goal(self, thread_id: str) -> ResumeGoalResult:
        raise NotImplementedError

    @abstractmethod
    def read_thread(self, thread_id: str) -> ThreadSnapshot:
        raise NotImplementedError


class DryRunCodexAdapter(CodexAdapter):
    def __init__(self, paste_ready: str = "") -> None:
        self.paste_ready = paste_ready

    def available(self) -> bool:
        return True

    def start_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        _ = (thread_id, objective, token_budget)
        return StartGoalResult(
            success=False,
            supported=True,
            message="Dry-run adapter did not start Codex. Use the paste-ready /goal text.",
            paste_ready=self.paste_ready,
            mode="contract_only",
        )

    def pause_goal(self, thread_id: str) -> PauseGoalResult:
        _ = thread_id
        return PauseGoalResult(
            success=False,
            supported=False,
            message="Dry-run adapter cannot pause Codex automatically.",
        )

    def resume_goal(self, thread_id: str) -> ResumeGoalResult:
        _ = thread_id
        return ResumeGoalResult(
            success=False,
            supported=False,
            message="Dry-run adapter cannot resume Codex automatically.",
        )

    def read_thread(self, thread_id: str) -> ThreadSnapshot:
        return ThreadSnapshot(
            thread_id=thread_id,
            summary="Dry-run adapter cannot read Codex threads.",
        )


class PythonSdkCodexAdapter(CodexAdapter):
    module_name = "openai_codex"

    def __init__(self) -> None:
        self._module: Any | None = None
        self._load_error: str | None = None
        self._capabilities: CodexCapabilityMatrix | None = None

    def available(self) -> bool:
        return self._load_module() is not None

    def capabilities(self) -> CodexCapabilityMatrix:
        if self._capabilities is not None:
            return self._capabilities
        self._capabilities = inspect_python_sdk_capabilities()
        if not self._capabilities.sdk_importable and self._load_error:
            self._capabilities.notes.append(self._unavailable_message())
        return self._capabilities

    def start_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        _ = (thread_id, objective, token_budget)
        capabilities = self.capabilities()
        if not capabilities.sdk_importable:
            return StartGoalResult(False, False, self._unavailable_message())
        return StartGoalResult(
            False,
            False,
            (
                "The installed openai-codex SDK exposes thread_start/thread_resume/thread.run, "
                "but no verified true /goal lifecycle API. Use contract-only mode or explicit "
                "SDK run mode instead."
            ),
            mode="unsupported",
        )

    def start_sdk_run(
        self,
        objective: str,
        *,
        thread_id: str | None = None,
        cwd: str | None = None,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        _ = token_budget
        module = self._load_module()
        if module is None:
            return StartGoalResult(False, False, self._unavailable_message())
        capabilities = self.capabilities()
        if not capabilities.sdk_run_mode:
            return StartGoalResult(
                False,
                False,
                "The installed openai-codex SDK does not expose thread.run SDK run mode.",
                mode="unsupported",
            )
        try:
            codex_cls = getattr(module, "Codex")
            with codex_cls() as codex:
                if thread_id:
                    thread = codex.thread_resume(thread_id, cwd=cwd)
                else:
                    thread = codex.thread_start(cwd=cwd)
                result = thread.run(objective, cwd=cwd)
                final_response = str(getattr(result, "final_response", result))
                return StartGoalResult(
                    True,
                    True,
                    (
                        "SDK run mode completed a normal Codex thread turn. "
                        "This is not native /goal mode."
                    ),
                    thread_id=str(getattr(thread, "id", thread_id or "")) or None,
                    mode="sdk_run",
                    final_response=final_response,
                )
        except Exception as exc:
            return StartGoalResult(
                False,
                True,
                f"SDK run mode failed: {exc}",
                thread_id=thread_id,
                mode="sdk_run",
            )

    def pause_goal(self, thread_id: str) -> PauseGoalResult:
        _ = thread_id
        capabilities = self.capabilities()
        if not capabilities.sdk_importable:
            return PauseGoalResult(False, False, self._unavailable_message())
        return PauseGoalResult(
            False,
            False,
            "The installed openai-codex SDK has no verified true /goal pause API.",
        )

    def resume_goal(self, thread_id: str) -> ResumeGoalResult:
        _ = thread_id
        capabilities = self.capabilities()
        if not capabilities.sdk_importable:
            return ResumeGoalResult(False, False, self._unavailable_message())
        return ResumeGoalResult(
            False,
            False,
            "The installed openai-codex SDK has no verified true /goal resume API.",
        )

    def read_thread(self, thread_id: str) -> ThreadSnapshot:
        module = self._load_module()
        if module is None:
            return ThreadSnapshot(thread_id=thread_id, summary=self._unavailable_message())
        capabilities = self.capabilities()
        if not capabilities.thread_read:
            return ThreadSnapshot(
                thread_id=thread_id,
                summary="openai_codex is importable, but no verified thread.read method was found.",
            )
        try:
            codex_cls = getattr(module, "Codex")
            with codex_cls() as codex:
                thread = codex.thread_resume(thread_id)
                try:
                    result = thread.read(include_turns=True)
                except Exception:
                    result = thread.read(include_turns=False)
        except Exception as exc:
            return ThreadSnapshot(thread_id=thread_id, summary=f"SDK read failed: {exc}")
        return _snapshot_from_result(thread_id, result)

    def _load_module(self) -> Any | None:
        if self._module is not None:
            return self._module
        if self._load_error is not None:
            return None
        try:
            self._module = importlib.import_module(self.module_name)
        except Exception as exc:  # pragma: no cover - exact import error is environment-specific.
            self._load_error = str(exc)
            return None
        return self._module

    def _unavailable_message(self) -> str:
        detail = f": {self._load_error}" if self._load_error else ""
        return f"openai_codex SDK is not available{detail}."


def inspect_python_sdk_capabilities() -> CodexCapabilityMatrix:
    try:
        module = importlib.import_module("openai_codex")
    except Exception as exc:
        return CodexCapabilityMatrix(
            sdk_importable=False,
            notes=[f"openai_codex import failed: {exc}"],
        )

    sdk_version = _package_version("openai-codex") or getattr(module, "__version__", None)
    runtime_version = _package_version("openai-codex-cli-bin")
    codex_cls = getattr(module, "Codex", None)
    codex_methods = _public_methods(codex_cls)

    thread_cls = None
    try:
        api_module = importlib.import_module("openai_codex.api")
        thread_cls = getattr(api_module, "Thread", None)
    except Exception:
        thread_cls = None
    thread_methods = _public_methods(thread_cls)

    goal_like_methods = sorted(
        method
        for method in [*codex_methods, *thread_methods]
        if "goal" in method.lower()
    )
    sdk_run_mode = "thread_start" in codex_methods and "run" in thread_methods
    thread_read = "thread_resume" in codex_methods and "read" in thread_methods

    low_level_json_rpc = False
    try:
        client_module = importlib.import_module("openai_codex.client")
        client_cls = getattr(client_module, "CodexClient", None)
        low_level_json_rpc = callable(getattr(client_cls, "request", None))
    except Exception:
        low_level_json_rpc = False

    notes = []
    if sdk_run_mode:
        notes.append("SDK run mode is available through Codex.thread_start/thread_resume and Thread.run.")
    if thread_read:
        notes.append("Thread read mode is available through Thread.read.")
    if not goal_like_methods:
        notes.append("No public goal-specific SDK methods were detected.")
    if low_level_json_rpc:
        notes.append(
            "Low-level JSON-RPC request access exists, but no goal method names/payloads were verified."
        )

    return CodexCapabilityMatrix(
        sdk_importable=True,
        sdk_version=sdk_version,
        runtime_package_version=runtime_version,
        codex_methods=codex_methods,
        thread_methods=thread_methods,
        goal_like_methods=goal_like_methods,
        sdk_run_mode=sdk_run_mode,
        thread_read=thread_read,
        true_goal_control=False,
        goal_start=False,
        goal_pause=False,
        goal_resume=False,
        low_level_json_rpc=low_level_json_rpc,
        safe_low_level_goal_control=False,
        notes=notes,
    )


class JsonRpcError(RuntimeError):
    def __init__(self, method: str, error: dict[str, Any]) -> None:
        self.method = method
        self.error = error
        code = error.get("code")
        message = error.get("message", "JSON-RPC error")
        super().__init__(f"{method} failed ({code}): {message}")


class CodexAppServerJsonRpcAdapter(CodexAdapter):
    """Raw app-server JSON-RPC adapter for verified true goal-control methods."""

    def __init__(
        self,
        *,
        codex_bin: str | None = None,
        cwd: str | None = None,
        process_factory: Any | None = None,
        request_timeout_s: float = 30.0,
    ) -> None:
        self.codex_bin = codex_bin
        self.cwd = cwd
        self.process_factory = process_factory or subprocess.Popen
        self.request_timeout_s = request_timeout_s
        self._proc: Any | None = None
        self._stdout_queue: queue.Queue[str | BaseException | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return _resolve_codex_command(self.codex_bin) is not None

    def start_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        if not thread_id:
            return StartGoalResult(
                False,
                False,
                "App-server goal start needs an existing thread id. Use start_goal_thread to create one.",
                mode="true_goal",
            )
        try:
            with self:
                goal = self.set_goal(thread_id, objective, token_budget=token_budget)
            return StartGoalResult(
                True,
                True,
                "App-server thread/goal/set created an active Codex goal.",
                goal_id=thread_id,
                thread_id=thread_id,
                mode="true_goal",
                final_response=_format_goal_state(goal),
            )
        except Exception as exc:
            return StartGoalResult(False, True, f"App-server goal start failed: {exc}", mode="true_goal")

    def start_goal_thread(
        self,
        objective: str,
        *,
        cwd: str | None = None,
        token_budget: int | None = None,
    ) -> StartGoalResult:
        try:
            with self:
                thread_id = self.thread_start(cwd=cwd or self.cwd, ephemeral=False)
                goal = self.set_goal(thread_id, objective, token_budget=token_budget)
            return StartGoalResult(
                True,
                True,
                "App-server created a persisted thread and set an active Codex goal.",
                goal_id=thread_id,
                thread_id=thread_id,
                mode="true_goal",
                final_response=_format_goal_state(goal),
            )
        except Exception as exc:
            return StartGoalResult(False, True, f"App-server true goal mode failed: {exc}", mode="true_goal")

    def pause_goal(self, thread_id: str) -> PauseGoalResult:
        try:
            with self:
                self.set_goal_status(thread_id, "paused")
            return PauseGoalResult(True, True, "App-server thread/goal/set paused the goal.")
        except Exception as exc:
            return PauseGoalResult(False, True, f"App-server pause failed: {exc}")

    def resume_goal(self, thread_id: str) -> ResumeGoalResult:
        try:
            with self:
                self.set_goal_status(thread_id, "active")
            return ResumeGoalResult(True, True, "App-server thread/goal/set resumed the goal.")
        except Exception as exc:
            return ResumeGoalResult(False, True, f"App-server resume failed: {exc}")

    def read_thread(self, thread_id: str) -> ThreadSnapshot:
        try:
            with self:
                result = self.thread_read(thread_id, include_turns=True)
            return _snapshot_from_result(thread_id, {"thread": result.get("thread", result)})
        except Exception as exc:
            return ThreadSnapshot(thread_id=thread_id, summary=f"App-server thread read failed: {exc}")

    def get_goal(self, thread_id: str) -> GoalState | None:
        result = self.request("thread/goal/get", {"threadId": thread_id})
        return _goal_state_from_result(thread_id, result)

    def set_goal(
        self,
        thread_id: str,
        objective: str,
        *,
        status: str | None = None,
        token_budget: int | None = None,
    ) -> GoalState:
        params: dict[str, Any] = {"threadId": thread_id, "objective": objective}
        if status is not None:
            params["status"] = status
        if token_budget is not None:
            params["tokenBudget"] = token_budget
        result = self.request("thread/goal/set", params)
        goal = _goal_state_from_result(thread_id, result)
        if goal is None:
            raise RuntimeError("thread/goal/set returned no goal")
        return goal

    def set_goal_status(self, thread_id: str, status: str) -> GoalState:
        current = self.get_goal(thread_id)
        params: dict[str, Any] = {"threadId": thread_id, "status": status}
        if current and current.objective:
            params["objective"] = current.objective
        result = self.request("thread/goal/set", params)
        goal = _goal_state_from_result(thread_id, result)
        if goal is None:
            raise RuntimeError("thread/goal/set status update returned no goal")
        return goal

    def clear_goal(self, thread_id: str) -> bool:
        result = self.request("thread/goal/clear", {"threadId": thread_id})
        return bool(result.get("cleared"))

    def thread_start(self, *, cwd: str | None = None, ephemeral: bool = False) -> str:
        params: dict[str, Any] = {}
        if cwd:
            params["cwd"] = cwd
        if ephemeral:
            params["ephemeral"] = True
        result = self.request("thread/start", params)
        thread = result.get("thread", {})
        thread_id = thread.get("id")
        if not thread_id:
            raise RuntimeError(f"thread/start returned no thread id: {result}")
        return str(thread_id)

    def thread_read(self, thread_id: str, *, include_turns: bool = False) -> dict[str, Any]:
        try:
            return self.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": include_turns},
            )
        except JsonRpcError:
            if include_turns:
                return self.request(
                    "thread/read",
                    {"threadId": thread_id, "includeTurns": False},
                )
            raise

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_started()
        request_id = str(uuid.uuid4())
        message: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._write_message(message)
        deadline = time.time() + self.request_timeout_s
        while time.time() < deadline:
            raw = self._read_line(deadline)
            if raw is None:
                continue
            data = json.loads(raw)
            if "method" in data and "id" in data:
                self._write_message({"id": data["id"], "result": {}})
                continue
            if data.get("id") != request_id:
                continue
            if "error" in data:
                error = data["error"] if isinstance(data["error"], dict) else {"message": str(data["error"])}
                raise JsonRpcError(method, error)
            result = data.get("result", {})
            if not isinstance(result, dict):
                return {"result": result}
            return result
        raise TimeoutError(f"Timed out waiting for {method}; stderr_tail={self._stderr_tail()}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._ensure_started()
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._write_message(message)

    def __enter__(self) -> "CodexAppServerJsonRpcAdapter":
        self._ensure_started()
        self._initialize()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._stdout_queue.put(None)

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "goalkeeper",
                    "title": "Goalkeeper",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self.notify("initialized", {})

    def _ensure_started(self) -> None:
        if self._proc is not None:
            return
        command = _resolve_codex_command(self.codex_bin)
        if command is None:
            raise FileNotFoundError("codex binary was not found on PATH")
        args = _app_server_args(command)
        self._stdout_queue = queue.Queue()
        self._proc = self.process_factory(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=self.cwd,
        )
        self._start_stdout_reader_thread()
        self._start_stderr_drain_thread()

    def _write_message(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("app-server process is not running")
        with self._lock:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

    def _read_line(self, deadline: float) -> str | None:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                item = self._stdout_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self._proc is not None and getattr(self._proc, "poll", lambda: None)() is not None:
                    raise RuntimeError(f"app-server exited; stderr_tail={self._stderr_tail()}")
                continue
            if item is None:
                raise RuntimeError(f"app-server stdout closed; stderr_tail={self._stderr_tail()}")
            if isinstance(item, BaseException):
                raise item
            return item

    def _start_stdout_reader_thread(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return

        def read_stdout() -> None:
            try:
                for line in self._proc.stdout:
                    self._stdout_queue.put(line.rstrip("\n"))
            except BaseException as exc:
                self._stdout_queue.put(exc)
            finally:
                self._stdout_queue.put(None)

        self._stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        self._stdout_thread.start()
        return None

    def _start_stderr_drain_thread(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return

        def drain() -> None:
            try:
                for line in self._proc.stderr:
                    self._stderr_lines.append(line.rstrip("\n"))
                    del self._stderr_lines[:-50]
            except Exception:
                pass

        self._stderr_thread = threading.Thread(target=drain, daemon=True)
        self._stderr_thread.start()

    def _stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines[-20:])


def inspect_app_server_capabilities(
    *,
    codex_bin: str | None = None,
    cwd: str | None = None,
    live_probe: bool = True,
) -> AppServerCapabilityMatrix:
    command = _resolve_codex_command(codex_bin)
    report = AppServerCapabilityMatrix(codex_binary=command)
    if command is None:
        report.notes.append("codex binary was not found on PATH.")
        return report
    report.app_server_available = True
    if not live_probe:
        report.notes.append("Live app-server goal probe was skipped.")
        return report
    adapter = CodexAppServerJsonRpcAdapter(codex_bin=command, cwd=cwd, request_timeout_s=20.0)
    thread_id = None
    try:
        with adapter:
            report.initialize = True
            thread_id = adapter.thread_start(cwd=cwd, ephemeral=False)
            report.thread_start = True
            adapter.get_goal(thread_id)
            report.goal_get = True
            adapter.set_goal(thread_id, "Goalkeeper capability probe")
            report.goal_set = True
            adapter.set_goal_status(thread_id, "paused")
            report.goal_pause = True
            adapter.clear_goal(thread_id)
            report.goal_clear = True
            try:
                adapter.request("thread/archive", {"threadId": thread_id})
                report.notes.append("Capability probe thread was archived.")
            except Exception as exc:
                report.notes.append(f"Capability probe thread archive skipped: {exc}")
            report.true_goal_control = (
                report.goal_get and report.goal_set and report.goal_pause and report.goal_clear
            )
            try:
                adapter.thread_read(thread_id, include_turns=False)
                report.thread_read = True
            except Exception as exc:
                report.notes.append(f"thread/read probe skipped after goal probe: {exc}")
            report.notes.append("App-server thread/goal/get,set,clear probe succeeded.")
    except Exception as exc:
        report.notes.append(f"App-server goal probe failed: {exc}")
    return report


def _resolve_codex_command(codex_bin: str | None = None) -> str | None:
    if codex_bin:
        return codex_bin
    return shutil.which("codex")


def _app_server_args(codex_command: str) -> list[str]:
    if os.name == "nt" and codex_command.lower().endswith((".cmd", ".bat")):
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            codex_command,
            "app-server",
            "--listen",
            "stdio://",
        ]
    return [codex_command, "app-server", "--listen", "stdio://"]


def _goal_state_from_result(thread_id: str, result: dict[str, Any]) -> GoalState | None:
    raw_goal = result.get("goal")
    if raw_goal is None:
        return None
    if not isinstance(raw_goal, dict):
        raise RuntimeError(f"Expected goal object, got {raw_goal!r}")
    return GoalState(
        thread_id=str(raw_goal.get("threadId") or thread_id),
        objective=raw_goal.get("objective"),
        status=raw_goal.get("status"),
        token_budget=raw_goal.get("tokenBudget"),
        tokens_used=raw_goal.get("tokensUsed"),
        time_used_seconds=raw_goal.get("timeUsedSeconds"),
        raw=raw_goal,
    )


def _format_goal_state(goal: GoalState) -> str:
    return (
        f"thread_id={goal.thread_id}, status={goal.status}, "
        f"token_budget={goal.token_budget}, tokens_used={goal.tokens_used}"
    )


def _public_methods(owner: Any) -> list[str]:
    if owner is None:
        return []
    result = []
    for name in dir(owner):
        if name.startswith("_"):
            continue
        value = getattr(owner, name, None)
        if callable(value) or isinstance(value, property):
            result.append(name)
    return sorted(result)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _snapshot_from_result(thread_id: str, result: Any) -> ThreadSnapshot:
    messages = []
    latest_event_id = None
    summary = ""
    raw = _to_plain_result(result)
    if isinstance(raw, dict):
        thread = raw.get("thread", {})
        if isinstance(thread, dict):
            raw_messages = thread.get("turns") or thread.get("messages") or []
            messages = raw_messages if isinstance(raw_messages, list) else [raw_messages]
            latest_event_id = thread.get("updated_at") or thread.get("id")
            summary = str(thread.get("preview") or thread.get("name") or "")
        else:
            raw_messages = raw.get("messages") or raw.get("events") or []
            messages = raw_messages if isinstance(raw_messages, list) else [raw_messages]
            latest_event_id = raw.get("latest_event_id") or raw.get("last_event_id")
            summary = str(raw.get("summary", ""))
    return ThreadSnapshot(
        thread_id=thread_id,
        messages=messages,
        latest_event_id=str(latest_event_id) if latest_event_id else None,
        summary=summary,
        raw=raw,
    )


def _to_plain_result(result: Any) -> Any:
    if isinstance(result, dict):
        return result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()
    return result
