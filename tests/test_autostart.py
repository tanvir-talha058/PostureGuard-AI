"""Launch-at-login registry logic.

Every test fakes `winreg` itself, never touching the real Registry — these run on the
developer's own machine, and a leaked write would make this app actually start at their
next login.
"""

from __future__ import annotations

import pytest

from postureguard import autostart


class _FakeKey:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeWinreg:
    """Just enough of the `winreg` surface for the Run-key value this module touches."""

    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    KEY_READ = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.fail = False

    def OpenKey(self, hive, path, index, access):
        if self.fail:
            raise OSError("simulated registry failure")
        return _FakeKey(self.store)

    def SetValueEx(self, key, name, reserved, kind, value):
        key.values[name] = value

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return (key.values[name], self.REG_SZ)

    def DeleteValue(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        del key.values[name]


@pytest.fixture
def fake_registry(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setattr(autostart, "_IS_WINDOWS", True)
    monkeypatch.setattr(autostart, "winreg", fake, raising=False)
    return fake


class TestEnable:
    def test_writes_the_run_key_value(self, fake_registry):
        assert autostart.enable() is True
        assert autostart._VALUE_NAME in fake_registry.store

    def test_false_on_registry_failure(self, fake_registry):
        fake_registry.fail = True
        assert autostart.enable() is False


class TestDisable:
    def test_removes_an_existing_value(self, fake_registry):
        autostart.enable()
        assert autostart.disable() is True
        assert autostart._VALUE_NAME not in fake_registry.store

    def test_true_even_when_nothing_was_set(self, fake_registry):
        assert autostart.disable() is True


class TestIsEnabled:
    def test_false_before_enabling(self, fake_registry):
        assert autostart.is_enabled() is False

    def test_true_after_enabling(self, fake_registry):
        autostart.enable()
        assert autostart.is_enabled() is True

    def test_false_after_disabling(self, fake_registry):
        autostart.enable()
        autostart.disable()
        assert autostart.is_enabled() is False


class TestApply:
    def test_true_enables(self, fake_registry):
        autostart.apply(True)
        assert autostart.is_enabled() is True

    def test_false_disables(self, fake_registry):
        autostart.enable()
        autostart.apply(False)
        assert autostart.is_enabled() is False


def test_unsupported_platform_is_a_no_op(monkeypatch):
    monkeypatch.setattr(autostart, "_IS_WINDOWS", False)
    assert autostart.enable() is False
    assert autostart.disable() is False
    assert autostart.is_enabled() is False
