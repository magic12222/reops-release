"""Record actual provider input/output and SDK HTTP body, without headers or credentials."""
from copy import deepcopy
import json
from threading import Lock
import time
from uuid import uuid4

import httpx

from reops_agent.measurements import AttemptMeasurement, measurement_scope
from reops_agent.nexent_provider import WEB_TRANSPORT
from .b_privacy import redact, dumps


class RecordingProvider:
    """One outstanding call, with late results unable to mutate a closed incident."""
    def __init__(self, provider, store, incident_id, model):
        self.provider, self.store, self.incident_id = provider, store, incident_id
        self.measurement = AttemptMeasurement({"incident_id": incident_id,
            "trace_id": store.get(incident_id)[0]["trace_id"]}, source=store.source)
        self.lock = Lock()
        self.closed = False
        self.call = {"id": "call-b-" + uuid4().hex, "model": model, "status": "running",
            "request": "", "response": None, "duration_ms": None,
            "input_tokens": None, "output_tokens": None, "redacted": True}
        self.started = None
        self.raw = None
        self.wire_request = self.wire_response = None
        self.transport_factory = WEB_TRANSPORT.get()

    def complete(self, request, *, timeout_seconds):
        with self.lock:
            if self.closed or self.started is not None:
                raise ValueError("b_model_call_budget_exhausted")
            self.started = time.monotonic()
            # This is the actual provider boundary, never reconstructed from RCA conclusions.
            self.call["request"] = dumps({"boundary": "RCAProvider.complete", "input": request})
            self.store.model_call(self.incident_id, self.call)
        self.measurement.begin_model(timeout_seconds)
        owner = self

        class CaptureStream(httpx.SyncByteStream):
            def __init__(self, stream):
                self.stream, self.parts, self.size = stream, [], 0

            def __iter__(self):
                for part in self.stream:
                    self.size += len(part)
                    if self.size <= 131072:
                        self.parts.append(part)
                    yield part
                if self.size <= 131072:
                    text = b"".join(self.parts).decode("utf-8", errors="replace")
                    with owner.lock:
                        if not owner.closed:
                            owner.wire_response = text

            def close(self):
                self.stream.close()

        class CaptureTransport(httpx.BaseTransport):
            def __init__(self):
                self.inner = owner.transport_factory() if owner.transport_factory else httpx.HTTPTransport(retries=0)

            def handle_request(self, outgoing):
                # SDK body only; URL and headers can contain credentials and are excluded.
                payload = outgoing.read()
                with owner.lock:
                    if not owner.closed:
                        owner.wire_request = payload.decode("utf-8", errors="replace") if len(payload) <= 131072 else "[REQUEST_TOO_LARGE]"
                        owner.call["request"] = dumps({"boundary": "model_http_body", "body": owner.wire_request})
                        owner.store.model_call(owner.incident_id, owner.call)
                response = self.inner.handle_request(outgoing)
                response.stream = CaptureStream(response.stream)
                return response

            def close(self):
                self.inner.close()

        token = WEB_TRANSPORT.set(CaptureTransport)
        try:
            with measurement_scope(self.measurement):
                raw = self.provider.complete(deepcopy(request), timeout_seconds=timeout_seconds)
            with self.lock:
                if not self.closed:
                    self.raw = raw if isinstance(raw, str) else None
            return raw
        finally:
            WEB_TRANSPORT.reset(token)

    def _measurement_finished(self, result):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.measurement.close_model(result)
            measurements = self.measurement.close()
            if self.started is None:
                return  # No actual provider invocation, so no invented conversation.
            self.call.update(status="succeeded" if result.get("source") == "provider"
                and result.get("fallback_reason") is None else "failed",
                duration_ms=max(0, int((time.monotonic() - self.started) * 1000)),
                response=redact(self.raw if self.raw is not None else self.wire_response))
            usage = measurements["usage"]
            if usage is not None and usage.get("source") == "server_usage":
                self.call.update(input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"])
            self.store.model_call(self.incident_id, self.call)
