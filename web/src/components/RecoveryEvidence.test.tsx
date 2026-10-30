import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { RecoveryEvidence } from './RecoveryEvidence';

const render = (index: number, selected = Math.max(0, index)) => renderToStaticMarkup(createElement(RecoveryEvidence, { index, selected, onSelect: () => {} }));
describe('Recovery evidence layers', () => {
  it('keeps the first fold factual and the full preset script explicitly separate', () => {
    const html = render(-1, 7);
    const firstLayer = html.split('class="lab-event-details"')[0];
    expect(firstLayer).toContain('没有已发生的恢复证据');
    expect(firstLayer).not.toContain('business: 200');
    expect(firstLayer).not.toContain('Verification passed');
    expect(html).toContain('完整预设脚本');
    expect(html).toContain('预设模拟事件 · 尚未回放');
    expect(html).not.toContain(' open');
  });
  it('removes the secondary Agent inspector while retaining the full raw event', () => {
    const html = render(7, 5);
    expect(html).not.toContain('Agent policy');
    expect(html).not.toContain('Memory / Skill');
    expect(html).not.toContain('<dt>Reason</dt>');
    expect(html).toContain('已回放的模拟事件');
    expect(html).toContain('原始模拟事件 JSON');
    expect(html).toContain('evt-demo-6');
    expect(html).toContain('不含任意 shell');
  });
});
