"""移动端只读投影；复用工作台快照，不持有模型、授权或执行器。"""
from datetime import datetime, timezone
from typing import Literal
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, model_validator

from workbench.b_privacy import redact
from workbench.contracts import Event, Experience, Incident, ModelCall, Target, Verification, unique_ids

STATES = Literal['observing', 'diagnosing', 'waiting_human', 'executing', 'verifying',
                 'recovered', 'failed', 'unknown']


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class MobileSnapshot(ResponseModel):
    """持久业务引用与当前监控连接独立；不补造目标或就绪状态。"""
    schema_version: Literal['0.1']
    source: Literal['real', 'offline_fixture']
    generated_at: str
    a_status: Literal['ready', 'not_connected']
    b_status: Literal['ready', 'not_connected']
    targets: list[Target]
    incidents: list[Incident]
    experiences: list[Experience]

    @model_validator(mode='after')
    def references(self):
        unique_ids(self.targets)
        unique_ids(self.incidents)
        experience_ids = unique_ids(self.experiences)
        if self.a_status == 'not_connected' and self.targets:
            raise ValueError('unconnected_target_feed')
        if self.b_status == 'not_connected' and (self.incidents or self.experiences):
            raise ValueError('unconnected_agent_feed')
        origins = {i.id: i for i in self.incidents}
        experiences = {e.id: e for e in self.experiences}
        for incident in self.incidents:
            unique_ids(incident.events)
            unique_ids(incident.model_calls)
            if [e.sequence for e in incident.events] != list(range(len(incident.events))):
                raise ValueError('event_order_conflict')
            if not set(incident.experience_ids) <= experience_ids:
                raise ValueError('unknown_experience')
            if incident.diagnosis_source == 'experience' and not incident.experience_ids:
                raise ValueError('experience_evidence_required')
            if incident.status == 'recovered' and incident.verification.status != 'passed':
                raise ValueError('verification_required')
            if any(experiences[key].target_id != incident.target_id for key in incident.experience_ids):
                raise ValueError('experience_target_conflict')
        for experience in self.experiences:
            origin = origins.get(experience.incident_id)
            if origin is None or origin.target_id != experience.target_id:
                raise ValueError('experience_origin_conflict')
            if experience.status == 'verified' and origin.verification.status != 'passed':
                raise ValueError('experience_verification_required')
        return self


class Context(ResponseModel):
    schema_version: Literal['mobile-v1'] = 'mobile-v1'
    source: Literal['real', 'offline_fixture']
    generated_at: str
    a_status: str
    b_status: str


class IncidentSummary(ResponseModel):
    id: str
    target_id: str
    trace_id: str
    title: str
    status: STATES
    severity: None = None
    started_at: str
    updated_at: str
    diagnosis_source: str
    summary: str
    verification: Verification


class Page(Context):
    items: list[IncidentSummary]
    total: int
    limit: int
    offset: int
    has_more: bool
    since: str | None
    until: str | None


class FreshTarget(ResponseModel):
    id: str
    health: Literal['healthy', 'unhealthy', 'unknown']
    monitoring: str
    observed_at: str | None
    age_seconds: float | None
    freshness: Literal['fresh', 'stale', 'unavailable']


class RelatedEvent(Event):
    incident_id: str
    trace_id: str


class Overview(Context):
    total: int
    counts_by_status: dict[str, int]
    since: str | None
    until: str | None
    statistics_scope: Literal['persisted_workbench_incidents_started_at']
    latest_incident_update_at: str | None
    target_health: Literal['healthy', 'unhealthy', 'unknown']
    freshness_threshold_seconds: int
    targets: list[FreshTarget]
    recent_incidents: list[IncidentSummary]
    recent_events: list[RelatedEvent]


class Diagnosis(ResponseModel):
    status: Literal['not_started', 'running', 'succeeded', 'failed', 'unavailable']
    source: str
    diagnosed_at: None = None
    failure_reason: None = None
    calls: list[ModelCall]
    evidence_events: list[Event]


class RunLink(ResponseModel):
    run_id: str
    incident_id: str
    trace_id: str
    source: str
    status: str
    event_ids: list[str]


