"""Inject scripts/fixture_dump.json into scripts/fixture_template.html."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = (root / "scripts" / "fixture_dump.json").read_text(encoding="utf-8")
# compact the JSON so the inline script stays small
data = json.dumps(json.loads(data), ensure_ascii=False, separators=(",", ":"))
template = (root / "scripts" / "fixture_template.html").read_text(encoding="utf-8")
html = template.replace("__DATA__", data)
dest = root / "scripts" / "fixture_view.html"
dest.write_text(html, encoding="utf-8")
print("wrote", dest, len(html), "bytes")
