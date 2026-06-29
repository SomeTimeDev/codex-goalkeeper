from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .codex_adapter import (
    AppServerCapabilityMatrix,
    CodexCapabilityMatrix,
    inspect_app_server_capabilities,
    inspect_python_sdk_capabilities,
)
from .ledger import GoalkeeperStore


@dataclass
class DoctorReport:
    python_version: str
    storage_location: Path
    sdk: CodexCapabilityMatrix
    app_server: AppServerCapabilityMatrix
    codex_binary: str | None
    features: dict[str, str]
    live_probe: bool


def collect_doctor_report(cwd: str | Path | None = None, *, live_probe: bool = False) -> DoctorReport:
    store = GoalkeeperStore(cwd)
    sdk = inspect_python_sdk_capabilities()
    app_server = inspect_app_server_capabilities(cwd=str(store.root), live_probe=live_probe)
    codex_binary = shutil.which("codex")
    true_goal_control = (
        "available"
        if app_server.true_goal_control
        else "unknown; run `goalkeeper doctor --live-probe`"
        if app_server.app_server_available and not live_probe
        else "unavailable"
    )
    return DoctorReport(
        python_version=f"{platform.python_implementation()} {sys.version.split()[0]}",
        storage_location=store.storage_dir,
        sdk=sdk,
        app_server=app_server,
        codex_binary=codex_binary,
        features={
            "contract_generation": "available",
            "paste_ready_goal_prompt": "available",
            "sdk_run_mode": _availability(sdk.sdk_run_mode),
            "sdk_thread_read": _availability(sdk.thread_read),
            "app_server_json_rpc": _availability(app_server.app_server_available),
            "true_goal_control": true_goal_control,
            "app_server_goal_start": _availability(app_server.goal_set),
            "app_server_goal_pause": _availability(app_server.goal_pause),
            "app_server_goal_read": _availability(app_server.goal_get),
            "auto_pause": _availability(app_server.goal_pause),
        },
        live_probe=live_probe,
    )


def render_doctor_report(report: DoctorReport) -> str:
    feature_lines = "\n".join(
        f"- {name.replace('_', ' ')}: {status}" for name, status in report.features.items()
    )
    codex_binary = report.codex_binary or "not found on PATH"
    sdk = "importable" if report.sdk.sdk_importable else "not importable"
    sdk_version = report.sdk.sdk_version or "unknown"
    runtime_version = report.sdk.runtime_package_version or "unknown"
    goal_methods = ", ".join(report.sdk.goal_like_methods) or "none"
    notes = "\n".join(f"- {note}" for note in report.sdk.notes) or "- None."
    app_notes = "\n".join(f"- {note}" for note in report.app_server.notes) or "- None."
    app_goal_control = (
        "available"
        if report.app_server.true_goal_control
        else "unknown; run `goalkeeper doctor --live-probe`"
        if report.app_server.app_server_available and not report.live_probe
        else "unavailable"
    )
    return f"""Goalkeeper doctor
Python: {report.python_version}
Storage: {report.storage_location}
openai_codex SDK: {sdk}
openai-codex version: {sdk_version}
openai-codex-cli-bin version: {runtime_version}
Codex binary: {codex_binary}

Features:
{feature_lines}

Detected Codex SDK capabilities:
- SDK run mode: {'available' if report.sdk.sdk_run_mode else 'unavailable'}
- thread read: {'available' if report.sdk.thread_read else 'unavailable'}
- true /goal control: {'available' if report.sdk.true_goal_control else 'unavailable'}
- goal start: {'available' if report.sdk.goal_start else 'unavailable'}
- goal pause: {'available' if report.sdk.goal_pause else 'unavailable'}
- goal resume: {'available' if report.sdk.goal_resume else 'unavailable'}
- low-level JSON-RPC request: {'available' if report.sdk.low_level_json_rpc else 'unavailable'}
- safe low-level goal control: {'available' if report.sdk.safe_low_level_goal_control else 'unavailable'}
- goal-like methods: {goal_methods}

SDK notes:
{notes}

Detected app-server JSON-RPC capabilities:
- codex binary: {report.app_server.codex_binary or 'not found'}
- app-server: {'available' if report.app_server.app_server_available else 'unavailable'}
- initialize: {'available' if report.app_server.initialize else 'unavailable'}
- thread/start: {'available' if report.app_server.thread_start else 'unavailable'}
- thread/goal/get: {'available' if report.app_server.goal_get else 'unavailable'}
- thread/goal/set: {'available' if report.app_server.goal_set else 'unavailable'}
- thread/goal/set pause: {'available' if report.app_server.goal_pause else 'unavailable'}
- thread/goal/clear: {'available' if report.app_server.goal_clear else 'unavailable'}
- thread/read: {'available' if report.app_server.thread_read else 'unavailable'}
- true /goal control: {app_goal_control}

App-server notes:
{app_notes}

Notes:
- Contract-only mode and paste-ready /goal prompts do not require Codex SDK support.
- SDK run mode can run a normal Codex thread turn when available; it is not true /goal mode.
- True goal start/watch/pause features use verified app-server JSON-RPC goal APIs when available.
"""


def _availability(value: bool) -> str:
    return "available" if value else "unavailable"
