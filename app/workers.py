import sys
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_activeWorkers = set()


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.cancelled = False
        self.setAutoDelete(False)

    def reportProgress(self, value):
        if not self.cancelled:
            self.signals.progress.emit(value)

    def run(self):
        try:
            try:
                result = self.function(*self.args, **self.kwargs)
            except Exception as error:
                if sys.stderr:
                    traceback.print_exc()
                if not self.cancelled:
                    self.signals.error.emit(str(error) or error.__class__.__name__)
            else:
                if not self.cancelled:
                    self.signals.finished.emit(result)
        except RuntimeError:
            pass
        finally:
            _activeWorkers.discard(self)


def runInBackground(function, *args, onFinished=None, onError=None, onProgress=None, pool=None, withProgress=False, **kwargs):
    worker = Worker(function, *args, **kwargs)
    if withProgress:
        worker.kwargs["progressCallback"] = worker.reportProgress
    if onFinished:
        worker.signals.finished.connect(onFinished)
    if onError:
        worker.signals.error.connect(onError)
    if onProgress:
        worker.signals.progress.connect(onProgress)
    _activeWorkers.add(worker)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
