"""Ограниченный мост вывода между worker и event loop."""
import queue
import threading

MAX_LINES = 128
MAX_LINE_CHARS = 16000


class ProgressQueue:
    def __init__(self, cancel_flag=None):
        self.queue = queue.Queue(maxsize=MAX_LINES)
        self.cancel_flag = cancel_flag
        self.loop_thread = threading.get_ident()
        self.closed = threading.Event()
        self.stopped = threading.Event()
        self.skipped = 0
        self.lock = threading.Lock()

    def put(self, line):
        if line is None:
            self.closed.set()
            return
        from core.cancel_flags import current
        flag = self.cancel_flag if self.cancel_flag is not None else current()
        line = str(line)[-MAX_LINE_CHARS:]
        while not self.closed.is_set() and not self.stopped.is_set():
            if flag is not None and flag.is_set():
                return
            try:
                if threading.get_ident() == self.loop_thread:
                    self.queue.put_nowait(line)
                else:
                    self.queue.put(line, timeout=0.05)
                return
            except queue.Full:
                if threading.get_ident() == self.loop_thread:
                    # Синхронный emit из event loop не может ждать свой drain.
                    # Потеря отмечается отдельной строкой, без роста буфера.
                    try:
                        self.queue.get_nowait()
                        with self.lock: self.skipped += 1
                    except queue.Empty:
                        pass

    def get(self):
        while not self.stopped.is_set():
            with self.lock:
                skipped, self.skipped = self.skipped, 0
            if skipped:
                return f"[Часть лога недоступна: пропущено строк {skipped} при переполнении буфера]"
            try:
                return self.queue.get(timeout=0.05)
            except queue.Empty:
                if self.closed.is_set(): return None
        return None

    def abort(self):
        self.closed.set()
        self.stopped.set()
