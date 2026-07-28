from __future__ import annotations

from postureguard import sound


class _FakeWinsound:
    MB_ICONASTERISK = 64

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.fail = False

    def MessageBeep(self, kind: int) -> None:
        if self.fail:
            raise OSError("simulated audio failure")
        self.calls.append(kind)


def test_plays_a_beep_on_windows(monkeypatch):
    fake = _FakeWinsound()
    monkeypatch.setattr(sound, "_IS_WINDOWS", True)
    monkeypatch.setattr(sound, "winsound", fake, raising=False)
    sound.play_alert()
    assert fake.calls == [fake.MB_ICONASTERISK]


def test_a_failed_beep_does_not_raise(monkeypatch):
    fake = _FakeWinsound()
    fake.fail = True
    monkeypatch.setattr(sound, "_IS_WINDOWS", True)
    monkeypatch.setattr(sound, "winsound", fake, raising=False)
    sound.play_alert()  # must not raise


def test_unsupported_platform_is_a_no_op(monkeypatch):
    monkeypatch.setattr(sound, "_IS_WINDOWS", False)
    sound.play_alert()  # must not raise, and must not touch winsound
