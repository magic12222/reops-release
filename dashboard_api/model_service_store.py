"""本机API元数据原子保存；Key仅进入当前Windows用户的凭据管理器。"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4


class WindowsCredentials:
    def _api(self):
        if os.name != 'nt':
            raise ValueError('model_storage_unavailable')
        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
        api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api, Credential

    def put(self, target, value):
        api, record = self._api()
        raw = value.encode('utf-8')
        if len(raw) > 2560:
            raise ValueError('model_storage_unavailable')
        buffer = ctypes.create_string_buffer(raw)
        credential = record(Type=1, TargetName=target, Comment='ReOps local API key',
            CredentialBlobSize=len(raw), CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=2, UserName='ReOps')
        if not api.CredWriteW(ctypes.byref(credential), 0):
            raise ValueError('model_storage_unavailable')

    def get(self, target):
        api, record = self._api()
        value = ctypes.POINTER(record)()
        if not api.CredReadW(target, 1, 0, ctypes.byref(value)):
            raise ValueError('model_storage_unavailable')
        try:
            return ctypes.string_at(value.contents.CredentialBlob, value.contents.CredentialBlobSize).decode('utf-8')
        finally:
            api.CredFree(value)

    def delete(self, target):
        api, _ = self._api()
        if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise ValueError('model_storage_unavailable')


class ModelServiceStore:
    def __init__(self, path, credentials=None):
        self.path = Path(path).resolve()
        self.credentials = credentials or WindowsCredentials()
        self.prefix = 'ReOps/API/' + hashlib.sha256(os.path.normcase(str(self.path)).encode()).hexdigest()[:24] + '/'

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + '.lock').open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'\0'); stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('model_storage_busy') from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _reference(self, item):
        return self.prefix + item['id'] + '/' + item['revision']

    def _manifest(self):
        if not self.path.exists():
            return None
        if self.path.stat().st_size > 65536:
            raise ValueError('model_storage_invalid')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('model_storage_invalid')
                result[key] = value
            return result
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'), object_pairs_hook=unique)
            if (set(value) != {'version', 'generation', 'selected', 'services'} or type(value['version']) is not int or value['version'] != 1
                    or not re.fullmatch('[a-f0-9]{32}', value['generation'])
                    or not isinstance(value['services'], list) or not 1 <= len(value['services']) <= 16):
                raise ValueError()
            identifiers = set()
            for item in value['services']:
                if set(item) != {'id', 'revision', 'name', 'provider', 'model', 'endpoint', 'credential_ref'}:
                    raise ValueError()
                if not re.fullmatch('[A-Za-z0-9_-]{1,80}', item['id']) or item['id'] in identifiers:
                    raise ValueError()
                identifiers.add(item['id'])
                if not re.fullmatch('[a-f0-9]{32}', item['revision']):
                    raise ValueError()
                for field in ('name', 'provider'):
                    if not isinstance(item[field], str) or not item[field].strip() or len(item[field]) > 128 or any(ord(c) < 32 for c in item[field]):
                        raise ValueError()
                if item['credential_ref'] is None:
                    if item['model'] is not None or item['endpoint'] is not None:
                        raise ValueError()
                elif (item['credential_ref'] != self._reference(item) or not isinstance(item['model'], str)
                        or not item['model'].strip() or len(item['model']) > 128 or any(ord(c) < 32 for c in item['model'])):
                    raise ValueError()
                else:
                    from .model_endpoints import validate_endpoint
                    validate_endpoint(item['endpoint'])
            if value['selected'] not in identifiers:
                raise ValueError()
            return value
        except (TypeError, KeyError, ValueError, UnicodeError):
            raise ValueError('model_storage_invalid') from None

    def load(self):
        # No directory or lock is created just for an empty initial read.
        if not self.path.exists():
            return None
        try:
            with self._locked():
                value = self._manifest()
                for item in value['services']:
                    item['api_key'] = self.credentials.get(item['credential_ref']) if item['credential_ref'] else None
                    key = item['api_key']
                    if item['credential_ref'] is not None and (not isinstance(key, str) or not 8 <= len(key) <= 2048 or any(c.isspace() or ord(c) < 32 for c in key)):
                        raise ValueError('model_storage_invalid')
                return value
        except OSError:
            raise ValueError('model_storage_unavailable') from None

    def save(self, services, selected, expected_generation):
        created, temporary = [], None
        try:
            with self._locked():
                old = self._manifest()
                if (old['generation'] if old else None) != expected_generation:
                    raise ValueError('model_storage_conflict')
                old_refs = {item['credential_ref'] for item in old['services'] if item['credential_ref']} if old else set()
                entries = []
                for item in services.values():
                    config = item['model'].config
                    entry = {key: item[key] for key in ('id', 'revision', 'name', 'provider')}
                    entry.update(model=config.model_id if config else None, endpoint=config.api_base if config else None,
                        credential_ref=self._reference(item) if config else None)
                    if config and entry['credential_ref'] not in old_refs:
                        # Immutable revision targets keep the previous complete configuration recoverable.
                        created.append(entry['credential_ref'])
                        self.credentials.put(entry['credential_ref'], config.api_key)
                    entries.append(entry)
                value = {'version': 1, 'generation': uuid4().hex, 'selected': selected, 'services': entries}
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, prefix='.model-services-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                temporary = None
                new_refs = {item['credential_ref'] for item in entries if item['credential_ref']}
                for reference in old_refs - new_refs:
                    try:
                        self.credentials.delete(reference)
                    except (OSError, ValueError):
                        pass  # Never undo a successfully committed manifest or replay a save.
                return value['generation']
        except (OSError, ValueError) as error:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            for reference in created:
                try:
                    self.credentials.delete(reference)
                except (OSError, ValueError):
                    pass
            reason = str(error)
            allowed = {'model_storage_conflict', 'model_storage_invalid', 'model_storage_unavailable', 'model_storage_busy'}
            raise ValueError(reason if reason in allowed else 'model_storage_write_failed') from None
