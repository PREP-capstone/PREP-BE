"""시드 임포터의 bm_mapping 집계(#145) — competitors에서 db_구축_설계서.md §3.6 식대로 계산하는지."""

from datetime import date

from scripts import import_postgres_seed_data as seed


def _competitor(competitor_id: str, country: str = "한국", **overrides) -> dict:
    row = {
        "competitor_id": competitor_id,
        "category_1": "수면",
        "category_2": "정보제공",
        "target": "직장인",
        "service_type": "앱단독",
        "bm_pattern": "Freemium(프리미엄)",
        "country": country,
    }
    return {**row, **overrides}


def test_aggregate_counts_domestic_and_global_per_combo() -> None:
    rows = seed.aggregate_bm_mapping(
        [
            _competitor("CP003"),
            _competitor("CP004", country="미국"),
            _competitor("CP005", bm_pattern="Subscription(구독형)", country="미국"),
        ],
        computed_at=date(2026, 10, 6),
    )

    assert [row["mapping_id"] for row in rows] == ["BM001", "BM002"]
    first, second = rows
    assert (first["frequency_score"], first["frequency_score_global"], first["precedent_level"]) == (1, 2, "적음")
    assert first["contributing_competitor_ids"] == "CP003,CP004"
    # 국내 0건, 해외만 있으면 '가능'
    assert (second["frequency_score"], second["frequency_score_global"], second["precedent_level"]) == (0, 1, "가능")
    assert first["last_computed_at"] == date(2026, 10, 6)


def test_aggregate_skips_rows_missing_any_lookup_key() -> None:
    rows = seed.aggregate_bm_mapping([_competitor("CP003", target=None), _competitor("CP004", bm_pattern=None)])
    assert rows == []


def test_precedent_level_thresholds() -> None:
    assert [seed.precedent_level(n, n) for n in (5, 4, 3, 2, 1)] == ["많음", "중간", "중간", "적음", "적음"]
    assert seed.precedent_level(0, 2) == "가능"
    assert seed.precedent_level(0, 0) == "어려움"


def test_seed_sheet_excludes_example_rows_and_covers_every_competitor() -> None:
    competitors = seed.load_competitors(seed.DEFAULT_DATA_DIR)
    assert not [c for c in competitors if (c["note"] or "").startswith(seed.EXAMPLE_ROW_NOTE_PREFIX)]

    mapping = seed.aggregate_bm_mapping(competitors)
    contributing = {cid for row in mapping for cid in row["contributing_competitor_ids"].split(",")}
    eligible = {
        c["competitor_id"]
        for c in competitors
        if all(c[key] for key in ("category_1", "category_2", "target", "service_type", "bm_pattern"))
    }
    assert contributing == eligible
