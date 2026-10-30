import type { KnowledgeEdge, KnowledgeGraph } from './knowledge';

export const workbenchNode = { width: 192, height: 64 };
const centers = [110, 350, 590, 850];
const firstRow = 112;
const rowGap = 82;

// Conservative glyph widths prevent long words from entering adjacent node lanes.
// Full labels remain in SVG titles, accessible names, and the source inspector.
export function workbenchNodeLines(value: string): string[] {
  const fit = (text: string, budget: number) => {
    let width=0, count=0;
    for (const char of text) {
      const next=/[\u3400-\u9fff]/.test(char)?13:/[MWm@%]/.test(char)?12.5:/[w]/.test(char)?10.5:/[A-Z0-9]/.test(char)?8.8:/[ilItf .,:;!'|]/.test(char)?4.8:7.7;
      if(width+next>budget)break;
      width+=next;count+=char.length;
    }
    return count;
  };
  const first=fit(value,160);
  if(first===value.length)return [value];
  const space=value.lastIndexOf(' ',first);
  const split=space>first/2?space:first;
  const rest=value.slice(split).trim();const second=fit(rest,160);
  return [value.slice(0,split),second===rest.length?rest:rest.slice(0,fit(rest,147))+'…'];
}

// View-only geometry. Keep IDs, fields, endpoints, and complete-graph positions stable.
export function workbenchGraphLayout(graph: KnowledgeGraph, incidentScope: boolean) {
  const lane = new Map(graph.nodes.map(node => [node.id, incidentScope && node.eventId ? 3 : node.column]));
  const columns = centers.map((_, index) => graph.nodes.filter(node => lane.get(node.id) === index));
  const positions = new Map(columns.flatMap((column, index) => column.map((node, row) => [node.id, { x: centers[index], y: firstRow + row * rowGap }] as const)));
  return { positions, lane, width: 960, height: Math.max(320, firstRow + (Math.max(1, ...columns.map(column => column.length)) - 1) * rowGap + 56) };
}

export function workbenchEdgeRoute(edge: KnowledgeEdge, graph: KnowledgeGraph, layout: ReturnType<typeof workbenchGraphLayout>) {
  const a = layout.positions.get(edge.from)!;
  const b = layout.positions.get(edge.to)!;
  const direction = Math.sign(b.x - a.x) || 1;
  const x1 = a.x + direction * workbenchNode.width / 2;
  const x2 = b.x - direction * workbenchNode.width / 2;
  if (Math.abs(layout.lane.get(edge.from)! - layout.lane.get(edge.to)!) > 1) {
    // Route cross-column links above the nodes, then down the empty inter-column lane.
    const siblings = graph.edges.filter(item => item.from === edge.from && layout.lane.get(item.to) === layout.lane.get(edge.to));
    const offset = siblings.findIndex(item => item.to === edge.to) % 7;
    const top = 46 + offset * 6;
    const left = x1 + direction * (16 + offset * 3);
    const right = x2 - direction * (16 + offset * 3);
    return { path: `M ${x1} ${a.y} H ${left} V ${top} H ${right} V ${b.y} H ${x2}`, label: { x: (left + right) / 2, y: top - 7, anchor: 'middle' as const } };
  }
  const middle = (x1 + x2) / 2;
  return { path: `M ${x1} ${a.y} C ${middle} ${a.y}, ${middle} ${b.y}, ${x2} ${b.y}`,
    label: { x: a.y === b.y ? middle : x2 - direction * 8, y: b.y - 9, anchor: a.y === b.y ? 'middle' as const : direction > 0 ? 'end' as const : 'start' as const } };
}
