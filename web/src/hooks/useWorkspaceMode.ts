import { navigate, useRoute } from '../navigation/router';

export function useWorkspaceMode<T extends string>(hashes: Record<T, string>, fallback: T) {
  const route = useRoute();
  const mode = (Object.keys(hashes) as T[]).find(value => hashes[value] === route.hash) ?? fallback;
  const selectMode = (next: T) => navigate(hashes[next]);
  return [mode, selectMode] as const;
}
