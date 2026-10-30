import { useRef } from 'react';
import { t, useLocale } from '../i18n';
import {motion,useReducedMotion} from 'motion/react';
import { pages, type PageId } from '../navigation/routes';
import { useRoute } from '../navigation/router';
import { OverviewPage } from './OverviewPage';
import { ArchitecturePage } from './ArchitecturePage';
import { AgentPage } from './AgentPage';
import { RecoveryPage } from './RecoveryPage';
import { BenchmarkPage } from './BenchmarkPage';
import { ApiPage } from './ApiPage';
import { WorkbenchPage } from './WorkbenchPage';
import { ExecutionPage } from './ExecutionPage';
import {KnowledgeRetrievalPage} from './KnowledgeRetrievalPage';

export function PageOutlet() {
  useLocale();
  const { page } = useRoute();
  const reduced=useReducedMotion();
  const visited = useRef(new Set<PageId>());
  if (page === 'agent' || page === 'recovery' || page === 'workbench' || page === 'execution' || page === 'knowledge-retrieval') visited.current.add(page);
  return <>
    {pages.map(item => {
      const active = page === item.id;
      if (!active && !visited.current.has(item.id)) return null;
      return <motion.div initial={false} animate={{opacity:active?1:0,y:active?0:6}} transition={{duration:reduced?0:.24,ease:'easeOut'}} key={item.id} data-page={item.id} hidden={!active} className={`route-page route-${item.id}`}>
        {item.id === 'overview' ? <OverviewPage /> : item.id === 'architecture' ? <ArchitecturePage />
          : item.id === 'agent' ? <AgentPage active={active} /> : item.id === 'recovery' ? <RecoveryPage active={active} />
          : item.id === 'api' ? <ApiPage /> : item.id === 'knowledge-retrieval' ? <KnowledgeRetrievalPage active={active}/> : item.id === 'execution' ? <ExecutionPage active={active}/> : item.id === 'workbench' ? <WorkbenchPage active={active} /> : <BenchmarkPage />}
      </motion.div>;
    })}
    {page === 'not-found' && <section data-page="not-found" className="route-page shell section"><h1>{t('页面不存在')}</h1><a href="/">{t('返回 Overview')}</a></section>}
  </>;
}
