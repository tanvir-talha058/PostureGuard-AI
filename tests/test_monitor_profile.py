from postureguard.monitor_profile import MonitorProfiles, fingerprint


class TestFingerprint:
    def test_the_same_arrangement_fingerprints_the_same_way(self):
        one = [("DP-1", 2560, 1440), ("DP-2", 1920, 1080)]
        two = [("DP-1", 2560, 1440), ("DP-2", 1920, 1080)]
        assert fingerprint(one) == fingerprint(two)

    def test_enumeration_order_does_not_matter(self):
        forward = [("DP-1", 2560, 1440), ("DP-2", 1920, 1080)]
        reversed_ = [("DP-2", 1920, 1080), ("DP-1", 2560, 1440)]
        assert fingerprint(forward) == fingerprint(reversed_)

    def test_a_different_monitor_count_fingerprints_differently(self):
        single = [("DP-1", 2560, 1440)]
        dual = [("DP-1", 2560, 1440), ("DP-2", 1920, 1080)]
        assert fingerprint(single) != fingerprint(dual)

    def test_a_different_resolution_fingerprints_differently(self):
        one = [("DP-1", 2560, 1440)]
        other = [("DP-1", 1920, 1080)]
        assert fingerprint(one) != fingerprint(other)

    def test_no_monitors_still_produces_something_stable(self):
        assert fingerprint([]) == fingerprint([])


class TestMonitorProfiles:
    def test_an_unremembered_arrangement_returns_none(self):
        profiles = MonitorProfiles()
        assert profiles.get("unknown") is None

    def test_remembering_an_arrangement_makes_it_retrievable(self):
        profiles = MonitorProfiles()
        profiles.remember("abc123", "Standing desk")
        assert profiles.get("abc123") == "Standing desk"

    def test_remembering_again_overwrites_the_previous_profile(self):
        profiles = MonitorProfiles()
        profiles.remember("abc123", "Standing desk")
        profiles.remember("abc123", "Home office")
        assert profiles.get("abc123") == "Home office"

    def test_forgetting_an_arrangement_removes_it(self):
        profiles = MonitorProfiles()
        profiles.remember("abc123", "Standing desk")
        profiles.forget("abc123")
        assert profiles.get("abc123") is None

    def test_forgetting_an_unknown_arrangement_does_not_raise(self):
        MonitorProfiles().forget("never-seen")


class TestPersistence:
    def test_round_trips_through_a_file(self, tmp_path):
        path = tmp_path / "nested" / "monitor_profiles.json"
        original = MonitorProfiles()
        original.remember("abc123", "Standing desk")
        original.remember("def456", "Home office")
        original.save(path)

        loaded = MonitorProfiles.load(path)
        assert loaded.get("abc123") == "Standing desk"
        assert loaded.get("def456") == "Home office"

    def test_a_missing_file_loads_empty(self, tmp_path):
        loaded = MonitorProfiles.load(tmp_path / "does-not-exist.json")
        assert loaded.get("anything") is None

    def test_a_corrupt_file_loads_empty_rather_than_raising(self, tmp_path):
        path = tmp_path / "monitor_profiles.json"
        path.write_text("not json{{{", encoding="utf-8")
        loaded = MonitorProfiles.load(path)
        assert loaded.get("anything") is None

    def test_a_file_holding_something_other_than_an_object_loads_empty(self, tmp_path):
        path = tmp_path / "monitor_profiles.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        loaded = MonitorProfiles.load(path)
        assert loaded.get("anything") is None
