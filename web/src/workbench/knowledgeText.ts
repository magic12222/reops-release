import { t } from '../i18n';
import type { KnowledgeNode } from './knowledge';

/** Product knowledge is UI copy. Imported incident evidence remains original text. */
export function knowledgeText(node: KnowledgeNode): string {
  if (node.provenance !== 'curated') return node.value;
  return node.value.split('\n').map(line => {
    const split = line.indexOf(': ');
    return split < 0 ? t(line) : `${t(line.slice(0, split + 1))} ${t(line.slice(split + 2))}`;
  }).join('\n');
}
