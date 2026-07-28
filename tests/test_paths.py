from __future__ import annotations

import pytest

from postureguard import paths


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTUREGUARD_HOME", str(tmp_path))
    return tmp_path


class TestSanitizeProfileName:
    def test_keeps_ordinary_names_readable(self):
        assert paths.sanitize_profile_name("Home Office") == "Home Office"

    def test_strips_path_separators(self):
        assert "/" not in paths.sanitize_profile_name("a/b")
        assert "\\" not in paths.sanitize_profile_name("a\\b")

    def test_empty_input_still_yields_something_usable(self):
        assert paths.sanitize_profile_name("") == "profile"

    def test_purely_invalid_input_still_yields_something_usable(self):
        assert paths.sanitize_profile_name("///") == "profile"


class TestBaselinePath:
    def test_the_default_profile_uses_the_original_top_level_path(self, isolated_home):
        """Upgrading to named profiles must never orphan an existing calibration or
        force a surprise recalibration on the profile every install already has."""
        assert paths.baseline_path(paths.DEFAULT_PROFILE) == isolated_home / "baseline.json"
        assert paths.baseline_path() == paths.baseline_path(paths.DEFAULT_PROFILE)

    def test_a_named_profile_lives_under_a_baselines_subdirectory(self, isolated_home):
        path = paths.baseline_path("standing")
        assert path.parent == paths.baselines_dir()
        assert path.name == "standing.json"

    def test_different_profiles_never_collide(self, isolated_home):
        assert paths.baseline_path("home") != paths.baseline_path("office")


class TestListProfiles:
    def test_default_is_always_present_even_unbaselined(self, isolated_home):
        assert paths.list_profiles() == [paths.DEFAULT_PROFILE]

    def test_lists_every_profile_with_a_saved_baseline(self, isolated_home):
        paths.baseline_path("standing").write_text("{}", encoding="utf-8")
        paths.baseline_path("office").write_text("{}", encoding="utf-8")
        assert paths.list_profiles() == [paths.DEFAULT_PROFILE, "office", "standing"]

    def test_a_saved_default_baseline_does_not_duplicate_the_entry(self, isolated_home):
        paths.baseline_path(paths.DEFAULT_PROFILE).write_text("{}", encoding="utf-8")
        assert paths.list_profiles() == [paths.DEFAULT_PROFILE]
