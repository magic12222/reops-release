"""最多16条API配置；可用Windows凭据管理器保留配置，不自动切换或验证。"""
from threading import RLock
from uuid import uuid4

from reops_agent.nexent_provider import NexentConfig
from .model_endpoints import validate_endpoint, DLUT
from .web_model import WebModel


class ModelRegistry:
    def __init__(self, initial, store=None):
        self.lock = RLock()
        self.store, self.generation, self.storage_error = store, None, None
        self.selected = "builtin-dlut"
        self.services = {self.selected: {"id": self.selected, "name": "DeepSeek", "provider": "大工模型网关",
            "revision": uuid4().hex, "model": initial}}
        if store is not None:
            try:
                saved = store.load()
                if saved:
                    restored = {}
                    for item in saved['services']:
                        key = item['api_key']
                        if key and any(key in str(item[field]) for field in ('name', 'provider', 'model', 'endpoint')):
                            raise ValueError('model_storage_invalid')
                        config = NexentConfig(item['endpoint'], item['model'], key, max_output_tokens=512,
                            allow_dlut_http=item['endpoint'] == DLUT) if key is not None else None
                        model = WebModel(config)
                        model.source = 'persisted_local'
                        restored[item['id']] = {**{field: item[field] for field in ('id', 'name', 'provider', 'revision')}, 'model': model}
                    self.services, self.selected, self.generation = restored, saved['selected'], saved['generation']
            except (OSError, ValueError, TypeError, KeyError):
                # Corrupt/unavailable saved state must never silently activate legacy credentials.
                self.services[self.selected]['model'] = WebModel()
                self.storage_error = 'model_storage_restore_failed'

    @property
    def verified(self):
        return self.services[self.selected]["model"].verified

    def _get(self, service_id=None):
        item = self.services.get(service_id or self.selected)
        if item is None:
            raise ValueError("model_service_not_found")
        return item

    def _status(self, item):
        return {**item["model"].status(), **{key: item[key] for key in ("id", "name", "provider", "revision")},
            "active": item["id"] == self.selected,
            'storage': 'windows_credential_manager' if self.store is not None else 'server_process_memory',
            'storage_state': 'restore_failed' if self.storage_error else 'saved' if self.generation else 'not_saved'}

    def status(self):
        with self.lock:
            return {**self._status(self._get()), 'storage_error': self.storage_error,
                "services": [self._status(item) for item in self.services.values()]}

    def _persist(self, services, selected):
        if self.storage_error:
            raise ValueError(self.storage_error)
        if self.store is not None:
            self.generation = self.store.save(services, selected, self.generation)

    def save(self, fields, service_id=None, *, preserve_active=False, expected_revision=None):
        with self.lock:
            old = self._get(service_id) if service_id else None
            if expected_revision is not None and (old is None or old['revision'] != expected_revision):
                raise ValueError('model_service_revision_conflict')
            candidate = bool(preserve_active and old is not None and service_id == self.selected)
            if (old is None or candidate) and len(self.services) >= 16:
                raise ValueError("model_service_limit")
            for name in ("name", "provider", "model"):
                if (not isinstance(fields.get(name), str) or not fields[name].strip()
                        or len(fields[name]) > 128 or any(ord(c) < 32 for c in fields[name])):
                    raise ValueError("model_service_invalid")
            endpoint = validate_endpoint(fields.get("endpoint"))
            key = fields.get("api_key")
            if not isinstance(key, str):
                raise ValueError("model_key_invalid_format")
            if not key:
                if old is None or old["model"].config is None:
                    raise ValueError("model_key_missing")
                if endpoint != old["model"].config.api_base:
                    raise ValueError("model_endpoint_requires_key")
                key = old["model"].config.api_key
            if not 8 <= len(key) <= 2048 or any(c.isspace() or ord(c) < 32 for c in key):
                raise ValueError("model_key_invalid_format")
            if any(key in str(fields[name]) for name in ("name", "provider", "model", "endpoint")):
                raise ValueError("model_service_invalid")
            config = NexentConfig(endpoint, fields["model"].strip(), key,
                max_output_tokens=512, allow_dlut_http=endpoint == DLUT)
            model = WebModel(config)
            model.source = "server_session"
            item = {"id": service_id if service_id and not candidate else "service-" + uuid4().hex, "name": fields["name"].strip(),
                "provider": fields["provider"].strip(), "revision": uuid4().hex, "model": model}
            next_services = {**self.services, item['id']: item}
            self._persist(next_services, self.selected)
            self.services = next_services
            return self._status(item)

    def set_key(self, key):
        with self.lock:
            item = self._get()
            status = self._status(item)
            self.save({**status, "api_key": key}, item["id"])

    def verify(self, service_id=None, transport=None):
        with self.lock:
            item = self._get(service_id)
            item['model'].verify(transport)
            return self._status(item)

    def select(self, service_id):
        with self.lock:
            item = self._get(service_id)
            if item["model"].config is None:
                raise ValueError("model_key_missing")
            self._persist(self.services, item['id'])
            self.selected = item["id"]
            item["model"].verified = False
            return self.status()

    def for_run(self):
        with self.lock:
            return self._get()["model"].for_run()

    def binding(self):
        with self.lock:
            item = self._get()
            config = item["model"].config
            return {"service_id": item["id"], "revision": item["revision"], "provider": item["provider"],
                "endpoint": config.api_base, "model": config.model_id}
