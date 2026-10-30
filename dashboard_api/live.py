"""C-side receiver for B AgentEvents, called only after B has durably recorded them.

B currently exposes TraceJournal.record(), not an EventSink interface. A B-side
integration can call publish(recorded_event) after that method returns; this
module deliberately does not modify B's recovery or authorization workflow.
"""

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .models import SOURCES
from .normalize import from_trace_journal
from .store import Store


class DashboardEventSink:
    def __init__(self, store: Store, *, source: str):
        if source not in SOURCES:
            raise ValueError("invalid live source")
        self.store = store
        self.source = source

    def publish(self, recorded_event: dict[str, Any]):
        """Validate, redact and atomically append one B journal event.

        The caller must provide explicit provenance and must call this only after
        TraceJournal.record has returned. Replays are harmless; gaps/out-of-order
        parents and conflicting event IDs fail closed.
        """
        run, events = from_trace_journal([recorded_event], source=self.source)
        return self.store.append_live(run, events[0])


class JournalFollower:
    """Follow B's fsynced TraceJournal JSONL without changing B or its control flow."""

    def __init__(self, sink: DashboardEventSink, path: str | Path):
        self.sink = sink
        self.path = Path(path)
        self.offset = 0
        self._identity = None
        self._lock = Lock()

    def poll(self) -> int:
        """Ingest complete lines only; leave failed/partial lines for a later poll."""
        with self._lock:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                return 0
            identity = (stat.st_dev, stat.st_ino)
            if identity != self._identity or stat.st_size < self.offset:
                self.offset = 0
            self._identity = identity
            count = 0
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        break
                    raw = json.loads(line.decode("utf-8"))
                    self.sink.publish(raw)
                    self.offset = stream.tell()
                    count += 1
            return count
