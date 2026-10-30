import { RecoveryDemo } from '../components/RecoveryDemo';
import { WorkbenchAgentTrace } from '../workbench/WorkbenchAgentTrace';
export function AgentPage({ active }: { active: boolean }) {
  const params = typeof window === 'undefined' ? new URLSearchParams() : new URLSearchParams(window.location.search);
  const trace = params.get('trace');
  return params.get('feed') === 'workbench' && trace ? <WorkbenchAgentTrace active={active} traceId={trace} /> : <RecoveryDemo mode="api" active={active} />;
}
