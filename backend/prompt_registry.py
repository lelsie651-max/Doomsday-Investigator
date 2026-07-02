import json
from pathlib import Path
from string import Formatter


class PromptRegistry:
    """Load and render externalized prompt templates from backend/prompts.json."""

    _cache: dict[str, dict] | None = None
    _formatter = Formatter()

    @classmethod
    def _prompt_file(cls) -> Path:
        return Path(__file__).resolve().parent / "prompts.json"

    @classmethod
    def _load(cls) -> dict[str, dict]:
        if cls._cache is not None:
            return cls._cache
        path = cls._prompt_file()
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        prompts = data.get("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError("prompts.json: 'prompts' must be an object")
        cls._cache = prompts
        return prompts

    @classmethod
    def get_template(cls, key: str) -> str:
        prompts = cls._load()
        item = prompts.get(key)
        if not isinstance(item, dict):
            raise KeyError(f"Prompt key not found: {key}")
        template = item.get("template", "")
        if not isinstance(template, str) or not template.strip():
            raise ValueError(f"Prompt template is empty: {key}")
        return template

    @classmethod
    def render(cls, key: str, **kwargs) -> str:
        template = cls.get_template(key)

        required: set[str] = set()
        for _, field_name, _, _ in cls._formatter.parse(template):
            if field_name:
                required.add(field_name)
        missing = sorted([name for name in required if name not in kwargs])
        if missing:
            raise KeyError(f"Missing prompt variables for '{key}': {', '.join(missing)}")

        return template.format(**kwargs)

