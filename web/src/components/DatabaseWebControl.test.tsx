import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ConfirmationCard, DatabaseWebControl } from './DatabaseWebControl';
import type { PendingConfirmation, WebJob } from '../data/webControl';

const pending: PendingConfirmation = { id: 'fixture', challenge: 'AUTHORIZE recovery 0123456789abcdef',
  expires_at: Date.now() / 1000 + 120, request: { purpose: 'recovery', binding: { target: 'postgres' } } };
const job: WebJob = { id: 'fixture', strategy: 'model', state: 'running', incident_id: 'fixture', trace_id: 'fixture',
  experiment_id: null, result: null, error: null, cancel_requested: false, confirmation: pending };

describe('browser operation UI safety', () => {
  it('links to separate API management and disables real actions until connection verification', () => {
    const html = renderToStaticMarkup(<DatabaseWebControl />);
    expect(html).not.toContain('type="password"');
    expect(html).toContain('href="/api"');
    expect(html).toContain('操作服务暂未连接');
    expect(html).toMatch(/disabled="">启动模型诊断实验/);
    expect(html).toMatch(/disabled="">启动经验复用实验/);
    expect(html).toContain('前往 API 管理');
  });
  it('shows the challenge but leaves the manual answer empty and submit disabled', () => {
    const html = renderToStaticMarkup(<ConfirmationCard pending={pending} job={job} busy={false} onConfirm={() => {}} onCancel={() => {}} />);
    expect(html).toContain(pending.challenge);
    expect(html).toContain('value=""');
    expect(html).not.toContain(`value="${pending.challenge}"`);
    expect(html).toMatch(/disabled="">确认本次操作/);
    expect(html).toContain('拒绝并完成必要善后');
    expect(html).toContain('本次绑定');
  });
  it('disables expired challenges and explicitly labels experience fallback model authorization', () => {
    const html = renderToStaticMarkup(<ConfirmationCard pending={{ ...pending, expires_at: 1,
      request: { ...pending.request, purpose: 'model' } }} job={{ ...job, strategy: 'experience' }}
      busy={false} onConfirm={() => {}} onCancel={() => {}} />);
    expect(html).toContain('确认已到期');
    expect(html).toContain('经验未满足快速通道条件');
    expect(html).toMatch(/disabled="">确认本次操作/);
  });
});