class Recovery(ResponseModel):
    decision_events: list[Event]
    safety_events: list[Event]
    authorization_events: list[Event]
    execution_events: list[Event]
    verification_events: list[Event]
    verification: Verification
    outcome: Literal['verified', 'failed', 'pending', 'unknown']


class Detail(Context):
    incident: Incident
    severity: None = None
    updated_at: str
    diagnosis: Diagnosis
    knowledge: list[Experience]
    recovery: Recovery
    run_link_status: Literal['matched', 'not_imported', 'unavailable']
    runs: list[RunLink]
    gaps: list[str]


def utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def stamp(value):
    return utc(value).isoformat()


def context(snapshot):
    return {name: getattr(snapshot, name) for name in ('source', 'generated_at', 'a_status', 'b_status')}


def summary(item):
    return {**item.model_dump(exclude={'events', 'model_calls', 'experience_ids'}),
            'severity': None, 'updated_at': max([item.started_at, *[e.timestamp for e in item.events]], key=utc)}


def window(since, until):
    try:
        start, end = stamp(since) if since is not None else None, stamp(until) if until is not None else None
        if start and end and utc(start) > utc(end):
            raise ValueError()
        return start, end
    except (ValueError, OverflowError):
        raise HTTPException(422, 'invalid_time_range') from None


def select(snapshot, status, target_id, since, until):
    return sorted((i for i in snapshot.incidents
        if (status is None or i.status == status) and (target_id is None or i.target_id == target_id)
        and (since is None or utc(i.started_at) >= utc(since))
        and (until is None or utc(i.started_at) < utc(until))),
        key=lambda i: (utc(i.started_at), i.id), reverse=True)


def diagnosis(item):
    last = item.model_calls[-1] if item.model_calls else None
    status = 'not_started'
    if last:
        status = last.status if last.status in {'running', 'failed', 'succeeded'} else 'unavailable'
        if status == 'succeeded' and not (last.response or '').strip():
            status = 'unavailable'
    return {'status': status, 'source': item.diagnosis_source, 'calls': item.model_calls,
            'evidence_events': [e for e in item.events if e.stage in
                                {'localization', 'root_cause_analysis'}]}


def recovery(item):
    def marked(event, codes):
        return event.title in codes or any('event=' + code in event.evidence for code in codes)
    return {'decision_events': [e for e in item.events if e.stage == 'recovery_decision'],
        'safety_events': [e for e in item.events if marked(e, {'safety_and_target_policy_passed', 'dependency_safety_passed'})],
        'authorization_events': [e for e in item.events if marked(e, {'recovery_authorization_required',
            'authorization_missing_expired_or_changed', 'dependency_action_reserved'})
            or 'authorization_consumed_by_a=true' in e.evidence],
        'execution_events': [e for e in item.events if e.stage == 'recovery_execution'],
        'verification_events': [e for e in item.events if e.stage == 'verification'],
        'verification': item.verification,
        'outcome': 'verified' if item.status == 'recovered' and item.verification.status == 'passed'
                   else 'failed' if item.verification.status == 'failed'
                   else 'pending' if item.verification.status == 'pending' else 'unknown'}


