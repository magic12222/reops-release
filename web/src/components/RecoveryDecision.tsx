import { useState } from 'react';
import { Check, ChevronRight } from 'lucide-react';
import { candidateActions } from '../data/demoData';

export function RecoveryDecision({ ready }: { ready: boolean }) {
  const [selected, setSelected] = useState(0);
  const action = candidateActions[selected];
  return <div className={`recovery-decision ${ready ? 'ready' : ''}`}><div className="mini-heading"><span>RECOVERY DECISION</span><span>{ready ? '4 ACTIONS EVALUATED' : 'STRATEGY PREVIEW'}</span></div><div className="decision-layout"><div className="candidate-list">{candidateActions.map((item, i) => <button key={item.name} className={selected === i ? 'active' : ''} aria-pressed={selected === i} onClick={() => setSelected(i)}><span>{item.name}<small className={i === 0 ? 'recommended' : ''}>{item.status}</small></span>{i === 0 ? <Check size={14} /> : <ChevronRight size={13} />}</button>)}</div><div className="decision-detail"><code>{action.code}</code><p>{action.reason}</p><div className="decision-stats"><div><span>Risk</span><strong>{action.risk.toFixed(2)}</strong><i><b style={{ width: `${action.risk * 100}%` }} /></i></div><div><span>Impact</span><strong>{action.impact}</strong></div><div><span>Expected time</span><strong>{action.time}</strong></div><div><span>Confidence</span><strong>{Math.round(action.confidence * 100)}%</strong></div></div><small>候选方案及评分均为演示数据。</small></div></div></div>;
}
