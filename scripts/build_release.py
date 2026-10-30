"""从显式文件白名单生成独立公开源码快照；不携带原 Git 历史或本机数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    '.gitignore', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'requirements.txt', 'requirements-dev.txt', 'requirements-nexent.txt',
    'requirements-lock.txt', 'pytest.ini', 'docker-compose.yml', 'infra/docker/Dockerfile',
    'workbench/snapshot.schema.json', 'workbench/example.snapshot.json',
    'workbench/a_examples.json', 'integrations/vikunja/compose.yml',
    'web/src/deployment.ts',
    'integrations/vikunja/images.lock.json', 'integrations/vikunja/LICENSE.upstream',
}
TREES = {
    'reops_agent': {'.py'}, 'dashboard_api': {'.py'}, 'workbench': {'.py'},
    'infra': {'.py'}, 'target_system': {'.py', '.sql'}, 'tools': {'.py'},
    'fault_injection': {'.py'}, 'shared': {'.json'},
    'benchmarks': {'.json'},
    'licenses': {'.txt', '.md'},
}
SCRIPTS = {
    'run_dashboard.py', 'run_control.py', 'sync_b_dashboard.py', 'init_local.py',
    'run_workbench_preview.py', 'run_vikunja_workbench.py', 'vikunja_baseline.py',
    'prepare_vikunja_demo.py', 'run_vikunja_acceptance.py', 'researchloop_baseline.py', 'run_researchloop_recovery.py',
    'validate_shared.py', 'scan_secrets.py', 'check_a02_liveness_readonly.py',
    'build_release.py', 'check_release.py', 'install.ps1', 'start.ps1',
    'verify_release.cjs',
}
TESTS = {
    'conftest.py', 'test_model_service_store.py', 'test_model_registry.py',
    'test_web_control.py', 'test_dependency_diagnosis.py', 'test_live_conversation.py',
    'test_run_authorization.py', 'test_vikunja_dependency.py', 'test_vikunja_authorization.py',
    'test_vikunja_session.py', 'test_vikunja_startup.py', 'test_vikunja_web.py',
    'test_workbench_control.py', 'test_knowledge_retrieval.py', 'test_persistence_boundaries.py',
    'test_a_workbench.py', 'test_ab_scenario_contract.py', 'test_b_measurements.py',
    'test_dependency_records.py', 'test_recovery_smoke.py', 'test_researchloop_recovery.py',
    'test_vikunja.py',
}


def selected(name):
    path = Path(name)
    if name in FILES:
        return True
    if path.parts[0] == 'web':
        return (name != 'web/README.md' and name != 'web/run.ps1'
                and path.suffix in {'.ts', '.tsx', '.css', '.json', '.yaml', '.html', '.svg', '.png', '.cjs', '.conf'})
    if path.parts[0] == 'scripts':
        return path.name in SCRIPTS
    if path.parts[0] == 'tests':
        return len(path.parts) == 2 and path.name in TESTS
    return path.parts[0] in TREES and path.suffix in TREES[path.parts[0]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT / 'runtime') or destination.exists():
        raise SystemExit('输出必须为项目 runtime 内尚不存在的目录')
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    candidates = set(filter(None, tracked)) | FILES
    candidates |= {p.relative_to(ROOT).as_posix() for folder in ('licenses',) for p in (ROOT / folder).rglob('*') if p.is_file()}
    candidates |= {'scripts/' + name for name in SCRIPTS}
    included = sorted(name for name in candidates if selected(name) and (ROOT / name).is_file())
    missing = sorted(name for name in FILES if not (ROOT / name).is_file())
    if missing:
        raise SystemExit('缺少必要文件: ' + ', '.join(missing))
    manifest = {}
    for name in included:
        source, target = ROOT / name, destination / name
        if source.is_symlink():
            raise SystemExit('不允许符号链接: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    # 清单按实际字节校验；防止 Git 在其他电脑自动转换换行符。
    attributes = destination / '.gitattributes'
    attributes.write_bytes(b'* -text\n')
    manifest['.gitattributes'] = hashlib.sha256(attributes.read_bytes()).hexdigest()
    (destination / 'release-manifest.json').write_text(json.dumps({
        'version': 'preliminary-2026.10.30',
        'repository': 'https://github.com/magic12222/reops-release',
        'files': manifest,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(included), 'output': str(destination)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
