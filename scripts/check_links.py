"""Check relative Markdown links without external network access."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in {".git", "node_modules", ".venv"} for part in path.parts)
    )


def check(root: Path) -> list[str]:
    failures: list[str] = []
    for markdown in markdown_files(root):
        text = markdown.read_text(encoding="utf-8")
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip("<>")
            if target.startswith(SKIP_PREFIXES):
                continue
            parsed = urlsplit(target)
            path_part = unquote(parsed.path)
            if not path_part:
                continue
            candidate = (markdown.parent / path_part).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                failures.append(f"{markdown.relative_to(root)}: link escapes repository: {target}")
                continue
            if not candidate.exists():
                failures.append(f"{markdown.relative_to(root)}: missing link target: {target}")
    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = check(root)
    if failures:
        print("markdown link check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"markdown link check passed ({len(markdown_files(root))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
