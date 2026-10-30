import { beforeEach as beforeLocaleEach, afterEach as afterLocaleEach } from 'vitest';
import { setLocale } from '../i18n';
beforeLocaleEach(() => setLocale('en'));
afterLocaleEach(() => setLocale('zh-CN'));
import { describe, expect, it } from 'vitest';
import { fixtureSnapshot } from './contract';
import { incidentKnowledgeGraph } from './knowledgeAtlas';
import { workbenchEdgeRoute, workbenchGraphLayout, workbenchNode, workbenchNodeLines } from './workbenchGraphLayout';

describe('Workbench graph geometry', () => {
  it('wraps long unbroken labels without shrinking the node font',()=>{
    expect(workbenchNodeLines('W'.repeat(80))).toEqual(['W'.repeat(12),'W'.repeat(11)+'…']);
    expect(workbenchNodeLines('SQL ready')).toEqual(['SQL ready']);
    expect(workbenchNodeLines('数据库业务恢复验证'.repeat(10))).toHaveLength(2);
  });
  it('preserves every record and relationship and separates node rectangles', () => {
    const data=fixtureSnapshot(); const graph=incidentKnowledgeGraph(data,data.incidents[0]);
    const before=JSON.stringify(graph);const layout=workbenchGraphLayout(graph,true);
    expect(graph.nodes).toHaveLength(15);expect(graph.edges).toHaveLength(14);
    expect(layout.positions.size).toBe(graph.nodes.length);
    const points=[...layout.positions.values()];
    points.forEach((a,i)=>points.slice(i+1).forEach(b=>expect(Math.abs(a.x-b.x)>=workbenchNode.width+16||Math.abs(a.y-b.y)>=workbenchNode.height+16).toBe(true)));
    expect(JSON.stringify(graph)).toBe(before);
    expect(layout.width).toBeLessThanOrEqual(1000);expect(layout.height).toBeLessThanOrEqual(680);
  });
  it('routes incident-to-source links above central nodes, with original endpoints', () => {
    const data=fixtureSnapshot();const graph=incidentKnowledgeGraph(data,data.incidents[0]);const layout=workbenchGraphLayout(graph,true);
    const source=graph.edges.find(edge=>edge.from===`incident:${data.incidents[0].id}`&&edge.to.startsWith('event:'))!;
    const route=workbenchEdgeRoute(source,graph,layout);
    expect(route.path).toContain(' V 46 H ');
    expect(route.label.y).toBeLessThan(80);
    expect(route.path).toMatch(new RegExp(`H ${layout.positions.get(source.to)!.x-workbenchNode.width/2}$`));
    graph.edges.forEach(edge=>expect(workbenchEdgeRoute(edge,graph,layout).path).not.toMatch(/NaN|undefined/));
  });
  it('keeps complete-graph positions stable and supports many real condition nodes', () => {
    const data=fixtureSnapshot();data.experiences[0].conditions=Array.from({length:50},(_,index)=>`Recorded condition ${index}`);
    const graph=incidentKnowledgeGraph(data,data.incidents[0],true);const layout=workbenchGraphLayout(graph,true);
    expect(layout.positions.size).toBe(graph.nodes.length);
    expect(graph.nodes.filter(node=>node.kind==='condition')).toHaveLength(24);
    expect([...layout.positions.values()].every(point=>point.x>=96&&point.x+96<=layout.width&&point.y+32<layout.height)).toBe(true);
    expect(graph.omitted).toBe(26);
  });
});
