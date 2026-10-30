"""Bound A calls without retrying uncertain side effects or accumulating stuck threads."""
from queue import Empty, Queue
from threading import Lock, Thread


class BoundedA:
    def __init__(self, port):
        self.port = port
        self.locks = {name: Lock() for name in ("scope", "observe", "prepare", "execute")}

    def call(self, name, *args, timeout, finished=None):
        lock = self.locks[name]
        if not lock.acquire(timeout=timeout):
            raise TimeoutError("b_a_" + name + "_busy")
        replies = Queue(maxsize=1)

        def worker():
            try:
                value = getattr(self.port, name)(*args)
                result = (True, value)
            except BaseException:
                result = (False, None)
            finally:
                try:
                    if finished is not None:
                        finished()
                except Exception:
                    # Failed persistence leaves the pending reservation conservatively held.
                    result = (False, None)
                lock.release()
            replies.put(result)

        thread = Thread(target=worker, daemon=True)
        try:
            thread.start()
        except BaseException:
            lock.release()
            raise
        try:
            succeeded, result = replies.get(timeout=timeout)
        except Empty:
            raise TimeoutError("b_a_" + name + "_timeout") from None
        if not succeeded:
            raise RuntimeError("b_a_" + name + "_failed")
        return result
