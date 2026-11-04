"""只读核对本机既存 BStore、原始依赖审计与移动 ASGI 投影；不启动任何服务。"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_api.mobile import MobileSnapshot, install_mobile_routes, stamp
from dashboard_api.store import Store
from scripts.check_harmony_api import check
from workbench.b_store import read_feed
from workbench.dependency_records import STAGES, project_run
from workbench.b_privacy import redact

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def audit(b_path, dashboard_path, journal_path, destination):
    before = {str(p.relative_to(ROOT)): digest(p) for p in (b_path, dashboard_path, journal_path) if p.is_file()}
    feed = read_feed(b_path)
    if feed.status != 'ready':
        raise ValueError('persisted_records_unavailable')
    def reader():
        current = read_feed(b_path)
        return MobileSnapshot(schema_version='0.1', source='real', generated_at=datetime.now(timezone.utc).isoformat(),
            a_status='not_connected', b_status=current.status, targets=[],
            incidents=current.incidents, experiences=current.experiences)

    store = Store(dashboard_path, read_only=True)
    app = FastAPI()
    install_mobile_routes(app, reader, store)
    prior = os.environ.get('REOPS_MOBILE_READ_TOKEN')
    credential = secrets.token_urlsafe(40)
    os.environ['REOPS_MOBILE_READ_TOKEN'] = credential
    try:
        with TestClient(app, headers={'Authorization': 'Bearer ' + credential}) as client:
            result = check(client)
            details = []
            for item in feed.incidents:
                value = client.get('/api/v1/mobile/incidents/' + item.id)
                value.raise_for_status()
                value = value.json()
                # Exact data values (apart from deliberate UTC formatting/redaction) and references.
                assert value['incident']['trace_id'] == item.trace_id
                assert value['incident']['status'] == item.status
                assert value['recovery']['verification'] == item.verification.model_dump()
                assert [e['id'] for e in value['incident']['events']] == [e.id for e in item.events]
                assert [e['id'] for e in value['knowledge']] == item.experience_ids
                assert [c['id'] for c in value['diagnosis']['calls']] == [c.id for c in item.model_calls]
                assert value['diagnosis']['calls'] == redact([c.model_dump() for c in item.model_calls])
                assert value['incident']['events'] == [
                    {**redact(e.model_dump()), 'timestamp': stamp(e.timestamp)} for e in item.events]
                details.append({'incident_id': item.id, 'trace_id': item.trace_id, 'status': item.status,
                    'event_count': len(item.events), 'model_calls': len(item.model_calls),
                    'knowledge_ids': item.experience_ids, 'run_link_status': value['run_link_status'],
                    'verification': value['recovery']['verification']})
    finally:
        if prior is None:
            os.environ.pop('REOPS_MOBILE_READ_TOKEN', None)
        else:
            os.environ['REOPS_MOBILE_READ_TOKEN'] = prior
    # Recompute existing projected facts from the actual original journal, without importing/writing.
    groups = {}
    if journal_path.is_file():
        for number, line in enumerate(journal_path.read_bytes().splitlines(), 1):
            row = json.loads(line)
            if row.get('event') in STAGES and isinstance(row.get('trace_id'), str):
                groups.setdefault(row['trace_id'], []).append((number, row, sha256(line).hexdigest()))
    matched = 0
    for rows in groups.values():
        if rows[0][1].get('plan_id') != 'vikunja_dependency_v1':
            continue
        incident, experience = project_run(rows)
        stored = next((i for i in feed.incidents if i.id == incident.id), None)
        assert stored is not None and stored.trace_id == incident.trace_id
        assert stored.status == incident.status and stored.verification == incident.verification
        assert [e.id for e in stored.events[:len(incident.events)]] == [e.id for e in incident.events]
        persisted = next((e for e in feed.experiences if e.id == experience.id), None)
        assert persisted is not None and persisted.incident_id == incident.id
        assert persisted.status in {experience.status, 'retired'}
        matched += 1
    with sqlite3.connect(b_path.as_uri() + '?mode=ro', uri=True) as db:
        sqlite_check = db.execute('PRAGMA quick_check').fetchone()[0]
    after = {str(p.relative_to(ROOT)): digest(p) for p in (b_path, dashboard_path, journal_path) if p.is_file()}
    assert before == after
    result.update(mode='persisted_record_asgi_audit', target_feed='not_connected_no_live_monitor',
        database_incidents=len(feed.incidents), records=details, original_journal_groups_checked=matched,
        sqlite_quick_check=sqlite_check, original_files_unchanged=True, fingerprints=after,
        live_service_verified=False, new_model_or_recovery_calls=0)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'persisted-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'mobile-openapi.json').write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'incidents_checked': len(details), 'journal_groups_checked': matched,
        'sqlite_check': sqlite_check, 'files_unchanged': before == after, 'output': str(destination)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--b-db', default='runtime/vikunja-b/state.sqlite3')
    parser.add_argument('--dashboard-db', default='runtime/dashboard-api.sqlite3')
    parser.add_argument('--journal', default='runtime/vikunja-web/events.jsonl')
    parser.add_argument('--output', default='runtime/harmony-b')
    args = parser.parse_args()
    paths = [Path(p).resolve() for p in (args.b_db, args.dashboard_db, args.journal, args.output)]
    if any(not p.is_relative_to(ROOT / 'runtime') for p in paths):
        parser.error('审计路径必须位于本项目 runtime 中')
    try:
        audit(*paths)
    except Exception as error:
        print('历史记录审计未通过：' + type(error).__name__ + '；未输出源数据或凭据。')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
