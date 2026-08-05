from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from postureguard.ai.worker import AskWorker


def _qapp():
    return QApplication.instance() or QApplication([])


def _run_worker(work):
    _qapp()
    worker = AskWorker(work)
    loop = QEventLoop()
    results = []
    worker.finished_with.connect(lambda value: (results.append(value), loop.quit()))
    worker.start()
    loop.exec()
    worker.wait()
    return results[0]


class TestAskWorker:
    def test_emits_the_callables_return_value(self):
        assert _run_worker(lambda: "hello") == "hello"

    def test_emits_none_when_the_callable_raises(self):
        def _boom():
            raise RuntimeError("network exploded")

        assert _run_worker(_boom) is None
