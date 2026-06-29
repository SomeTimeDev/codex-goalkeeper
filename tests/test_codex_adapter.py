from types import SimpleNamespace

from goalkeeper import codex_adapter
from goalkeeper.codex_adapter import PythonSdkCodexAdapter, inspect_python_sdk_capabilities


class FakeThread:
    id = "thread_fake"

    def run(self, input, *, cwd=None):  # noqa: A002 - mirrors SDK signature.
        _ = (input, cwd)
        return SimpleNamespace(final_response="completed normal sdk run")

    def read(self, *, include_turns=False):
        return SimpleNamespace(
            model_dump=lambda mode="json": {
                "thread": {
                    "id": self.id,
                    "preview": "fake thread",
                    "turns": [{"role": "assistant", "text": "ok"}] if include_turns else [],
                    "updated_at": 123,
                }
            }
        )


class FakeCodex:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def thread_start(self, *, cwd=None):
        _ = cwd
        return FakeThread()

    def thread_resume(self, thread_id, *, cwd=None):
        _ = (thread_id, cwd)
        return FakeThread()

    def thread_list(self):
        return []


class FakeCodexClient:
    def request(self, method, params, *, response_model):
        return response_model(method, params)


def fake_import_module(name):
    if name == "openai_codex":
        return SimpleNamespace(Codex=FakeCodex, __version__="fake-module-version")
    if name == "openai_codex.api":
        return SimpleNamespace(Thread=FakeThread)
    if name == "openai_codex.client":
        return SimpleNamespace(CodexClient=FakeCodexClient)
    raise ImportError(name)


def fake_version(name):
    versions = {
        "openai-codex": "0.1.0b3",
        "openai-codex-cli-bin": "0.137.0a4",
    }
    if name not in versions:
        raise codex_adapter.importlib.metadata.PackageNotFoundError(name)
    return versions[name]


def test_capability_matrix_detects_sdk_run_but_not_true_goal(monkeypatch):
    monkeypatch.setattr(codex_adapter.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(codex_adapter.importlib.metadata, "version", fake_version)

    capabilities = inspect_python_sdk_capabilities()

    assert capabilities.sdk_importable is True
    assert capabilities.sdk_version == "0.1.0b3"
    assert capabilities.runtime_package_version == "0.137.0a4"
    assert capabilities.sdk_run_mode is True
    assert capabilities.thread_read is True
    assert capabilities.low_level_json_rpc is True
    assert capabilities.true_goal_control is False
    assert capabilities.goal_start is False
    assert capabilities.goal_pause is False
    assert capabilities.goal_resume is False


def test_python_sdk_adapter_does_not_pretend_goal_control(monkeypatch):
    monkeypatch.setattr(codex_adapter.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(codex_adapter.importlib.metadata, "version", fake_version)

    adapter = PythonSdkCodexAdapter()
    result = adapter.start_goal("thread_fake", "contract")

    assert result.success is False
    assert result.supported is False
    assert result.mode == "unsupported"
    assert "no verified true /goal lifecycle API" in result.message


def test_python_sdk_adapter_sdk_run_mode(monkeypatch):
    monkeypatch.setattr(codex_adapter.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(codex_adapter.importlib.metadata, "version", fake_version)

    adapter = PythonSdkCodexAdapter()
    result = adapter.start_sdk_run("contract", cwd="C:/repo")

    assert result.success is True
    assert result.mode == "sdk_run"
    assert result.thread_id == "thread_fake"
    assert result.final_response == "completed normal sdk run"


def test_missing_sdk_capability_matrix(monkeypatch):
    def missing_import(name):
        raise ImportError(name)

    monkeypatch.setattr(codex_adapter.importlib, "import_module", missing_import)

    capabilities = inspect_python_sdk_capabilities()

    assert capabilities.sdk_importable is False
    assert capabilities.sdk_run_mode is False
