import { Check, ChevronRight, Circle, ScanLine } from 'lucide-react';
import { demoSteps } from '../data/demoData';

export function AgentTrajectory({ index, selected, onSelect }: { index: number; selected: number; onSelect: (index: number) => void }) {
  return <div className="agent-trajectory"><div className="workbench-title"><ScanLine size={14} /><span>AGENT TRAJECTORY</span><span className="event-count">{Math.max(0, index + 1)} / 08</span></div><ol>{demoSteps.map((step, i) => <li key={step.event.event_id} className={`${i === index ? 'current' : i < index ? 'done' : 'pending'} ${selected === i ? 'selected' : ''}`}><button disabled={i > index} onClick={() => onSelect(i)} aria-label={`查看步骤 ${i + 1}: ${step.title}`} aria-pressed={selected === i}><span className="step-marker">{i < index ? <Check size={12} /> : <Circle size={i === index ? 7 : 4} fill="currentColor" />}</span><span className="step-time">{(step.at / 1000).toFixed(1).padStart(4, '0')}s</span><div><strong>{step.title}</strong><span>{i <= index ? step.tool : 'Waiting for evidence'}</span></div><ChevronRight size={13} /></button></li>)}</ol></div>;
}
