import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import './PageHierarchy.css';

export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  return <motion.div className={className} initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 22 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-40px' }} transition={{ duration: 0.55, ease: [0.2, 0.8, 0.2, 1] }}>{children}</motion.div>;
}
export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="section-label"><span>{children}</span><span className="label-line" aria-hidden="true" /></div>;
}
export function SimulationBadge({ children = 'SIMULATION' }: { children?: ReactNode }) {
  return <span className="simulation-badge"><span className="badge-dot" />{children}</span>;
}
export function Brand({ small = false }: { small?: boolean }) {
  return <span className={`brand ${small ? 'small' : ''}`}><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M5 22V5h12a6 6 0 0 1 0 12h-5m4 0 7 8" /><circle cx="5" cy="25" r="1" /></svg>ReOps<span className="brand-period">.</span></span>;
}
export function ArrowLink({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return <a href={href} className={`arrow-link ${className}`}>{children}<ArrowUpRight size={17} /></a>;
}
