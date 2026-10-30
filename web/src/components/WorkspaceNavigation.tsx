import type { ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';

type Option<T extends string> = { value: T; title: string; detail: string; icon: ReactNode };

export function WorkspaceNavigation<T extends string>({ label, title, description, options, value, onSelect }: {
  label: string; title: string; description: string;
  options: Option<T>[]; value: T; onSelect: (value: T) => void;
}) {
  return <div className="workspace-navigation">
    <div className="workspace-intro"><span>WORKSPACE</span><h2>{title}</h2><p>{description}</p></div>
    <div className="workspace-options" role="group" aria-label={label}>
      {options.map(option => <button type="button" key={option.value} aria-pressed={value === option.value}
        onClick={() => onSelect(option.value)}>
        {option.icon}<span><strong>{option.title}</strong><small>{option.detail}</small></span><ArrowUpRight size={16} />
      </button>)}
    </div>
  </div>;
}
