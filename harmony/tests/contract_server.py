"""Local contract fixture server, never imported or packaged by the application.

Only loopback binding; all payloads explicitly offline_fixture. No real services,
databases, models, fault injection or recovery are accessed.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlparse, parse_qs, unquote


def fixture():
    def event(event_id, seq, stage, status, timestamp, detail):
        return dict(id=event_id, sequence=seq, timestamp=timestamp, stage=stage, status=status,
                    title=detail, detail=detail, evidence=['TEST ONLY: contract evidence'])
    first = dict(id='fixture-incident-1', target_id='fixture-target', trace_id='fixture-trace-1',
                 title='TEST ONLY: PostgreSQL incident', started_at='2026-11-03T00:00:00Z', status='recovered',
                 diagnosis_source='rule', summary='TEST ONLY: rule diagnosis summary', experience_ids=['fixture-exp'],
                 events=[event('fixture-observe', 0, 'observe', 'succeeded', '2026-11-03T00:00:00Z', 'TEST ONLY: observation'),
                         event('fixture-root', 1, 'root_cause_analysis', 'succeeded', '2026-11-03T00:00:01Z', 'TEST ONLY: root cause evidence'),
                         event('fixture-execute', 2, 'recovery_execution', 'succeeded', '2026-11-03T00:00:02Z', 'TEST ONLY: recorded execution'),
                         event('fixture-verify', 3, 'verification', 'succeeded', '2026-11-03T00:00:03Z', 'TEST ONLY: business verification')],
                 model_calls=[], verification=dict(status='passed', checks=['TEST ONLY: business check passed']))
    second = dict(id='fixture-incident-2', target_id='fixture-target', trace_id='fixture-trace-2',
                  title='TEST ONLY: pending incident', started_at='2026-11-03T01:00:00Z', status='unknown',
                  diagnosis_source='unknown', summary='', experience_ids=[], events=[], model_calls=[],
                  verification=dict(status='unknown', checks=[]))
    return dict(schema_version='0.1', source='offline_fixture', generated_at='2026-11-03T02:00:00Z',
                a_status='ready', b_status='ready',
                targets=[dict(id='fixture-target', name='TEST ONLY target', runtime='docker', health='unknown',
                              monitoring='watching', observed_at=None, components=[], allowed_actions=[])],
                incidents=[first, second], experiences=[dict(id='fixture-exp', target_id='fixture-target',
                    incident_id='fixture-incident-1', title='TEST ONLY: linked experience', symptom='TEST ONLY: symptom',
                    root_cause='TEST ONLY: historical root cause', action='TEST ONLY: historical action',
                    conditions=['TEST ONLY condition'], status='verified')])


def serve(port, directory):
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / 'mode.txt'
    token_file = directory / 'ephemeral-read-credential.local.json'
    payload = json.loads((Path(__file__).resolve().parents[1] / 'tests/mobile-v1.fixture.json').read_text(encoding='utf-8'))
    if not state.exists(): state.write_text('valid', encoding='utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            mode = state.read_text(encoding='utf-8').strip()
            path = urlparse(self.path).path
            expected = json.loads(token_file.read_text(encoding='utf-8'))['value']
            authorized = self.headers.get('Authorization', '') == 'Bearer ' + expected
            with (directory / 'requests.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps({'path': self.path, 'mode': mode, 'authorized': authorized, 'at': time.time()}) + '\n')
            code, value = 200, {}
            if mode == 'timeout': time.sleep(10)
            if mode == 'slow': time.sleep(5)
            if not authorized or mode == '401':
                code, value = 401, {'detail': 'mobile_authentication_required'}
            elif mode == '403':
                code, value = 403, {'detail': 'TEST ONLY denied'}
            elif mode == '503':
                code, value = 503, {'detail': 'mobile_data_unavailable'}
            elif mode == 'redirect':
                code, value = 302, {}
            elif path == '/api/v1/mobile/overview':
                value = payload['paged_overview'] if mode == 'paged' else payload['empty' if mode == 'empty' else 'valid']['overview']
            elif path == '/api/v1/mobile/incidents':
                offset = int(parse_qs(urlparse(self.path).query).get('offset', ['0'])[0])
                if mode == 'paged': value = payload['paged'].get(str(offset), payload['paged']['40'])
                else: value = payload['empty' if mode == 'empty' else 'valid']['page']
            elif path.startswith('/api/v1/mobile/incidents/'):
                identifier = unquote(path.rsplit('/', 1)[1])
                if mode in ['detail-404', 'empty'] or identifier not in ['fixture-incident-1', 'fixture-incident-2']:
                    code, value = 404, {'detail': 'incident_not_found'}
                else:
                    value = json.loads(json.dumps(payload['valid']['detail' if identifier == 'fixture-incident-1' else 'pending_detail']))
                    if mode == 'wrong-trace': value['runs'][0]['trace_id'] = 'different-trace'
                    if mode == 'missing': del value['recovery']['verification']
                    if mode == 'wrong-incident': value['incident']['id'] = 'other-incident'
            else:
                code, value = 404, {'detail': 'old route not available'}
            if mode == 'missing' and path.endswith('overview'): value = {'schema_version': 'mobile-v1'}
            if mode == 'missing' and path == '/api/v1/mobile/incidents':
                value = json.loads(json.dumps(value))
                del value['items'][0]['verification']
            encoded = b'{' if mode == 'bad-json' else json.dumps(value, ensure_ascii=False).encode()
            try:
                self.send_response(code)
                if code == 302: self.send_header('Location', 'http://127.0.0.1:18882/never-follow')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers(); self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'TEST ONLY mobile-v1 server http://127.0.0.1:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18882)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.directory)
