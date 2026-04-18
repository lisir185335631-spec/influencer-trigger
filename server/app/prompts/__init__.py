"""Prompt template loader — markdown files with {{variable}} substitution."""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str, **vars: str) -> str:
    """Load a prompt markdown file relative to server/app/prompts/.

    name: relative path without .md extension, e.g. 'scraper/search_strategy.system'
    vars: optional {{variable}} substitutions (str values only)
    """
    path = _PROMPTS_DIR / f"{name}.md"
    content = path.read_text(encoding="utf-8")
    for k, v in vars.items():
        content = content.replace(f"{{{{{k}}}}}", v)
    return content
