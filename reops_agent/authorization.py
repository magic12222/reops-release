"""本轮人类授权与持久化一次性消费；CLI 开关和普通 JSON 不能产生授权。"""

from copy import deepcopy
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import secrets
import sqlite3
import sys
import time
from threading import Lock
from uuid import uuid4

from .credential_handling import redact_persistent


class AuthorizationError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def interactive_confirm(request, challenge):
    """不接受重定向 stdin 或环境审批；必须在终端确认具体绑定的操作。"""
    if not sys.stdin.isatty():
        return None
    print(json.dumps(redact_persistent(request), ensure_ascii=True, indent=2))
    print("To authorize this operation once, type exactly: " + challenge)
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        return None


@dataclass(frozen=True)
class Grant:
    authorization_id: str
    purpose: str
    binding_digest: str
    expires_at: float


class AuthorizationGate:
    def __init__(self, ledger, *, confirm=None, ttl=120, clock=time.time):
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 300:
            raise ValueError("authorization ttl must be finite and within 0~300 seconds")
        self.ledger = Path(ledger)
        self.confirm = interactive_confirm if confirm is None else confirm
        self.ttl, self.clock = ttl, clock
        self._issued = {}
        self._clock_lock = Lock()
        self._last_clock = None

    def _now(self):
        # TTL不能因本机墙钟回退而延长；异常时钟不产生/消费能力。
        with self._clock_lock:
            value=self.clock()
            if (type(value) not in (int,float) or not math.isfinite(value)
                    or self._last_clock is not None and value < self._last_clock):
                raise AuthorizationError('authorization_clock_invalid_or_reversed')
            self._last_clock=value
            return value

    def request(self, purpose, binding):
        if purpose not in {"model", "recovery", "experiment"}:
            raise AuthorizationError("unknown_authorization_purpose")
        request = {"purpose": purpose, "binding": deepcopy(binding), "max_uses": 1,
                   "expires_in_seconds": self.ttl}
        challenge = f"AUTHORIZE {purpose} {secrets.token_hex(8)}"
        # Take the digest before invoking an external confirmation adapter.
        binding_digest = digest(binding)
        if self.confirm(deepcopy(request), challenge) != challenge:
            raise AuthorizationError("explicit_user_authorization_required")
        grant = Grant(f"authorization-{uuid4()}", purpose, binding_digest, self._now() + self.ttl)
        self._issued[grant.authorization_id] = grant
        return grant

    def consume(self, grant, purpose, binding, *, operation_id):
        if not isinstance(operation_id,str) or not operation_id.strip() or len(operation_id)>256:
            raise AuthorizationError('authorization_operation_id_invalid')
        # Object identity binds this capability to this live gate; serialized/copied
        # grants and grants from an earlier process cannot approve a new operation.
        if (not isinstance(grant, Grant) or self._issued.get(grant.authorization_id) is not grant
                or grant.purpose != purpose or grant.binding_digest != digest(binding)
                or self._now() >= grant.expires_at):
            raise AuthorizationError("authorization_invalid_expired_or_mismatched")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.ledger, timeout=10)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS reservations (operation_id TEXT PRIMARY KEY, "
                       "authorization_id TEXT UNIQUE NOT NULL, digest TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            # Lock acquisition may outlast the remaining lifetime. Check at the
            # reservation boundary, not only before a potentially blocking wait.
            if self._now() >= grant.expires_at:
                raise AuthorizationError("authorization_expired_before_reservation")
            try:
                db.execute("INSERT INTO reservations VALUES (?, ?, ?)",
                           (operation_id, grant.authorization_id, grant.binding_digest))
            except sqlite3.IntegrityError:
                raise AuthorizationError("operation_or_authorization_already_consumed") from None
        return {"authorization_id": grant.authorization_id, "purpose": purpose,
                "binding_digest": grant.binding_digest, "expires_at": grant.expires_at,
                "source": "interactive_user_confirmation" if self.confirm is interactive_confirm
                    else "injected_confirmation_adapter", "consumed": True}
