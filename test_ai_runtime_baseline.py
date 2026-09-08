import ast
from pathlib import Path

from backend.ai_service import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_THINKING_EXTRA_BODY,
)


REPO_ROOT = Path(__file__).resolve().parent
AUDITED_AI_FILES = {
    REPO_ROOT / "backend" / "ai_service.py": 13,
    REPO_ROOT / "backend" / "agent_service.py": 3,
    REPO_ROOT / "backend" / "game_controller.py": 5,
    REPO_ROOT / "backend" / "night_alliance_system.py": 2,
    REPO_ROOT / "backend" / "daily_state_service.py": 1,
}


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return parts


def _is_direct_chat_completion_call(node: ast.Call) -> bool:
    return _attr_chain(node.func) == ["_client", "chat", "completions", "create"]


def _is_helper_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "create_deepseek_chat_completion"


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        if path.parts[-2:] == ("backend", "__pycache__"):
            continue
        files.append(path)
    return sorted(files)


def test_constants() -> None:
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert DEEPSEEK_MODEL == "deepseek-v4-flash"
    assert DEEPSEEK_THINKING_EXTRA_BODY == {"thinking": {"type": "disabled"}}


def test_no_production_deepseek_chat_assignment() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "DEEPSEEK_MODEL" for target in node.targets):
                continue
            if isinstance(node.value, ast.Constant) and node.value.value == "deepseek-chat":
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"production files still assign deepseek-chat: {offenders}"


def test_helper_wraps_direct_client_with_extra_body() -> None:
    tree = _parse(REPO_ROOT / "backend" / "ai_service.py")
    helper = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_deepseek_chat_completion"
    )
    direct_calls = [
        node for node in ast.walk(helper)
        if isinstance(node, ast.Call) and _is_direct_chat_completion_call(node)
    ]
    assert len(direct_calls) == 1
    keyword_names = {kw.arg for kw in direct_calls[0].keywords}
    assert "extra_body" in keyword_names


def test_all_audited_ai_calls_route_through_helper() -> None:
    direct_counts: dict[str, int] = {}
    helper_counts: dict[str, int] = {}

    for path, expected_helper_calls in AUDITED_AI_FILES.items():
        tree = _parse(path)
        relative = str(path.relative_to(REPO_ROOT))
        direct_count = 0
        helper_count = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_direct_chat_completion_call(node):
                direct_count += 1
            if _is_helper_call(node):
                helper_count += 1
        direct_counts[relative] = direct_count
        helper_counts[relative] = helper_count

        if path.name == "ai_service.py":
            assert direct_count == 1, f"{relative} should keep exactly one wrapped direct client call"
        else:
            assert direct_count == 0, f"{relative} should not call _client.chat.completions.create directly"
        assert helper_count == expected_helper_calls, (
            f"{relative} helper call count mismatch: expected {expected_helper_calls}, got {helper_count}"
        )

    assert sum(helper_counts.values()) == 24
    assert sum(direct_counts.values()) == 1


def test_parameters_were_not_globally_flattened() -> None:
    helper_calls: list[ast.Call] = []
    for path in AUDITED_AI_FILES:
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_helper_call(node):
                helper_calls.append(node)

    def collect_keyword_dumps(name: str) -> set[str]:
        values: set[str] = set()
        for call in helper_calls:
            for kw in call.keywords:
                if kw.arg == name:
                    values.add(ast.dump(kw.value, include_attributes=False))
        return values

    temperatures = collect_keyword_dumps("temperature")
    max_tokens = collect_keyword_dumps("max_tokens")
    timeouts = collect_keyword_dumps("timeout")

    assert len(temperatures) > 1, "temperature values were flattened unexpectedly"
    assert len(max_tokens) > 1, "max_tokens values were flattened unexpectedly"
    assert len(timeouts) > 1, "timeout values were flattened unexpectedly"


if __name__ == "__main__":
    test_constants()
    test_no_production_deepseek_chat_assignment()
    test_helper_wraps_direct_client_with_extra_body()
    test_all_audited_ai_calls_route_through_helper()
    test_parameters_were_not_globally_flattened()
    print("PASS: test_ai_runtime_baseline")
