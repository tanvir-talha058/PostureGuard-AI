from datetime import date

from postureguard.ai.cue_variants import CueVariantCache, generate_variants, pick
from postureguard.rules import FaultKind


class TestCueVariantCachePersistence:
    def test_round_trips_through_a_file(self, tmp_path):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Pull back."], "action": ["Pull back"]}},
            generated_at="2026-08-02",
        )
        path = tmp_path / "cue_variants.json"
        cache.save(path)
        loaded = CueVariantCache.load(path)
        assert loaded.variants == cache.variants
        assert loaded.generated_at == "2026-08-02"

    def test_missing_file_loads_an_empty_cache(self, tmp_path):
        cache = CueVariantCache.load(tmp_path / "missing.json")
        assert cache.variants == {}

    def test_corrupt_file_loads_an_empty_cache(self, tmp_path):
        path = tmp_path / "cue_variants.json"
        path.write_text("not json", encoding="utf-8")
        assert CueVariantCache.load(path).variants == {}


class TestPick:
    def test_returns_canonical_when_cache_is_none(self):
        assert pick(None, FaultKind.FORWARD_HEAD, "Pull your chin back.") == "Pull your chin back."

    def test_returns_canonical_when_no_variants_for_the_kind(self):
        cache = CueVariantCache(variants={})
        assert pick(cache, FaultKind.FORWARD_HEAD, "canonical") == "canonical"

    def test_returns_a_cached_variant_deterministically_by_day(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Variant A", "Variant B"]}}
        )
        first = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        again = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        assert first == again
        assert first in ("Variant A", "Variant B")

    def test_different_days_can_pick_different_variants(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["Variant A", "Variant B"]}}
        )
        day_one = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 2))
        day_two = pick(cache, FaultKind.FORWARD_HEAD, "canonical", today=date(2026, 8, 3))
        assert {day_one, day_two} == {"Variant A", "Variant B"}

    def test_reads_the_action_field_separately_from_cue(self):
        cache = CueVariantCache(
            variants={"forward_head": {"cue": ["cue variant"], "action": ["action variant"]}}
        )
        assert pick(cache, FaultKind.FORWARD_HEAD, "x", field="action") == "action variant"


class TestGenerateVariants:
    def test_returns_none_when_ask_fails(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: None)
        assert generate_variants("sk-ant-test") is None

    def test_returns_none_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: "not json")
        assert generate_variants("sk-ant-test") is None

    def test_parses_a_valid_response_into_a_cache(self, monkeypatch):
        import json

        response = json.dumps(
            {"forward_head": {"cue": ["A", "B"], "action": ["a", "b"]}}
        )
        monkeypatch.setattr("postureguard.ai.cue_variants.ask", lambda *a, **k: response)
        cache = generate_variants("sk-ant-test")
        assert cache is not None
        assert cache.variants["forward_head"]["cue"] == ["A", "B"]
        assert cache.generated_at
