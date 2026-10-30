import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync } from 'node:fs';
import { localProxy } from './src/data/localProxy';

export default defineConfig(({ mode }) => {
  const env=loadEnv(mode,'.','REOPS_');
  const proxy=localProxy(env);
  return {
  appType: 'spa',
  define: { __REOPS_RESEARCHLOOP_AVAILABLE__: existsSync('../integrations/researchloop/source/backend/db.py') },
  plugins: [react()],
  // 同源 C 证据读取与独立 ResearchLoop 人工授权；不包含 A 控制凭据。
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
};
});
