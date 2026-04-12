import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.repositories.database import Database
from app.repositories.analytics_repository import AnalyticsRepository
from app.services.analytics_service import AnalyticsService


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


def test_programming_language_hiring_trends_aggregates_regions_and_daily_series(tmp_path: Path) -> None:
    db_path = tmp_path / "analytics_language.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE job_posts (
              id INTEGER PRIMARY KEY,
              location TEXT,
              first_seen_date TEXT,
              last_seen_date TEXT
            );
            CREATE TABLE job_programming_languages (
              job_post_id INTEGER NOT NULL,
              language TEXT NOT NULL
            );
            CREATE TABLE job_location_enrichment (
              job_post_id INTEGER PRIMARY KEY,
              normalized_country TEXT NOT NULL,
              normalized_region TEXT
            );
            CREATE TABLE geo_region_country_map (
              normalized_region TEXT NOT NULL,
              normalized_country TEXT NOT NULL,
              source TEXT,
              updated_at TEXT
            );
            """
        )
        today = date.today()
        rows = [
            (1, "San Francisco, CA", (today - timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat()),
            (2, "New York, NY", (today - timedelta(days=8)).isoformat(), (today - timedelta(days=8)).isoformat()),
            (3, "Berlin, Germany", (today - timedelta(days=15)).isoformat(), (today - timedelta(days=15)).isoformat()),
            (4, "Berlin, Germany", (today - timedelta(days=18)).isoformat(), (today - timedelta(days=18)).isoformat()),
            (5, "Austin, TX", (today - timedelta(days=50)).isoformat(), (today - timedelta(days=50)).isoformat()),
        ]
        conn.executemany("INSERT INTO job_posts (id, location, first_seen_date, last_seen_date) VALUES (?, ?, ?, ?)", rows)
        conn.executemany(
            "INSERT INTO job_programming_languages (job_post_id, language) VALUES (?, ?)",
            [
                (1, "Python"),
                (2, "Python"),
                (2, "TypeScript"),
                (3, "TypeScript"),
                (4, "Go"),
                (5, "Java"),
            ],
        )
        conn.executemany(
            "INSERT INTO job_location_enrichment (job_post_id, normalized_country, normalized_region) VALUES (?, ?, ?)",
            [
                (1, "United States", "North America"),
                (2, "United States", "North America"),
                (3, "Germany", "Western Europe"),
                (4, "Germany", "Western Europe"),
                (5, "United States", "North America"),
            ],
        )
        conn.executemany(
            "INSERT INTO geo_region_country_map (normalized_region, normalized_country, source, updated_at) VALUES (?, ?, ?, ?)",
            [
                ("North America", "United States", "test", today.isoformat()),
                ("Western Europe", "Germany", "test", today.isoformat()),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    repo = AnalyticsRepository(Database(str(db_path)))
    trend = repo.programming_language_hiring_trends(days=30, top_n=3)

    assert [item["language"] for item in trend["top_languages"]] == ["Python", "TypeScript", "Go"]
    assert trend["jobs_considered"] == 4
    assert trend["geo_coverage"]["other_region_mentions"] == 0
    assert trend["top_languages"][0]["dominant_region"] == "North America"
    assert trend["top_languages"][1]["dominant_region"] in {"North America", "Western Europe"}
    assert trend["daily_series"][0]["date"] <= trend["daily_series"][-1]["date"]
    assert any(point["languages"]["Python"] > 0 for point in trend["daily_series"])
    python_regions = next(item for item in trend["region_breakdown"] if item["language"] == "Python")
    assert python_regions["regions"][0]["region"] == "North America"


def test_programming_stack_hiring_trends_classifies_full_stack_and_role_groups(tmp_path: Path) -> None:
    db_path = tmp_path / "analytics_stack.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE job_posts (
              id INTEGER PRIMARY KEY,
              company TEXT,
              location TEXT,
              title TEXT,
              latest_payload_json TEXT,
              first_seen_date TEXT,
              last_seen_date TEXT
            );
            CREATE TABLE job_programming_languages (
              job_post_id INTEGER NOT NULL,
              language TEXT NOT NULL
            );
            CREATE TABLE job_location_enrichment (
              job_post_id INTEGER PRIMARY KEY,
              normalized_country TEXT NOT NULL,
              normalized_region TEXT
            );
            CREATE TABLE geo_region_country_map (
              normalized_region TEXT NOT NULL,
              normalized_country TEXT NOT NULL,
              source TEXT,
              updated_at TEXT
            );
            """
        )
        today = date.today()
        rows = [
            (1, "Acme", "San Francisco, United States", "Full Stack Engineer", '{"skills":["react","fastapi"]}', (today - timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat()),
            (2, "Acme", "New York, United States", "Frontend Engineer", '{"skills":["react","typescript"]}', (today - timedelta(days=3)).isoformat(), (today - timedelta(days=3)).isoformat()),
            (3, "Acme", "Austin, United States", "Backend Engineer", '{"skills":["python","api","sql"]}', (today - timedelta(days=5)).isoformat(), (today - timedelta(days=5)).isoformat()),
            (4, "Acme", "Berlin, Germany", "AI Engineer", '{"skills":["llm","python"]}', (today - timedelta(days=7)).isoformat(), (today - timedelta(days=7)).isoformat()),
        ]
        conn.executemany(
            "INSERT INTO job_posts (id, company, location, title, latest_payload_json, first_seen_date, last_seen_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.executemany(
            "INSERT INTO job_programming_languages (job_post_id, language) VALUES (?, ?)",
            [
                (1, "React"),
                (1, "Python"),
                (2, "TypeScript"),
                (3, "Python"),
                (3, "SQL"),
                (4, "Python"),
            ],
        )
        conn.executemany(
            "INSERT INTO job_location_enrichment (job_post_id, normalized_country, normalized_region) VALUES (?, ?, ?)",
            [
                (1, "United States", "North America"),
                (2, "United States", "North America"),
                (3, "United States", "North America"),
                (4, "Germany", "Western Europe"),
            ],
        )
        conn.executemany(
            "INSERT INTO geo_region_country_map (normalized_region, normalized_country, source, updated_at) VALUES (?, ?, ?, ?)",
            [
                ("North America", "United States", "test", today.isoformat()),
                ("Western Europe", "Germany", "test", today.isoformat()),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    repo = AnalyticsRepository(Database(str(db_path)))
    trend = repo.programming_stack_hiring_trends(days=30, top_n=4)

    assert [item["group"] for item in trend["top_groups"]][:4] == [
        "Full Stack",
        "Frontend (FE)",
        "Backend (BE)",
        "AI/ML",
    ]
    assert trend["jobs_considered"] == 4
    assert trend["classified_jobs"] == 4
    assert trend["geo_coverage"]["other_group_share_pct"] == 0.0
    assert trend["top_groups"][0]["dominant_region"] == "North America"
    assert trend["daily_series"][0]["date"] <= trend["daily_series"][-1]["date"]
    assert any(point["groups"]["Full Stack"] > 0 for point in trend["daily_series"])
    full_stack_regions = next(item for item in trend["region_breakdown"] if item["group"] == "Full Stack")
    assert full_stack_regions["regions"][0]["region"] == "North America"


def test_extract_curated_facts_returns_topic_scoped_notes() -> None:
    facts = AnalyticsService._extract_curated_facts(
        "TypeScript overtook both Python and JavaScript in August 2025 to become the most used language on GitHub. Python remains dominant for AI and data science workloads.",
        {
            "patterns": [
                ("TypeScript", r"TypeScript overtook both Python and JavaScript in August 2025 to become the most used language on GitHub"),
                ("Python", r"Python remains dominant for AI and data science workloads"),
            ]
        },
    )

    assert facts == [
        {
            "topic": "TypeScript",
            "text": "TypeScript overtook both Python and JavaScript in August 2025 to become the most used language on GitHub",
        },
        {
            "topic": "Python",
            "text": "Python remains dominant for AI and data science workloads",
        },
    ]


def test_market_sources_return_stale_cache_while_refreshing(monkeypatch) -> None:
    service = AnalyticsService(None)
    cached_sources = [
        {
            "id": "cached_source",
            "publisher": "Cached",
            "title": "Cached title",
            "url": "https://example.com",
            "status": "ok",
            "facts": [],
            "error": "",
            "fetched_at": "2026-04-12T00:00:00Z",
            "duration_ms": 12,
        }
    ]
    service._market_context_cache = {"expires_at": 1.0, "sources": cached_sources}
    service._market_context_refreshing = False

    refresh_calls: list[bool] = []

    def fake_start_refresh(self) -> None:  # noqa: ANN001
        refresh_calls.append(True)
        with self._market_context_lock:
            self._market_context_refreshing = False

    def fake_fetch_market_source(self, spec: dict[str, object]) -> dict[str, object]:  # noqa: ANN001
        raise AssertionError(f"Unexpected fetch for {spec.get('id')}")

    monkeypatch.setattr(AnalyticsService, "_start_market_sources_refresh", fake_start_refresh)
    monkeypatch.setattr(AnalyticsService, "_fetch_market_source", fake_fetch_market_source)

    result = service._load_market_sources()

    assert result == cached_sources
    assert refresh_calls == [True]


def test_trend_ai_insights_reads_snapshot_from_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "analytics_trend_ai.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE analytics_trend_ai_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              cache_key TEXT NOT NULL UNIQUE,
              trend_kind TEXT NOT NULL,
              summary_json TEXT NOT NULL,
              result_json TEXT NOT NULL,
              model TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'nightly',
              cache_state TEXT NOT NULL DEFAULT 'db',
              generated_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    repo = AnalyticsRepository(Database(str(db_path)))
    service = AnalyticsService(repo)
    trend = {
        "days": 90,
        "date_start": "2026-01-01",
        "date_end": "2026-03-31",
        "jobs_considered": 12,
        "top_languages": [
            {
                "language": "Python",
                "jobs": 5,
                "share_pct": 41.7,
                "momentum_pct": 12.5,
                "dominant_region": "North America",
                "dominant_region_share_pct": 60.0,
                "region_spread": 3,
                "signal_mix_samples": ["backend", "data"],
            }
        ],
        "geo_coverage": {"other_region_share_pct": 8.0},
        "crawl_recommendations": [{"language": "Python", "reason": "Need deeper regional coverage"}],
    }
    context = {
        "macro_cards": [{"title": "AI demand", "body": "Python remains dominant for AI and data science workloads"}],
        "items": [
            {
                "language": "Python",
                "headline": "Python is accelerating locally",
                "regional_story": "Python clusters around AI-heavy regions.",
                "local_reasons": ["Python appears in recent jobs."],
                "external_reasons": ["Python remains dominant for AI and data science workloads"],
            }
        ],
        "sources": [
            {
                "publisher": "GitHub",
                "title": "Octoverse 2025",
                "status": "ok",
                "facts": [{"text": "TypeScript overtook both Python and JavaScript in August 2025"}],
            }
        ],
    }

    summary = service._build_trend_ai_summary(trend_kind="language", trend=trend, context=context)
    cache_key = service._trend_ai_cache_key(summary=summary)
    stored_result = service._fallback_trend_ai(summary=summary)
    stored_result.update(
        {
            "thesis": "Python demand is still tied to AI and backend delivery.",
            "confidence": 0.82,
            "dimension_notes": [
                {
                    "dimension": "economic",
                    "reading": "Hiring reflects product delivery pressure.",
                    "evidence_basis": "Trend snapshot",
                    "confidence": 0.78,
                }
            ],
            "crawl_expansions": [
                {
                    "priority": "high",
                    "target": "earnings calls",
                    "source_types": ["earnings call transcripts"],
                    "question": "What budget or strategy signal explains the demand?",
                    "why_it_matters": "It anchors the macro explanation.",
                }
            ],
            "limitations": ["Directional only"],
            "what_would_change_view": ["More sources confirm the signal"],
            "model": "qwen2.5:1.5b-instruct",
            "generated_at": "2026-04-12T00:00:00Z",
            "cache_state": "nightly",
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
        }
    )
    repo.upsert_trend_ai_snapshot(
        cache_key=cache_key,
        trend_kind="language",
        summary=summary,
        result=stored_result,
        model="qwen2.5:1.5b-instruct",
        source="nightly",
        cache_state="nightly",
        expires_at="2026-04-13T00:00:00Z",
    )

    monkeypatch.setattr(service, "_call_trend_ai_model", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not call model")))

    result = service.trend_ai_insights(trend_kind="language", trend=trend, context=context)

    assert result["trend_kind"] == "language"
    assert result["thesis"].startswith("Python demand")
    assert result["dimension_notes"][0]["dimension"] == "economic"
    assert result["crawl_expansions"][0]["target"] == "earnings calls"
    assert result["cache_state"] == "nightly"
    assert result["model"] == "qwen2.5:1.5b-instruct"


def test_refresh_trend_ai_snapshots_persists_nightly_results(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "analytics_trend_ai_refresh.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE analytics_trend_ai_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              cache_key TEXT NOT NULL UNIQUE,
              trend_kind TEXT NOT NULL,
              summary_json TEXT NOT NULL,
              result_json TEXT NOT NULL,
              model TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'nightly',
              cache_state TEXT NOT NULL DEFAULT 'db',
              generated_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    repo = AnalyticsRepository(Database(str(db_path)))
    service = AnalyticsService(repo)

    def fake_language_trends(*, days, top_n, countries):  # noqa: ANN001
        return {
            "days": days,
            "date_start": "2026-04-01",
            "date_end": "2026-04-12",
            "jobs_considered": 10,
            "language_mentions": 12,
            "unique_language_count": 3,
            "top_languages": [
                {
                    "language": "Python",
                    "jobs": 5,
                    "share_pct": 41.7,
                    "momentum_pct": 12.5,
                    "dominant_region": "North America",
                    "dominant_region_share_pct": 60.0,
                    "region_spread": 3,
                    "signal_mix_samples": ["backend", "data"],
                }
            ],
            "daily_series": [],
            "region_breakdown": [
                {
                    "language": "Python",
                    "regions": [
                        {
                            "region": "North America",
                            "jobs": 4,
                            "countries": [{"country": "United States", "jobs": 4}],
                            "share_pct": 100.0,
                        }
                    ],
                }
            ],
            "regional_totals": [],
            "geo_coverage": {"other_region_share_pct": 8.0},
            "crawl_recommendations": [{"language": "Python", "reason": "Need deeper regional coverage"}],
        }

    def fake_stack_trends(*, days, top_n, countries):  # noqa: ANN001
        return {
            "days": days,
            "date_start": "2026-04-01",
            "date_end": "2026-04-12",
            "jobs_considered": 10,
            "group_mentions": 12,
            "unique_group_count": 3,
            "classified_jobs": 8,
            "top_groups": [
                {
                    "group": "Full Stack",
                    "jobs": 5,
                    "share_pct": 41.7,
                    "momentum_pct": 12.5,
                    "dominant_region": "North America",
                    "dominant_region_share_pct": 60.0,
                    "region_spread": 3,
                    "trend_direction": "up",
                    "signal_mix_samples": ["frontend + backend"],
                }
            ],
            "daily_series": [],
            "region_breakdown": [
                {
                    "group": "Full Stack",
                    "regions": [
                        {
                            "region": "North America",
                            "jobs": 4,
                            "countries": [{"country": "United States", "jobs": 4}],
                            "share_pct": 100.0,
                        }
                    ],
                }
            ],
            "regional_totals": [],
            "geo_coverage": {"other_group_share_pct": 8.0},
            "crawl_recommendations": [{"group": "Full Stack", "reason": "Need deeper regional coverage"}],
        }

    def fake_language_context(*, days, top_n, countries, force_refresh=False):  # noqa: ANN001
        return {
            "generated_at": "2026-04-12T00:00:00Z",
            "cache_ttl_seconds": 60,
            "sources": [
                {
                    "publisher": "GitHub",
                    "title": "Octoverse 2025",
                    "status": "ok",
                    "facts": [{"text": "TypeScript overtook both Python and JavaScript in August 2025"}],
                }
            ],
            "macro_cards": [{"title": "AI demand", "body": "Python remains dominant for AI and data science workloads"}],
            "items": [
                {
                    "language": "Python",
                    "headline": "Python is accelerating locally",
                    "regional_story": "Python clusters around AI-heavy regions.",
                    "local_reasons": ["Python appears in recent jobs."],
                    "external_reasons": ["Python remains dominant for AI and data science workloads"],
                }
            ],
        }

    def fake_stack_context(*, days, top_n, countries, force_refresh=False):  # noqa: ANN001
        return {
            "generated_at": "2026-04-12T00:00:00Z",
            "cache_ttl_seconds": 60,
            "sources": [
                {
                    "publisher": "GitHub",
                    "title": "Octoverse 2025",
                    "status": "ok",
                    "facts": [{"text": "TypeScript overtook both Python and JavaScript in August 2025"}],
                }
            ],
            "macro_cards": [{"title": "Frontend and full-stack demand", "body": "Typed stacks stay broad"}],
            "items": [
                {
                    "group": "Full Stack",
                    "headline": "Full Stack is accelerating locally",
                    "regional_story": "Full Stack roles cluster around product teams.",
                    "local_reasons": ["Full Stack appears in recent jobs."],
                    "external_reasons": ["Typed stacks stay broad"],
                }
            ],
        }

    def fake_call_trend_ai_model(*, summary):  # noqa: ANN001
        return (
            {
                "thesis": f"{summary['kind']} demand is still broad.",
                "confidence": 0.78,
                "dimension_notes": [
                    {
                        "dimension": "economic",
                        "reading": "Hiring reflects product delivery pressure.",
                        "evidence_basis": "Trend snapshot",
                        "confidence": 0.78,
                    }
                ],
                "crawl_expansions": [
                    {
                        "priority": "high",
                        "target": "earnings calls",
                        "source_types": ["earnings call transcripts"],
                        "question": "What budget or strategy signal explains the demand?",
                        "why_it_matters": "It anchors the macro explanation.",
                    }
                ],
                "limitations": ["Directional only"],
                "what_would_change_view": ["More sources confirm the signal"],
                "model": "qwen2.5:1.5b-instruct",
                "generated_at": "2026-04-12T00:00:00Z",
            },
            {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
            "qwen2.5:1.5b-instruct",
        )

    monkeypatch.setattr(service, "programming_language_hiring_trends", fake_language_trends)
    monkeypatch.setattr(service, "programming_stack_hiring_trends", fake_stack_trends)
    monkeypatch.setattr(service, "language_market_context", fake_language_context)
    monkeypatch.setattr(service, "stack_market_context", fake_stack_context)
    monkeypatch.setattr(service, "_call_trend_ai_model", fake_call_trend_ai_model)

    result = service.refresh_trend_ai_snapshots()

    assert result["count"] == 8
    latest_language = repo.get_latest_trend_ai_snapshot("language")
    latest_stack = repo.get_latest_trend_ai_snapshot("stack")
    assert latest_language is not None
    assert latest_stack is not None
    assert latest_language["cache_state"] == "nightly"
    assert latest_stack["cache_state"] == "nightly"
