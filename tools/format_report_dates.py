"""Normalize published report presentation without changing dates in data or URLs."""
from datetime import datetime
from pathlib import Path
import re

CHART_LABELS = "chartData.labels.map((value) => { const [year, month, day] = value.split('-'); return day + '/' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(month) - 1] + '/' + year; })"


def format_report(source):
    source = source.replace('labels: chartData.labels,', 'labels: ' + CHART_LABELS + ',')
    source = re.sub(r'\b(\d{2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})\b', lambda m: f'{m[1]}/{m[2][:3]}/{m[3]}', source)
    source = re.sub(r'(?<=>)(\d{4}-\d{2}-\d{2})(?=<)', lambda m: datetime.strptime(m[1], '%Y-%m-%d').strftime('%d/%b/%Y'), source)
    return re.sub(r'(Reports for |Generated at: |Generated: |Generated on )(\d{4}-\d{2}-\d{2})', lambda m: m[1] + datetime.strptime(m[2], '%Y-%m-%d').strftime('%d/%b/%Y'), source)


def main():
    root = Path(__file__).resolve().parents[1]
    for path in [*(root / 'reports').rglob('*.html'), *(root / name for name in ['index.html', 'technical.html', 'analysts.html', 'bought-selection.html'])]:
        if not path.is_file():
            continue
        source = path.read_text(encoding='utf-8')
        formatted = format_report(source)
        if formatted != source:
            path.write_text(formatted, encoding='utf-8')


if __name__ == '__main__':
    main()
