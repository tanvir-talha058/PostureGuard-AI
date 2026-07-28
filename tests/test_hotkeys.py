"""Global hotkey registration and dispatch.

Every test monkeypatches the private `_register`/`_unregister` wrappers, never the real
`RegisterHotKey` — a leaked call would actually claim Ctrl+Alt+P/R system-wide on
whatever machine runs the suite.
"""

from __future__ import annotations

from postureguard import hotkeys
from postureguard.hotkeys import RECALIBRATE_HOTKEY_ID, SNOOZE_HOTKEY_ID, GlobalHotkeys


class TestRegister:
    def test_registers_both_hotkeys(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", True)
        monkeypatch.setattr(hotkeys, "_register", lambda id_, vk: calls.append(id_) or True)
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        assert gh.register() is True
        assert set(calls) == {SNOOZE_HOTKEY_ID, RECALIBRATE_HOTKEY_ID}

    def test_succeeds_if_only_one_of_the_two_registers(self, monkeypatch):
        """Another app may already own one combo; that is not grounds to disable
        the whole feature when the other half still works."""
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", True)
        monkeypatch.setattr(
            hotkeys, "_register", lambda id_, vk: id_ == SNOOZE_HOTKEY_ID
        )
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        assert gh.register() is True

    def test_false_when_neither_registers(self, monkeypatch):
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", True)
        monkeypatch.setattr(hotkeys, "_register", lambda id_, vk: False)
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        assert gh.register() is False

    def test_calling_register_twice_is_a_no_op_the_second_time(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", True)
        monkeypatch.setattr(hotkeys, "_register", lambda id_, vk: calls.append(id_) or True)
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        gh.register()
        gh.register()
        assert len(calls) == 2  # not 4

    def test_unsupported_platform_never_registers(self, monkeypatch):
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", False)
        monkeypatch.setattr(hotkeys, "_register", lambda id_, vk: True)
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        assert gh.register() is False


class TestUnregister:
    def test_releases_both_after_a_successful_registration(self, monkeypatch):
        released = []
        monkeypatch.setattr(hotkeys, "_IS_WINDOWS", True)
        monkeypatch.setattr(hotkeys, "_register", lambda id_, vk: True)
        monkeypatch.setattr(hotkeys, "_unregister", lambda id_: released.append(id_))
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None)
        gh.register()
        gh.unregister()
        assert set(released) == {SNOOZE_HOTKEY_ID, RECALIBRATE_HOTKEY_ID}

    def test_a_no_op_when_never_registered(self, monkeypatch):
        released = []
        monkeypatch.setattr(hotkeys, "_unregister", lambda id_: released.append(id_))
        GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: None).unregister()
        assert released == []


class TestDispatch:
    def test_routes_the_snooze_id_to_its_callback(self):
        fired = []
        gh = GlobalHotkeys(on_snooze=lambda: fired.append("snooze"), on_recalibrate=lambda: None)
        assert gh.dispatch(SNOOZE_HOTKEY_ID) is True
        assert fired == ["snooze"]

    def test_routes_the_recalibrate_id_to_its_callback(self):
        fired = []
        gh = GlobalHotkeys(on_snooze=lambda: None, on_recalibrate=lambda: fired.append("recal"))
        assert gh.dispatch(RECALIBRATE_HOTKEY_ID) is True
        assert fired == ["recal"]

    def test_an_unknown_id_is_ignored(self):
        gh = GlobalHotkeys(on_snooze=lambda: (_ for _ in ()).throw(AssertionError()),
                            on_recalibrate=lambda: (_ for _ in ()).throw(AssertionError()))
        assert gh.dispatch(0xDEAD) is False
