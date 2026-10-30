export const pages = [
  { id: 'overview', label: 'Overview', href: '/' },
  { id: 'workbench', label: 'Workbench', href: '/workbench' },
  { id: 'execution', label: 'Execution', href: '/execution' },
  { id: 'knowledge-retrieval', label: 'Knowledge', href: '/knowledge-retrieval' },
  { id: 'architecture', label: 'Architecture', href: '/architecture' },
  { id: 'agent', label: 'Agent', href: '/agent' },
  { id: 'recovery', label: 'Recovery', href: '/recovery' },
  { id: 'benchmark', label: 'Benchmark', href: '/benchmark' },
  { id: 'api', label: 'API', href: '/api' },
] as const;

export type PageId = typeof pages[number]['id'];
export const paths = Object.fromEntries(pages.map(page => [page.id, page.href])) as Record<PageId, string>;

// Only former global chapter/workspace hashes migrate. All other hashes stay local.
const legacy: Record<string, string> = {
  '#overview': paths.overview, '#architecture': paths.architecture,
  '#agent': paths.agent, '#records': paths.agent, '#recovery': paths.recovery,
  '#benchmark': paths.benchmark, '#story': '/#story', '#team': '/#team',
  '#evaluation': '/benchmark#evaluation', '#evidence': '/benchmark#evidence',
};

export function resolveRoute(url: URL) {
  const pathname = url.pathname.replace(/\/+$/, '') || '/';
  // #story, #team and evaluation hashes on their owning page are local anchors.
  const migration = legacy[url.hash];
  const destination = migration ? new URL(migration, url.origin) : null;
  const path = pathname === '/workbench' && url.searchParams.get('knowledge') === 'retrieve'
    ? '/knowledge-retrieval' : destination?.pathname ?? pathname;
  const hash = destination?.hash ?? url.hash;
  const page = pages.find(item => item.href === path)?.id ?? 'not-found';
  return { page, hash, href: path + url.search + hash } as const;
}
