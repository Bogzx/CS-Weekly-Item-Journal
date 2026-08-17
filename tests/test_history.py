"""Tests for the drop-history aggregation and its chart geometry."""


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
