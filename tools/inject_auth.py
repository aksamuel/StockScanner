"""Add the StockScanner Supabase Auth guard to published dashboard pages."""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "data-stockscanner-auth"
INJECTION = """<style data-stockscanner-auth>
html:not(.auth-ready) { visibility: hidden; }
.stockscanner-account { position: fixed; right: 14px; bottom: 14px; z-index: 9999; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid #3b5368; border-radius: 8px; background: #0f1923; color: #b0bec5; font: 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; box-shadow: 0 6px 22px #0008; }
.stockscanner-account button { padding: 5px 9px; border: 1px solid #4fc3f7; border-radius: 5px; color: #4fc3f7; background: transparent; cursor: pointer; }
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
