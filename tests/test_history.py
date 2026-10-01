"""Tests for the drop-history aggregation and its chart geometry."""

import pytest

from Src.Web import history as history_lib


def bucket(week, items, total, cumulative, avg=None):
    return {
        'week': week,
        'week_start': '2026-01-01',
        'item_count': items,
        'avg_value': avg if avg is not None else (total / items if items else 0.0),
        'total_value': total,
        'cumulative_value': cumulative,
    }


class TestSummarizeHistory:
    def test_empty_history(self, appmod):
        summary = appmod.summarize_history([])

        assert summary['weeks_tracked'] == 0
        assert summary['total_items'] == 0
        assert summary['total_value'] == 0.0
        assert summary['avg_per_item'] == 0.0
        assert summary['best_week'] is None

    def test_totals_and_averages(self, appmod):
        history = [
            bucket('2026-W01', 2, 10.0, 10.0),
            bucket('2026-W02', 1, 30.0, 40.0),
            bucket('2026-W03', 1, 5.0, 45.0),
        ]

        summary = appmod.summarize_history(history)

        assert summary['weeks_tracked'] == 3
        assert summary['total_items'] == 4
        assert summary['total_value'] == 45.0
        assert summary['avg_per_item'] == 45.0 / 4
        assert summary['avg_per_week'] == 15.0
        assert summary['best_week']['week'] == '2026-W02'

    def test_no_zero_division_when_every_item_is_unpriced(self, appmod):
        history = [bucket('2026-W01', 3, 0.0, 0.0)]

        summary = appmod.summarize_history(history)

        assert summary['total_value'] == 0.0
        assert summary['avg_per_item'] == 0.0


class TestBuildHistoryChart:
    def test_returns_none_for_empty_history(self, appmod):
        assert appmod.build_history_chart([]) is None

    def test_geometry_stays_inside_the_viewbox(self, appmod):
        history = [
            bucket('2026-W01', 1, 10.0, 10.0),
            bucket('2026-W02', 1, 30.0, 40.0),
            bucket('2026-W03', 1, 5.0, 45.0),
        ]

        chart = appmod.build_history_chart(history)

        assert len(chart['bars']) == 3
        assert len(chart['points']) == 3
        for bar in chart['bars']:
            assert bar['x'] >= 0
            assert bar['y'] >= 0
            assert bar['x'] + bar['width'] <= chart['width']
            assert bar['y'] + bar['height'] <= chart['height'] + 0.01
        for point in chart['points']:
            assert 0 <= point['x'] <= chart['width']
            assert 0 <= point['y'] <= chart['height']

    def test_peak_of_cumulative_line_touches_the_top_of_the_plot(self, appmod):
        history = [
            bucket('2026-W01', 1, 10.0, 10.0),
            bucket('2026-W02', 1, 30.0, 40.0),
        ]

        chart = appmod.build_history_chart(history)

        # The last (largest) cumulative point sits at the top padding line.
        assert chart['points'][-1]['y'] == chart['pad']
        assert chart['max_cumulative'] == 40.0

    def test_single_week_is_centred_and_does_not_divide_by_zero(self, appmod):
        chart = appmod.build_history_chart([bucket('2026-W01', 1, 10.0, 10.0)])

        assert len(chart['bars']) == 1
        assert len(chart['points']) == 1
        assert chart['polyline'].count(',') == 1

    def test_all_zero_values_do_not_divide_by_zero(self, appmod):
        """Every item unpriced -> flat line on the baseline, no exception."""
        history = [
            bucket('2026-W01', 1, 0.0, 0.0),
            bucket('2026-W02', 1, 0.0, 0.0),
        ]

        chart = appmod.build_history_chart(history)

        assert all(bar['height'] == 0 for bar in chart['bars'])
        assert all(point['y'] == chart['baseline'] for point in chart['points'])

    def test_polyline_has_one_coordinate_pair_per_week(self, appmod):
        history = [bucket(f'2026-W{i:02d}', 1, float(i), float(i)) for i in range(1, 6)]

        chart = appmod.build_history_chart(history)

        assert len(chart['polyline'].split(' ')) == 5


