from goalkeeper.calibration import calibrate_objective
from goalkeeper.filesystem import inspect_repository


GENERIC_FRAGMENTS = (
    "can you clarify",
    "should i continue",
    "what exactly do you want",
    "should i write tests",
)


def test_question_policy_is_limited_and_targeted(tmp_path):
    contract = calibrate_objective(
        "migrate auth provider and refactor public sdk for release",
        cwd=tmp_path,
        max_questions=3,
    )

    assert len(contract.questions) <= 3
    prompts = [question.prompt.lower() for question in contract.questions]
    assert any("legacy provider" in prompt for prompt in prompts)
    assert all(not any(fragment in prompt for fragment in GENERIC_FRAGMENTS) for prompt in prompts)


def test_no_questions_when_no_material_ambiguity(tmp_path):
    contract = calibrate_objective(
        "refactor billing module without breaking public API",
        cwd=tmp_path,
    )

    assert len(contract.questions) <= 1
    assert all("can you clarify" not in question.prompt.lower() for question in contract.questions)


def test_verification_inference_for_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}', encoding="utf-8")

    facts = inspect_repository(tmp_path)

    assert "npm test" in facts.test_commands


def test_verification_inference_for_pnpm(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'", encoding="utf-8")

    facts = inspect_repository(tmp_path)

    assert "pnpm test" in facts.test_commands


def test_verification_inference_for_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    facts = inspect_repository(tmp_path)

    assert "pytest" in facts.test_commands


def test_verification_inference_for_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")

    facts = inspect_repository(tmp_path)

    assert "cargo test" in facts.test_commands


def test_turkish_migration_objective_triggers_fallback_question(tmp_path):
    contract = calibrate_objective("auth sağlayıcısını yeni sisteme taşı", cwd=tmp_path)

    assert any(question.id == "Q_FALLBACK" for question in contract.questions)


def test_turkish_compat_phrase_adds_compat_criterion(tmp_path):
    contract = calibrate_objective(
        "faturalama modülünü mevcut davranışı bozmadan yeniden düzenle",
        cwd=tmp_path,
    )

    assert any(criterion.id == "AC_COMPAT" for criterion in contract.acceptance_criteria)
    assert not any(question.id == "Q_COMPAT" for question in contract.questions)


def test_short_tokens_do_not_match_inside_words(tmp_path):
    contract = calibrate_objective("add specific circuit breaker handling", cwd=tmp_path)

    assert not any(question.id == "Q_WAIT_CONDITION" for question in contract.questions)
    assert not any(criterion.id == "AC_WAIT" for criterion in contract.acceptance_criteria)


def test_custom_criteria_are_appended(tmp_path):
    contract = calibrate_objective(
        "add health endpoint",
        cwd=tmp_path,
        extra_criteria=["GET /health returns 200", "  ", "Latency stays under 50ms"],
    )

    ids = [criterion.id for criterion in contract.acceptance_criteria]
    assert "AC_U1" in ids
    assert "AC_U2" in ids
    assert not any(criterion.id == "AC_U3" for criterion in contract.acceptance_criteria)
