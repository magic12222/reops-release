/** 工作台与配置/证据服务分别路由，保持浏览器同源和后端权限检查。 */
export function localProxy(env:Record<string,string>) {
  const dashboard=env.REOPS_DASHBOARD_PROXY||'http://127.0.0.1:8020';
  // String shorthand makes Vite rewrite Host to the upstream address. Keep the
  // browser's allowed local Host so backend same-origin checks remain effective.
  const route=(target:string)=>({target,changeOrigin:false});
  return {'/api/v1/workbench':route(env.REOPS_WORKBENCH_PROXY||dashboard),'/api/v1':route(dashboard)};
}
