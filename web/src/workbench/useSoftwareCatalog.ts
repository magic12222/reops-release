import { useEffect, useRef, useState } from 'react';
import { createSoftwareCatalogClient } from './softwareCatalog';
import type { SoftwareCatalog } from './softwareCatalog';

export function useSoftwareCatalog(active: boolean) {
  const client = useRef(createSoftwareCatalogClient()).current;
  const [data,setData] = useState<SoftwareCatalog | null>(null);
  const [error,setError] = useState('');
  const [pending,setPending] = useState(false);
  const [revision,setRevision] = useState(0);
  const activeRef = useRef(active); activeRef.current = active;
  const generation = useRef(0);
  const mutating = useRef(false);
  useEffect(() => {
    const sequence = ++generation.current;
    if (!active) { setData(null); setError(''); setPending(false); return; }
    const abort = new AbortController(); let busy = false;
    const read = async () => {
      if (busy || mutating.current || document.hidden) return;
      busy = true; const version = generation.current;
      try { const value = await client.read(abort.signal); if (!abort.signal.aborted && activeRef.current && version === generation.current) { setData(value); setError(''); } }
      catch (e) { if (!abort.signal.aborted && activeRef.current && version === generation.current) { setData(null); setError(e instanceof Error ? e.message : 'Local discovery could not be read.'); } }
      finally { busy = false; }
    };
    void read(); const timer = window.setInterval(() => void read(), 3000);
    document.addEventListener('visibilitychange', read);
    return () => { if (generation.current === sequence) generation.current++; abort.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', read); };
  }, [active,revision,client]);
  async function watch(id: string, watching: boolean) {
    if (!activeRef.current || mutating.current) return;
    const version = ++generation.current; mutating.current=true; setPending(true);setError('');
    try { const value = await client.watch(id,watching); if (activeRef.current && version === generation.current) setData(value); }
    catch (e) { if (activeRef.current && version === generation.current) setError(e instanceof Error ? e.message : 'The basic monitor could not be changed.'); }
    finally { mutating.current=false; if (activeRef.current) setPending(false); }
  }
  return {data,error,pending,watch,refresh:()=>setRevision(value=>value+1)};
}
