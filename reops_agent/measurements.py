"""J-01 每次 attempt 独立计量；关闭后拒绝迟到，不存储请求/响应原文。"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import math
from threading import RLock
import time
import zlib
from uuid import uuid4

CURRENT = ContextVar("reops_measurement", default=None)


@contextmanager
def measurement_scope(measurement):
    token = CURRENT.set(measurement)
    try:
        yield
    finally:
        CURRENT.reset(token)


def strict_usage(value):
    """只接受服务端原始完整输入/输出对，不接受 SDK 估算、bool 或坏类型。"""
    if not isinstance(value, dict):
        return None
    counts = [value.get(name) for name in ("prompt_tokens", "completion_tokens")]
    if not all(type(count) is int and count >= 0 for count in counts):
        return None
    total = value.get("total_tokens")
    if total is not None and (type(total) is not int or total != sum(counts)):
        return None
    return {"input_tokens": counts[0], "output_tokens": counts[1], "source": "server_usage"}


class AttemptMeasurement:
    def __init__(self, observation, *, source, clock=None):
        self.clock = clock or time.monotonic
        self.lock = RLock()
        self.closed = self.model_closed = False
        self.identity = {key: observation[key] for key in ("incident_id", "trace_id")}
        self.identity.update(source=source, attempt_id="attempt-" + uuid4().hex)
        self.attempts = self.texts = self.schemas = self.budget_timeouts = 0
        self.transport_bound = False
        self.requests = {}
        self.deadline = None
        self.command_start = self.command_end = self.command_operation = None
        self.verify_ids = []
        self.last_clock = None
        self.clock_valid = True

    def _now(self):
        try:
            value = self.clock()
            if (not self.clock_valid or type(value) not in (int, float) or not math.isfinite(value)
                    or value < 0 or self.last_clock is not None and value < self.last_clock):
                raise ValueError()
            self.last_clock = value
            return value
        except Exception:
            self.clock_valid = False
            return None

    def begin_model(self, timeout):
        with self.lock:
            if self.closed or self.model_closed:
                return False
            self.attempts += 1
            started = self._now()
            self.deadline = started + timeout if started is not None else None
            return True

    def text_returned(self, text):
        with self.lock:
            if not self.closed and not self.model_closed:
                instant = self._now()
                if self.deadline is None or instant is None:
                    self.texts = None
                elif instant <= self.deadline:
                    self.texts += int(isinstance(text, str) and bool(text.strip()))

    def close_model(self, rca):
        with self.lock:
            if self.model_closed:
                return
            self.model_closed = True
            self.schemas = int(rca.get("source") == "provider" and rca.get("fallback_reason") is None)
            self.budget_timeouts = int(rca.get("fallback_reason") == "provider_timeout")

    def bind_transport(self):
        with self.lock:
            if not self.closed and not self.model_closed:
                self.transport_bound = True

    def request_started(self):
        with self.lock:
            if self.closed or self.model_closed or self.deadline is None:
                return None
            instant = self._now()
            if instant is None or instant > self.deadline:
                return None
            key = "request-" + uuid4().hex
            self.requests[key] = {"http_success": False, "timeout": False, "usage": None, "finished": False}
            return key

    def response_finished(self, key, status, usage, *, timeout=False):
        with self.lock:
            if self.closed or self.model_closed or key not in self.requests:
                return
            instant = self._now()
            if instant is None or self.deadline is None or instant > self.deadline:
                return
            self.requests[key].update(http_success=not timeout and 200 <= status < 300,
                                      timeout=timeout, usage=usage if not timeout and 200 <= status < 300 else None,
                                      finished=True)

    def command_started(self, operation):
        with self.lock:
            if self.closed or operation not in {"start", "restart"}:
                return
            if self.command_start is not None:
                # 多次命令不拼成一个成功恢复时延。
                self.command_start = None
                self.command_operation = "conflict"
            elif self.command_operation != "conflict":
                self.command_start, self.command_operation = self._now(), operation

    def recovered(self, executed, ids):
        with self.lock:
            if (not self.closed and executed is True and self.command_start is not None
                    and len(ids) == 2 and all(isinstance(value, str) and value for value in ids) and len(set(ids)) == 2):
                self.command_end, self.verify_ids = self._now(), list(ids)

    def close(self):
        with self.lock:
            self.closed = self.model_closed = True
            requests = list(self.requests.values())
            usage = None
            if requests and all(request["usage"] is not None for request in requests):
                usage = {name: sum(request["usage"][name] for request in requests)
                         for name in ("input_tokens", "output_tokens")}
                usage["source"] = "server_usage"
            elapsed = None
            if self.clock_valid and self.command_start is not None and self.command_end is not None:
                value = (self.command_end - self.command_start) * 1000
                if math.isfinite(value) and value >= 0:
                    elapsed = value
            return {"version": "j01-v1", **self.identity,
                "provider_attempts": self.attempts,
                "http_requests": len(requests) if self.transport_bound else None,
                "http_successes": sum(item["http_success"] for item in requests) if self.transport_bound else None,
                "text_successes": self.texts, "rca_schema_successes": self.schemas,
                "timeouts": {"provider_budget": self.budget_timeouts,
                             "transport": sum(item["timeout"] for item in requests)
                             if self.transport_bound and all(item["finished"] for item in requests) else None},
                "usage": usage, "cost": None,
                "requests": [{"request_id": key, **deepcopy(value)} for key, value in self.requests.items()],
                "recovery_latency_ms": elapsed,
                "recovery_timing": {"source": "local_monotonic_command_to_second_fresh_verify",
                    "start": self.command_start, "end": self.command_end,
                    "clock_valid": self.clock_valid, "clock_id": self.identity["attempt_id"],
                    "operation": self.command_operation, "verify_observation_ids": self.verify_ids},
                "closed": True}


class UsageReader:
    """有界解析原始 JSON/SSE，仅保留 usage；不暴露响应文本。"""
    def __init__(self, sse, encoding=""):
        self.sse = sse
        self.buffer = b""
        self.usage = None
        self.invalid = self.done = False
        self.decoder = (zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip"
                        else zlib.decompressobj() if encoding == "deflate" else None)
        if encoding not in {"", "identity", "gzip", "deflate"}:
            self.invalid = True

    def parsed(self, raw):
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate_json_field")
                value[key] = item
            return value
        try:
            value = json.loads(raw, object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if isinstance(value, dict) and value.get("usage") is not None:
                usage = strict_usage(value["usage"])
                if usage is None or self.usage is not None and self.usage != usage:
                    self.invalid = True
                else:
                    self.usage = usage
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            self.invalid = True

    def feed(self, chunk):
        if self.invalid:
            return
        if self.decoder:
            try:
                chunk = self.decoder.decompress(chunk, 131073)
            except zlib.error:
                self.invalid = True
                return
        self.buffer += chunk
        if len(self.buffer) > 131072:
            self.buffer = b""
            self.invalid = True
            return
        if self.sse:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                line = line.strip()
                if line == b"data: [DONE]":
                    self.done = True
                elif line.startswith(b"data:"):
                    self.parsed(line[5:].strip())

    def finish(self):
        if self.decoder and not self.decoder.eof:
            self.invalid = True
        if not self.sse:
            self.parsed(self.buffer)
        self.buffer = b""
        return self.usage if not self.invalid and (not self.sse or self.done) else None


def measured_transport(inner, measurement):
    import httpx
    measurement.bind_transport()

    class Stream(httpx.SyncByteStream):
        def __init__(self, response, key):
            self.inner, self.key, self.status = response.stream, key, response.status_code
            self.settled = False
            self.reader = UsageReader("text/event-stream" in response.headers.get("content-type", ""),
                                      response.headers.get("content-encoding", "").lower())

        def __iter__(self):
            try:
                for chunk in self.inner:
                    self.reader.feed(chunk)
                    yield chunk
                measurement.response_finished(self.key, self.status, self.reader.finish())
                self.settled = True
            except httpx.TimeoutException:
                measurement.response_finished(self.key, self.status, None, timeout=True)
                self.settled = True
                raise
            except httpx.HTTPError:
                measurement.response_finished(self.key, 0, None)
                self.settled = True
                raise

        def close(self):
            try:
                # OpenAI SDK 在 [DONE] 后结束上层迭代，不一定再次拉取底层 EOF。
                # 只结算已经观察到完整协议结束的流；禁止主动排空或接收迟到结果。
                if not self.settled and self.reader.sse and self.reader.done:
                    measurement.response_finished(self.key, self.status, self.reader.finish())
                    self.settled = True
            finally:
                self.inner.close()

    class Transport(httpx.BaseTransport):
        def handle_request(self, request):
            key = measurement.request_started()
            if key is None:
                raise RuntimeError("measurement_closed")
            try:
                response = inner.handle_request(request)
            except httpx.TimeoutException:
                measurement.response_finished(key, 0, None, timeout=True)
                raise
            except httpx.HTTPError:
                measurement.response_finished(key, 0, None)
                raise
            if response.is_stream_consumed:
                reader = UsageReader("text/event-stream" in response.headers.get("content-type", ""))
                reader.feed(response.content)
                measurement.response_finished(key, response.status_code, reader.finish())
            else:
                response.stream = Stream(response, key)
            return response

        def close(self):
            inner.close()

    return Transport()


def summarize_incidents(reports, plan):
    """按事前明确的 incident 清单汇总；不推断 ground truth 或纳入资格。"""
    if not isinstance(plan, dict) or any(type(value) is not bool for value in plan.values()):
        raise ValueError("evaluation_plan_requires_boolean_eligibility")
    indexed, conflicts, groups, started, missing_start = {}, set(), set(), set(), set()
    for report in reports:
        key, trace = report["incident_id"], report["trace_id"]
        if key not in plan or not plan[key]:
            continue
        traces = indexed.setdefault(key, {})
        if trace in traces and traces[trace] != report:
            conflicts.add(key)
        if report.get("recovery_verified") is True and (
                report.get("execution_outcome") != "succeeded" or report.get("recovery_executed") is not True):
            conflicts.add(key)
        traces[trace] = report
        if report.get("incident_started") is True:
            started.add(key)
            metadata = report.get("measurements", {})
            if not isinstance(metadata, dict):
                metadata = {}
            groups.add(json.dumps([report.get("phase"), report.get("strategy"),
                                   metadata.get("source"), report.get("scenario")], sort_keys=True))
        elif report.get("incident_started") is None:
            missing_start.add(key)
    if len(groups) > 1:
        raise ValueError("evaluation_groups_must_not_be_pooled")
    result = {"eligible": 0, "valid": 0, "missing": 0, "conflict": 0,
              "succeeded": 0, "failed": 0, "unknown": 0, "denied": 0,
              "planned_eligible": sum(plan.values()), "latency_valid": 0, "latency_missing": 0}
    latencies = []
    for key, eligible in plan.items():
        if not eligible:
            continue
        traces = indexed.get(key)
        if not traces:
            result["missing"] += 1
            continue
        attempts = list(traces.values())
        if key not in started:
            if key in conflicts:
                result["conflict"] += 1
            elif key in missing_start:
                result["missing"] += 1
            continue  # 排队/健康 no_action/cleanup 不扩大故障 incident 分母。
        result["eligible"] += 1
        if key in conflicts:
            result["conflict"] += 1
            continue
        result["valid"] += 1
        # 缺失/非法执行结果和未确认的 Verify 都不能冒充已知失败；
        # 同 incident 中未解除的未知也不能被另一 trace 的成功覆盖。
        def uncertain(report):
            outcome = report.get("execution_outcome")
            if outcome not in ("succeeded", "failed", "not_run"):
                return True
            if outcome == "succeeded" and report.get("recovery_verified") is not True:
                return report.get("verification_status") != "not_recovered"
            return False

        category = ("unknown" if any(uncertain(report) for report in attempts) else
                    "succeeded" if any(report.get("recovery_verified") is True for report in attempts) else
                    "denied" if all(report.get("execution_outcome") == "not_run" for report in attempts) else "failed")
        result[category] += 1
        for report in attempts:
            if category != "succeeded" or report.get("recovery_verified") is not True:
                continue
            data = report.get("measurements", {})
            if not isinstance(data, dict):
                data = {}
            value = data.get("recovery_latency_ms")
            timing = data.get("recovery_timing", {})
            if not isinstance(timing, dict):
                timing = {}
            ids = timing.get("verify_observation_ids")
            if (data.get("version") == "j01-v1" and data.get("closed") is True
                    and data.get("incident_id") == key and data.get("trace_id") == report["trace_id"]
                    and type(value) in (int, float) and math.isfinite(value) and value >= 0
                    and timing.get("clock_valid") is True and timing.get("clock_id") == data.get("attempt_id")
                    and timing.get("source") == "local_monotonic_command_to_second_fresh_verify"
                    and type(timing.get("start")) in (int, float) and math.isfinite(timing["start"])
                    and type(timing.get("end")) in (int, float) and math.isfinite(timing["end"])
                    and timing["start"] >= 0 and timing["end"] >= timing["start"]
                    and math.isclose(value, (timing["end"]-timing["start"])*1000, rel_tol=1e-9)
                    and isinstance(ids, list) and len(ids) == 2
                    and all(isinstance(value, str) and value for value in ids) and len(set(ids)) == 2):
                result["latency_valid"] += 1
                latencies.append(value)
            else:
                result["latency_missing"] += 1
    # 不剔除缺失/冲突后只对剩余记录报成绩，也不把冲突算作零次成功。
    result["success_rate"] = (result["succeeded"] / result["eligible"]
                              if result["eligible"] and not result["conflict"] and not result["missing"]
                              else None)
    result["mean_success_latency_ms"] = sum(latencies) / len(latencies) if latencies else None
    return result
