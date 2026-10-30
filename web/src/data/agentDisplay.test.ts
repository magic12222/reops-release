import { describe, expect, it } from 'vitest';
import { agentDuration, agentSentence, agentTime, agentValueName } from './agentDisplay';
import { compactEvidence, evidenceFactText } from './evidencePresentation';
import { setLocale } from '../i18n';

describe('Agent display vocabulary and formatting', () => {
  it('uses field-scoped exact mappings, with safe unknown and prototype-name handling', () => {
    expect(agentValueName('root_cause', 'postgres_service_down')).toBe('PostgreSQL 服务不可用');
    expect(agentValueName('action', 'postgres_service_down')).toBe('postgres_service_down');
    expect(agentValueName('root_cause', 'postgres_service_down_extra')).toBe('postgres_service_down_extra');
    expect(agentValueName('root_cause', 'constructor')).toBe('constructor');
    expect(agentValueName('constructor', 'postgres')).toBe('postgres');
    expect(agentValueName('execution_status', 'succeeded')).toBe('执行成功');
    expect(agentValueName('verification_status', 'not_run')).toBe('未执行验证');
    expect(agentValueName('failed_step', 'database_query')).toBe('数据库查询');
    expect(agentValueName('root_cause', 'health_check_failed_cause_unknown')).toBe('健康检查失败，原因未确定');
    expect(agentValueName('root_cause', 'redis_service_down')).toBe('redis_service_down');
    const services = { postgres: { status: 'unhealthy' }, api: { status: 'healthy' }, other: { status: 'custom_health' } };
    expect(evidenceFactText({ key: 'services', label: '服务观测', value: services })).toBe('postgres: 不健康 · api: 健康 · other: custom_health');
    expect(services.postgres.status).toBe('unhealthy');
  });
  it('preserves recorded sentences and translation-key collisions in both languages', () => {
    try {
      for (const locale of ['zh-CN', 'en'] as const) {
        setLocale(locale);
        for (const text of ['Unknown', 'Succeeded', '未知', 'PostgreSQL is unavailable and service-down evidence is consistent.',
          'connection refused: postgres:5432', 'custom recorded diagnosis']) expect(agentSentence(text)).toBe(text);
        expect(evidenceFactText({ key: 'message', label: 'Message', value: 'Unknown' })).toBe('Unknown');
        expect(evidenceFactText({ key: 'action', label: 'Action', value: 'succeeded' })).toBe('succeeded');
        expect(agentValueName('execution_status', 'succeeded')).toBe(locale === 'en' ? 'Execution succeeded' : '执行成功');
      }
    } finally { setLocale('zh-CN'); }
  });
  it('formats numbers and units without losing zero or promoting out-of-range confidence', () => {
    const fact = (key: string, value: number) => evidenceFactText({ key, value, label: key });
    expect(fact('confidence', 0.94)).toBe('94%');
    expect(fact('confidence', 0.94567)).toBe('94.57%');
    expect(fact('confidence', 94)).toBe('94');
    expect(fact('risk', 0)).toBe('0%');
    expect(fact('duration_ms', 3120.256)).toBe('3,120.26 ms');
    expect(agentDuration(0)).toBe('0 ms');
  });
  it('formats local timestamps consistently and distinguishes missing and invalid values', () => {
    const date = new Date(2026, 9, 11, 9, 5, 3);
    expect(agentTime(date.toISOString())).toBe('2026-10-11 09:05:03');
    expect(agentTime(null)).toBe('未提供');
    expect(agentTime(null, '未提供（无独立时间戳）')).toBe('未提供（无独立时间戳）');
    expect(agentTime('invalid')).toBe('时间不可解析');
  });
  it('marks truncation in the preview while preserving the source string', () => {
    const text = '日志内容'.repeat(100);
    expect(compactEvidence(text)).toHaveLength(180);
    expect(compactEvidence(text).endsWith('…')).toBe(true);
    expect(text).toHaveLength(400);
  });
});
