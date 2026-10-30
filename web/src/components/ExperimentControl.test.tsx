import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ExperimentControl } from './ExperimentControl';

describe('C4 initial authorization state', () => {
  it('keeps the request disabled until server capability is read', () => {
    const html = renderToStaticMarkup(<ExperimentControl />);
    expect(html).toContain('请求一次受控实验');
    expect(html).toContain('disabled');
    expect(html).toContain('请求入口关闭');
    expect(html).toContain('cleanup');
  });
});