class TestIsoWeekBuckets:
    def test_a_week_across_new_year_is_one_bucket(self, appmod):
        """Wed 2025-12-31 and Thu 2026-01-01 are the same Monday-Sunday week.
        strftime('%Y-W%W') split them into 2025-W52 and 2026-W00."""
        history = history_lib.bucket_by_iso_week([
            ('2025-12-31 20:00:00', 1.0),
            ('2026-01-01 09:00:00', 2.0),
        ])

        assert [b['week'] for b in history] == ['2026-W01']
        assert history[0]['week_start'] == '2025-12-29'
        assert history[0]['item_count'] == 2
        assert history[0]['total_value'] == 3.0

    def test_iso_year_can_differ_from_calendar_year(self, appmod):
        history = history_lib.bucket_by_iso_week([('2027-01-01 12:00:00', 1.0)])

        assert history[0]['week'] == '2026-W53'

    def test_buckets_are_ordered_and_cumulative(self, appmod):
        history = history_lib.bucket_by_iso_week([
            ('2026-03-10 10:00:00', 5.0),
            ('2026-01-05 10:00:00', 1.0),
            ('2026-01-06 10:00:00', None),
        ])

        assert [b['week'] for b in history] == ['2026-W02', '2026-W11']
        assert history[0]['item_count'] == 2
        assert history[0]['avg_value'] == 1.0      # unpriced items excluded from EV
        assert [b['cumulative_value'] for b in history] == [1.0, 6.0]

    def test_all_unpriced_week(self, appmod):
        history = history_lib.bucket_by_iso_week([('2026-01-05 10:00:00', None)])

        assert history[0]['avg_value'] == 0.0
        assert history[0]['total_value'] == 0.0

    def test_unparseable_timestamps_are_skipped(self, appmod):
        assert history_lib.bucket_by_iso_week([('garbage', 1.0)]) == []

    def test_route_renders_drop_weeks(self, appmod, logged_in):
        with logged_in.session_transaction() as sess:
            user_id = sess['user_id']
        with appmod.app.app_context():
            conn = appmod.get_db()
            conn.execute(
                "INSERT INTO user_journals (user_id, item_id, item_name, item_price, created_at) "
                "VALUES (?, 1, 'Revolution Case', 0.5, '2026-01-01 09:00:00')", (user_id,))
            conn.commit()

        html = logged_in.get('/history').get_data(as_text=True)

        # Thu 2026-01-01 is in the drop week that began Wed 2025-12-31 01:00.
        assert '2026-W01' in html
        assert '2025-12-31 01:00 UTC' in html
        assert 'Weeks start at the CS2 weekly reset' in html
        assert 'W00' not in html


class TestCs2DropWeeks:
    def test_reset_is_wednesday_0100_utc(self, appmod):
        history = appmod.bucket_by_week([
            ('2026-09-30 00:30:00', 1.0),   # Wednesday, before the reset
            ('2026-09-30 01:30:00', 2.0),   # Wednesday, after it
        ], boundary='cs2')

        assert [(b['week'], b['week_start'], b['total_value']) for b in history] == [
            ('2026-W39', '2026-09-23 01:00 UTC', 1.0),
            ('2026-W40', '2026-09-30 01:00 UTC', 2.0),
        ]

    def test_monday_and_tuesday_belong_to_the_previous_drop_week(self, appmod):
        """ISO weeks split one drop week (Wed-Tue) across two buckets."""
        rows = [('2026-09-23 12:00:00', 1.0), ('2026-09-28 12:00:00', 1.0), ('2026-09-29 23:00:00', 1.0)]

        assert len(appmod.bucket_by_week(rows, boundary='cs2')) == 1
        assert len(appmod.bucket_by_week(rows, boundary='iso')) == 2

    def test_iso_fallback(self, appmod):
        history = appmod.bucket_by_week([('2026-09-30 00:30:00', 1.0)], boundary='iso')

        assert history[0]['week'] == '2026-W40'
        assert history[0]['week_start'] == '2026-09-28'

    @pytest.mark.parametrize('raw,expected', [(None, 'cs2'), ('ISO', 'iso'), ('bogus', 'cs2')])
    def test_resolve(self, appmod, raw, expected):
        assert appmod.resolve_week_boundary(raw) == expected

    def test_default_is_cs2(self, appmod):
        assert appmod.app.config['WEEK_BOUNDARY'] == 'cs2'