def install_mobile_routes(app, reader, store=None, *, token_provider=None, deployment=None):
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        expected = token_provider() if token_provider else os.getenv('REOPS_MOBILE_READ_TOKEN', '')
        if len(expected) < 32:
            raise HTTPException(503, 'mobile_access_not_configured')
        if credentials is None or not secrets.compare_digest(
                credentials.credentials.encode(), expected.encode()):
            raise HTTPException(401, 'mobile_authentication_required', headers={'WWW-Authenticate': 'Bearer'})

    router = APIRouter(prefix='/api/v1/mobile', dependencies=[Depends(authorize)], tags=['mobile'])

    if deployment is not None:
        @router.get('/deployment')
        def deployment_info():
            try:
                return deployment()
            except Exception:
                raise HTTPException(503, 'mobile_data_unavailable') from None

    def snapshot():
        try:
            # Detach, redact again and validate before deriving anything; never mutate the producer.
            raw = MobileSnapshot.model_validate(redact(reader().model_dump()))
            raw.generated_at = stamp(raw.generated_at)
            for target in raw.targets:
                if target.observed_at is not None:
                    target.observed_at = stamp(target.observed_at)
            for item in raw.incidents:
                item.started_at = stamp(item.started_at)
                for event in item.events:
                    event.timestamp = stamp(event.timestamp)
            if raw.b_status != 'ready':
                raise ValueError('agent_feed_unavailable')
            return raw
        except Exception:
            raise HTTPException(503, 'mobile_data_unavailable') from None

    @router.get('/incidents', response_model=Page)
    def incidents(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                  status: STATES | None = None, target_id: str | None = Query(None, min_length=1),
                  since: str | None = None, until: str | None = None,
                  severity: str | None = None):
        if severity is not None:
            raise HTTPException(422, 'severity_not_recorded')
        start, end = window(since, until)
        data = snapshot()
        items = select(data, status, target_id, start, end)
        return {**context(data), 'items': [summary(i) for i in items[offset:offset + limit]],
                'total': len(items), 'limit': limit, 'offset': offset,
                'has_more': offset + limit < len(items), 'since': start, 'until': end}

    @router.get('/overview', response_model=Overview)
    def overview(since: str | None = None, until: str | None = None):
        start, end = window(since, until)
        data = snapshot()
        items = select(data, None, None, start, end)
        counts = {value: 0 for value in STATES.__args__}
        for item in items:
            counts[item.status] += 1
        targets = []
        now = utc(data.generated_at)
        for target in data.targets:
            age = (now - utc(target.observed_at)).total_seconds() if target.observed_at else None
            fresh = (age is not None and 0 <= age <= 60 and target.monitoring == 'watching')
            targets.append({'id': target.id, 'monitoring': target.monitoring,
                'health': target.health if fresh else 'unknown', 'observed_at': target.observed_at,
                'age_seconds': age, 'freshness': 'fresh' if fresh else 'unavailable' if age is None else 'stale'})
        health = ('unhealthy' if any(t['health'] == 'unhealthy' for t in targets)
            else 'healthy' if targets and all(t['health'] == 'healthy' for t in targets) else 'unknown')
        events = sorted(({**e.model_dump(), 'incident_id': i.id, 'trace_id': i.trace_id}
            for i in items for e in i.events), key=lambda e: (utc(e['timestamp']), e['id']), reverse=True)
        return {**context(data), 'total': len(items), 'counts_by_status': counts,
            'since': start, 'until': end, 'statistics_scope': 'persisted_workbench_incidents_started_at',
            'latest_incident_update_at': max((summary(i)['updated_at'] for i in items), key=utc, default=None),
            'target_health': health, 'freshness_threshold_seconds': 60, 'targets': targets,
            'recent_incidents': [summary(i) for i in items[:5]], 'recent_events': events[:10]}

    @router.get('/incidents/{incident_id}', response_model=Detail)
    def detail(incident_id: str):
        data = snapshot()
        item = next((i for i in data.incidents if i.id == incident_id), None)
        if item is None:
            raise HTTPException(404, 'incident_not_found')
        links, link_status = [], 'unavailable'
        if store is not None:
            try:
                for run, events in store.incident_snapshots(item.id, item.trace_id, source=data.source):
                    links.append({'run_id': run.id, 'incident_id': run.incident_id, 'trace_id': run.trace_id,
                        'source': run.source, 'status': run.status, 'event_ids': [e.event_id for e in events]})
                link_status = 'matched' if links else 'not_imported'
            except Exception:
                link_status = 'unavailable'
        gaps = ['severity_not_recorded', 'diagnosis_timestamp_and_failure_reason_not_standardized',
                'updated_at_is_latest_incident_event_not_model_call_time']
        if not any(t.id == item.target_id for t in data.targets):
            gaps.append('target_monitoring_unavailable')
        if link_status != 'matched':
            gaps.append('dashboard_run_' + link_status)
        return {**context(data), 'incident': item, 'updated_at': summary(item)['updated_at'],
            'diagnosis': diagnosis(item), 'knowledge': [e for e in data.experiences if e.id in item.experience_ids],
            'recovery': recovery(item), 'run_link_status': link_status, 'runs': links, 'gaps': gaps}

    # Responses include operational evidence and must not enter shared browser/proxy caches.
    @app.middleware('http')
    async def mobile_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/v1/mobile/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Authorization'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    app.include_router(router)
