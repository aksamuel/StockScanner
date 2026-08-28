"""Add the StockScanner Supabase Auth guard to published dashboard pages."""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "data-stockscanner-auth"
INJECTION = """<style data-stockscanner-auth>
html:not(.auth-ready) { visibility: hidden; }
</style>
<script type="module" src="/StockScanner/auth.js" data-stockscanner-auth></script>
"""


def inject(path: Path) -> bool:
    if not path.exists():
        return False
    html = path.read_text(encoding="utf-8")
    if MARKER in html:
        return False
    if "</head>" not in html.lower():
        raise ValueError(f"No closing head tag in {path}")
    position = html.lower().index("</head>")
    updated = html[:position] + INJECTION + html[position:]
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    changed = [str(path) for path in args.paths if inject(path)]
    print(f"Auth guard injected into {len(changed)} page(s): {', '.join(changed) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
