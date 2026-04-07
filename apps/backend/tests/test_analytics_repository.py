from app.repositories.analytics_repository import AnalyticsRepository


def test_merge_cumulative_series_uses_tracker_snapshot_as_floor() -> None:
    explicit_series = [
        {"apply_date": "2026-03-08", "applied_count": 1, "cumulative_count": 1},
        {"apply_date": "2026-03-09", "applied_count": 4, "cumulative_count": 5},
    ]
    tracker_snapshot_series = [
        {"apply_date": "2026-02-28", "applied_count": 6, "cumulative_count": 6},
        {"apply_date": "2026-03-08", "applied_count": 4, "cumulative_count": 10},
    ]

    merged = AnalyticsRepository._merge_cumulative_series(explicit_series, tracker_snapshot_series)

    assert merged[-1] == {
        "apply_date": "2026-03-09",
        "applied_count": 0,
        "cumulative_count": 10,
    }
    assert merged[-2] == {
        "apply_date": "2026-03-08",
        "applied_count": 4,
        "cumulative_count": 10,
    }
