from datetime import datetime
import importlib.util
from pathlib import Path

import pytest

from stockscanner.display_time import format_new_york_time

spec = importlib.util.spec_from_file_location('format_report_dates', Path(__file__).resolve().parents[1] / 'tools/format_report_dates.py')
report_dates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_dates)


@pytest.mark.parametrize('timestamp,expected', [
    ('2026-09-05T18:07:59+00:00', '05/Sep/2026, 14:07 EDT'),
    ('2026-01-05T18:07:59+00:00', '05/Jan/2026, 13:07 EST'),
    ('2026-01-01T04:59:59+00:00', '31/Dec/2025, 23:59 EST'),
    ('2026-09-05T04:00:59+00:00', '05/Sep/2026, 00:00 EDT'),
    ('2026-03-08T06:59:59+00:00', '08/Mar/2026, 01:59 EST'),
    ('2026-03-08T07:00:00+00:00', '08/Mar/2026, 03:00 EDT'),
    ('2026-11-01T05:30:00+00:00', '01/Nov/2026, 01:30 EDT'),
    ('2026-11-01T06:30:00+00:00', '01/Nov/2026, 01:30 EST'),
])
def test_new_york_clock_handles_dst_and_date_rollover(timestamp, expected):
    assert format_new_york_time(datetime.fromisoformat(timestamp)) == expected


def test_legacy_report_times_are_normalized_without_changing_data_or_urls():
    source = '''<title>StockScanner Dashboard - 04 September 2026, 04:25 AM EDT</title>
<p>Generated on 2026-09-04 08:25:17</p>
<p>Scan completed: 04 August 2026, 06:13 PM</p>
<p>Generated on 2026-01-01 01:07:59 UTC</p>
<a href="reports/2026-09-04_08-25-17.html">Open</a>
<time datetime="2026-09-04T08:25:17Z">Original data</time>
<script>const raw = "2026-09-04 08:25:17";</script>'''
    result = report_dates.format_report(source)
    assert '04/Sep/2026, 04:25 EDT' in result
    assert 'Generated on 04/Sep/2026, 04:25 EDT' in result
    assert 'Scan completed: 04/Aug/2026, 14:13 EDT' in result
    assert 'Generated on 31/Dec/2025, 20:07 EST' in result
    assert 'href="reports/2026-09-04_08-25-17.html"' in result
    assert 'datetime="2026-09-04T08:25:17Z"' in result
    assert 'const raw = "2026-09-04 08:25:17"' in result
    assert report_dates.format_report(result) == result


def test_archived_snapshot_displays_use_iso_timestamps_and_are_idempotent():
    source = """<script>
        const snapshot = await response.json();
        element.textContent = snapshot.generated_at_new_york;
</script>"""
    result = report_dates.format_report(source)
    assert "formatDateTime(snapshot.generated_at)" in result
    assert "formatDateTime(snapshot.price_timestamp)" in result
    assert report_dates.format_report(result) == result
