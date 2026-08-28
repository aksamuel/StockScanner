"""Generate a compatibility redirect to the user-owned Supabase exception page."""

import os

from .config import EXCEPTION_LIST


def _generate_html():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <meta http-equiv="refresh" content="0; url=my-exceptions.html">
  <title>My exceptions | StockScanner</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; padding: 40px 20px; color: #e0e0e0; background: #0f1923;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; text-align: center; }
    a { color: #81d4fa; }
  </style>
</head>
<body>
  <p>The repository exception page has moved to your private Supabase list.</p>
  <p><a href="my-exceptions.html">Open My Exceptions</a></p>
  <script>window.location.replace("my-exceptions.html");</script>
</body>
</html>
"""


def export_exceptions_dashboard(
    csv_path=EXCEPTION_LIST, output_path="exceptions.html", generated_at=None, today=None
):
    """Write the compatibility redirect and return its output path."""
    del csv_path, generated_at, today
    output_directory = os.path.dirname(output_path)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(_generate_html())
    return output_path


if __name__ == "__main__":
    export_exceptions_dashboard()
