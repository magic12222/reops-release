"""原工作台历史查询，可显式复用实时监控；不提供模型或恢复执行器。"""
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .mobile import MobileSnapshot, install_mobile_routes
from .store import Store
from workbench.b_store import read_feed
from workbench.contracts import Snapshot, Target
from workbench.legacy_knowledge import FILES, read_legacy_knowledge

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def code_version(root=ROOT):
    root = Path(root).resolve()
    commit = None
    # A source archive has no Git checkout. Never borrow a parent repository's identity.
    if (root / '.git').exists():
        try:
            result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                capture_output=True, text=True, check=True, timeout=5)
            commit = result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
    hashes = {}
    for folder in ('dashboard_api', 'workbench', 'scripts'):
        for path in (root / folder).rglob('*.py'):
            hashes[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    proxy = root / 'web/src/data/localProxy.ts'
    if proxy.is_file():
        hashes[proxy.relative_to(root).as_posix()] = sha256(proxy.read_bytes()).hexdigest()
    return {'git_commit': commit, 'loaded_code_sha256': digest(hashes)}


def create_history_app(*, b_path, dashboard_path, token, archives=True, root=ROOT, monitor=None):
    root = Path(root).resolve()
    paths = [Path(b_path).resolve(), Path(dashboard_path).resolve()]
    if any(not p.is_file() or not p.is_relative_to(root) for p in paths):
        raise ValueError('existing_project_databases_required')
    store = Store(paths[1], read_only=True)
    instance = str(uuid4())
    version = code_version(root)
    source_identity = digest({'paths': [str(p) for p in paths], 'archives': archives,
        'archive_files': list(FILES) if archives else []})
    mode = 'live_monitoring_with_persisted_history' if monitor is not None else 'persisted_history_read_only'
    app = FastAPI(title='ReOps workbench read API', docs_url=None, redoc_url=None, openapi_url=None)

    def read():
        feed = read_feed(paths[0])
        if feed.status != 'ready':
            raise ValueError('history_store_unavailable')
        legacy = read_legacy_knowledge(root) if archives else None
        from workbench.contracts import TargetFeed
        try:
            current = monitor.read_targets() if monitor is not None else TargetFeed(status='not_connected', targets=[])
        except Exception:
            current = TargetFeed(status='not_connected', targets=[])
        return MobileSnapshot(schema_version='0.1', source='real',
            generated_at=datetime.now(timezone.utc).isoformat(), a_status=current.status, b_status='ready',
            targets=[t.model_copy(update={'allowed_actions': []}) for t in current.targets],
            incidents=[*feed.incidents, *(legacy.incidents if legacy else [])],
            experiences=[*feed.experiences, *(legacy.experiences if legacy else [])])

    def deployment():
        data = read()
        records = {'incidents': [i.model_dump() for i in data.incidents],
                   'experiences': [e.model_dump() for e in data.experiences]}
        monitoring = ('watching' if any(t.monitoring == 'watching' for t in data.targets) else
                      'paused' if data.targets else 'not_connected')
        return {'schema_version': 'deployment-v1', 'mode': mode, **version,
            'instance_id': instance, 'source_identity': source_identity,
            'archive_policy': 'fixed_legacy_memory_files' if archives else 'b_store_only',
            'incident_count': len(data.incidents), 'experience_count': len(data.experiences),
            'model_call_count': sum(len(i.model_calls) for i in data.incidents),
            'records_sha256': digest(records), 'monitoring': monitoring,
            'dashboard_runs': 'separate_imported_read_model'}

    install_mobile_routes(app, read, store, token_provider=lambda: token, deployment=deployment)

    @app.middleware('http')
    async def boundary(request, call_next):
        # proxy_headers must be disabled at the listener. Forwarded headers confer no authority.
        try:
            local = (ipaddress.ip_address(request.client.host).is_loopback
                     and request.scope.get('server', (None, None))[1] == 8021)
        except (ValueError, AttributeError):
            local = False
        path = request.url.path
        mobile = path in {'/api/v1/mobile/overview', '/api/v1/mobile/incidents', '/api/v1/mobile/deployment'} or (
            path.startswith('/api/v1/mobile/incidents/') and len(path.split('/')) == 6)
        if request.method != 'GET' or not (mobile or local and path in {'/api/v1/workbench/snapshot', '/api/v1/health'}):
            return JSONResponse({'detail': 'read_route_not_available'}, status_code=404,
                headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-ReOps-Instance'] = instance
        response.headers['X-ReOps-Code'] = version['loaded_code_sha256']
        return response

    @app.get('/api/v1/workbench/snapshot', response_model=Snapshot)
    def snapshot():
        try:
            data = read()
            # Historical catalogue entries never replace an actual current target.
            current_ids = {t.id for t in data.targets}
            targets = [Target(id=key, name='历史记录 · ' + key, runtime='docker', health='unknown',
                monitoring='not_connected', observed_at=None, components=[], allowed_actions=[])
                for key in sorted({i.target_id for i in data.incidents} - current_ids)]
            targets = [*data.targets, *targets]
            return Snapshot(**{**data.model_dump(), 'a_status': 'ready' if targets else 'not_connected', 'targets': targets})
        except Exception:
            return JSONResponse({'detail': 'workbench_snapshot_unavailable'}, status_code=503)

    @app.get('/api/v1/health')
    def health():
        return {'status': 'ok', 'component': 'workbench_api', 'mode': mode}

    return app
