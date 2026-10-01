"""The weekly drop history: buckets, headline numbers and the chart."""

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def parse_timestamp(value):
    """Parse a SQLite CURRENT_TIMESTAMP string (or a datetime) into a datetime."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None


# How the history page cuts time into weeks.
#   cs2 - CS2's weekly care-package reset (default). Public trackers agree it
#         is Wednesday 01:00 GMT (Tuesday 6 PM Pacific): gamerevolution.com,
#         weeklyreset.net, skinsmetric.com, checked 2026-09-30. None says
#         whether it moves with daylight saving; CS2_RESET_HOUR_UTC adjusts it.
#   iso - ISO weeks, Monday 00:00 UTC.
WEEK_BOUNDARIES = ('cs2', 'iso')
CS2_RESET_WEEKDAY = 2  # Monday = 0, so Wednesday
CS2_RESET_HOUR_UTC = int(os.environ.get('CS2_RESET_HOUR_UTC', '1'))


def resolve_week_boundary(raw):
    boundary = (raw or 'cs2').strip().lower()
    if boundary not in WEEK_BOUNDARIES:
        logger.warning(
            "Unknown WEEK_BOUNDARY %r; using 'cs2'. Valid values: %s", raw, ', '.join(WEEK_BOUNDARIES))
        return 'cs2'
    return boundary



def bucket_by_week(rows, boundary='cs2'):
    """Aggregate (created_at, item_price) rows into weekly buckets.

    Timestamps are UTC (SQLite CURRENT_TIMESTAMP). With boundary 'iso' a week
    runs Monday 00:00 to Sunday 23:59 and is labelled with its ISO week; with
    'cs2' it runs from one care-package reset to the next and is labelled
    with the ISO week of the Wednesday it starts on, with `week_start` being
    that reset.

    Weeks used to come from SQLite's strftime('%Y-W%W'), which is not an ISO
    week: it counts from the year's first Monday, so the days before it fall
    into a "W00" and one week straddling New Year was split into two buckets.

    Returns buckets oldest-first, each with the week label, its start, the
    number of items, their total value, the mean over priced items (the
    realised expected value of a drop) and the running cumulative total.
    """
    # Shift time so the chosen week start lands on Monday 00:00; ISO weeks of
    # the shifted time are then the wanted weeks.
    shift = (timedelta(days=CS2_RESET_WEEKDAY, hours=CS2_RESET_HOUR_UTC)
             if boundary == 'cs2' else timedelta(0))

    weeks = {}
    for created_at, price in rows:
        stamp = parse_timestamp(created_at)
        if stamp is None:
            continue
        iso_year, iso_week, _ = (stamp - shift).isocalendar()
        bucket = weeks.setdefault((iso_year, iso_week), {'count': 0, 'prices': []})
        bucket['count'] += 1
        if price is not None:
            bucket['prices'].append(float(price))

    history = []
    running_total = 0.0
    for (iso_year, iso_week) in sorted(weeks):
        bucket = weeks[(iso_year, iso_week)]
        total = sum(bucket['prices'])
        running_total += total
        start = datetime.fromisocalendar(iso_year, iso_week, 1) + shift
        history.append({
            'week': f'{iso_year}-W{iso_week:02d}',
            'week_start': start.strftime('%Y-%m-%d %H:%M UTC') if shift else start.date().isoformat(),
            'item_count': bucket['count'],
            # Mean over *priced* items only, which is what you want for an EV
            # figure (unpriced items would drag it towards zero).
            'avg_value': total / len(bucket['prices']) if bucket['prices'] else 0.0,
            'total_value': total,
            'cumulative_value': running_total,
        })
    return history


def bucket_by_iso_week(rows):
    """bucket_by_week with ISO (Monday) weeks."""
    return bucket_by_week(rows, boundary='iso')


def summarize_history(history):
    """Headline numbers for the history page."""
    if not history:
        return {
            'weeks_tracked': 0,
            'total_items': 0,
            'total_value': 0.0,
            'avg_per_item': 0.0,
            'avg_per_week': 0.0,
            'best_week': None,
        }

    total_items = sum(bucket['item_count'] for bucket in history)
    total_value = history[-1]['cumulative_value']

    return {
        'weeks_tracked': len(history),
        'total_items': total_items,
        'total_value': total_value,
        'avg_per_item': (total_value / total_items) if total_items else 0.0,
        'avg_per_week': total_value / len(history),
        'best_week': max(history, key=lambda bucket: bucket['total_value']),
    }


def build_history_chart(history, width=760, height=260, pad=44):
    """Pre-compute SVG geometry for the history chart.

    The app ships no charting library and the templates load nothing from a
    CDN, so the coordinates are worked out here and the template simply emits
    them. Bars are the per-week value; the line is the cumulative total.
    """
    if not history:
        return None

    inner_w = width - pad * 2
    inner_h = height - pad * 2
    baseline = pad + inner_h
    count = len(history)

    # `or 1.0` keeps an all-zero journal (every item unpriced) from dividing
    # by zero and instead draws a flat line along the baseline.
    max_cumulative = max(b['cumulative_value'] for b in history) or 1.0
    max_weekly = max(b['total_value'] for b in history) or 1.0

    step = inner_w / (count - 1) if count > 1 else 0
    bar_width = max(6.0, min(44.0, (inner_w / count) * 0.55))

    points = []
    bars = []
    for index, bucket in enumerate(history):
        x = pad + (step * index if count > 1 else inner_w / 2)
        y = baseline - (bucket['cumulative_value'] / max_cumulative) * inner_h
        points.append((round(x, 2), round(y, 2)))

        bar_height = (bucket['total_value'] / max_weekly) * inner_h
        bars.append({
            'x': round(x - bar_width / 2, 2),
            'y': round(baseline - bar_height, 2),
            'width': round(bar_width, 2),
            'height': round(bar_height, 2),
            'label': bucket['week'],
            'value': bucket['total_value'],
        })

    return {
        'width': width,
        'height': height,
        'pad': pad,
        'baseline': baseline,
        'max_cumulative': max_cumulative,
        'max_weekly': max_weekly,
        'polyline': ' '.join(f'{x},{y}' for x, y in points),
        'points': [{'x': x, 'y': y} for x, y in points],
        'bars': bars,
    }
