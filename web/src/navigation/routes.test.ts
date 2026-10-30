import { describe, expect, it } from 'vitest';
import { pages, resolveRoute } from './routes';

const resolve = (href: string) => resolveRoute(new URL(href, 'http://localhost'));
describe('page URL compatibility', () => {
  it.each(pages)('resolves $href independently', ({ id, href }) => {
    expect(resolve(href)).toEqual({ page: id, href, hash: '' });
  });
  it.each([
    ['overview', '/'], ['architecture', '/architecture'], ['agent', '/agent'],
    ['records', '/agent'], ['recovery', '/recovery'], ['benchmark', '/benchmark'],
    ['story', '/#story'], ['team', '/#team'],
    ['evaluation', '/benchmark#evaluation'], ['evidence', '/benchmark#evidence'],
  ])('migrates the old #%s bookmark to %s', (hash, href) => {
    expect(resolve(`/#${hash}`).href).toBe(href);
    expect(resolve(`/recovery#${hash}`).href).toBe(href);
  });
  it('retains local anchors and query parameters', () => {
    expect(resolve('/agent?source=real#run-evidence')).toEqual({ page: 'agent', hash: '#run-evidence', href: '/agent?source=real#run-evidence' });
    expect(resolve('/benchmark#evidence').href).toBe('/benchmark#evidence');
    expect(resolve('/#story').href).toBe('/#story');
    expect(resolve('/architecture/#layer-panel').href).toBe('/architecture#layer-panel');
    expect(resolve('/?source=real#records').href).toBe('/agent?source=real');
  });
  it('handles unknown pages explicitly', () => {
    expect(resolve('/missing').page).toBe('not-found');
  });
  it('opens legacy embedded retrieval links on the independent page with the exact trace',()=>{
    const result=resolve('/workbench?source=real&knowledge=retrieve&trace=trace-exact');
    expect(result.page).toBe('knowledge-retrieval');expect(result.href).toContain('/knowledge-retrieval?');expect(result.href).toContain('trace=trace-exact');
  });
});
