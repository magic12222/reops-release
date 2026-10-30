import { useEffect, useState } from 'react';
import { freshBusinessVerifications, memoryHits, readDatabaseExperiments, recoveryLatency, repairUsage } from '../data/databaseExperiments';
import type { DatabaseExperiment } from '../data/databaseExperiments';
import './DatabaseExperimentLedger.css';

const results = { passed: '验收通过', failed: '未通过', rejected: '已拒绝', unknown: '结果未知' };

export function DatabaseExperimentRecord({ item }: { item: DatabaseExperiment }) {
  const report = item.report;
  const usage = repairUsage(report);
  const latency = recoveryLatency(report);
  const hits = memoryHits(report);
  const waiting = item.state === 'waiting_authorization';
  const source = report?.diagnosis_source === 'provider' ? '真实模型诊断'
    : report?.diagnosis_source === 'memory/rule-supported' ? '经验与当前规则证据' : '尚未提供';
  return <article className="experiment-record">
    <h4>{source} · {waiting ? '等待原终端授权或运行中' : results[item.result]}</h4>
    <p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</time></p>
    <dl>
      <div><dt>诊断与规划路径</dt><dd>{source}{hits.length > 0 && ` · 命中 ${hits.length} 条成功经验`}</dd></div>
      <div><dt>修复模型调用</dt><dd>{typeof report?.model_calls === 'number' ? report.model_calls : '尚未提供'}</dd></div>
      <div><dt>修复推理 Token</dt><dd>{usage ? <><strong>{usage.total.toLocaleString('zh-CN')}</strong>（输入 {usage.input} / 输出 {usage.output}）<br />
        <small>{usage.source === 'no_model_calls' ? '未调用模型 · 已核对 provider 与请求计数' : '当次服务端原始 usage'}</small></> : '暂无完整实测'}</dd></div>
      <div><dt>恢复时延</dt><dd>{latency === null ? '暂无完整实测' : `${latency.toFixed(3)} 秒`}<br /><small>固定恢复命令提交 → 第二次 fresh 业务验证通过</small></dd></div>
      <div><dt>业务验证</dt><dd>{freshBusinessVerifications(report) === 2 ? '两次 fresh 验证通过：原项目读取、SQL、新写入及读回' : '尚未确认两次 fresh 业务验证'}</dd></div>
      <div><dt>Memory</dt><dd>{report?.memory_written === true && (report.error === null || report.error === undefined) ? '已写入并严格读回'
        : report?.memory_written === true ? '已写入，完整核验未确认' : '尚未确认写入'}</dd></div>
      <div><dt>独立善后</dt><dd>{report?.cleanup_outcome === 'succeeded' ? '环境复核通过' : report?.cleanup_outcome === 'unknown' ? '结果未知' : '尚未确认'}
        {typeof report?.cleanup_extra_restarts === 'number' && ` · 额外重启 ${report.cleanup_extra_restarts} 次`}</dd></div>
      <div><dt>科研生成</dt><dd>{report && typeof report.generation_measurements === 'object'
        && report.generation_measurements !== null && 'enabled' in report.generation_measurements
        && report.generation_measurements.enabled === false ? '本实验未启用，与修复消耗分开统计' : '未提供生成消耗证据'}</dd></div>
    </dl>
    {item.review_required && !waiting && <p role="alert">需要人工核查，后续数据库实验已阻断。</p>}
    <details><summary>查看关联与原始证据</summary>
      <p>Experiment：{item.id}<br />Incident：{item.incident_id}<br />Trace：{item.trace_id}</p>
      {hits.length > 0 && <p>命中经验：{hits.join('、')}</p>}
      <pre>{JSON.stringify(report ?? { state: item.state }, null, 2)}</pre>
    </details>
  </article>;
}

export function DatabaseComparison({ items }: { items: DatabaseExperiment[] }) {
  const completed = items.filter(item => item.state === 'finished').slice(0, 2).reverse();
  if (completed.length < 2) return null;
  return <div className="database-comparison"><h4>最近两次已结束记录</h4>
    <div className="database-comparison-scroll"><table>
      <thead><tr><th>诊断路径</th><th>模型调用</th><th>修复 Token</th><th>恢复时延</th><th>结果</th></tr></thead>
      <tbody>{completed.map(item => {
        const usage = repairUsage(item.report);
        const latency = recoveryLatency(item.report);
        return <tr key={item.id}>
          <td>{item.report?.diagnosis_source === 'provider' ? '模型诊断' : item.report?.diagnosis_source === 'memory/rule-supported' ? '经验快速通道' : '未提供'}</td>
          <td>{typeof item.report?.model_calls === 'number' ? item.report.model_calls : '—'}</td>
          <td>{usage ? usage.total : '暂无实测'}</td><td>{latency === null ? '暂无实测' : `${latency.toFixed(3)} 秒`}</td>
          <td>{results[item.result]}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </div>;
}

export function DatabaseExperimentLedger({ visible = true }: { visible?: boolean }) {
  const [items, setItems] = useState<DatabaseExperiment[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    let busy = false;
    const controller = new AbortController();
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const value = await readDatabaseExperiments(controller.signal);
        if (active) { setItems(value); setError(false); }
      } catch { if (active) { setError(true); setItems(null); } }
      finally { busy = false; }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [visible]);
  return <section className="live-panel experiment-control database-ledger" aria-label="ResearchLoop 数据库实验台账">
    <h3>ResearchLoop-AI <small>隔离数据库实验 · REAL</small></h3>
    <p>独立目标为 API 与 PostgreSQL。下列数据来自真实实验台账；健康基线、故障恢复和环境善后分别核验。原项目及历史科研数据不参与实验。</p>
    <p>实验通过终端或上方网页操作区逐项人工授权；记录区只读。两次记录只证明本轮路径变化，不承诺普遍提速或 Token 下降。</p>
    {error ? <p role="alert">数据库实验台账不可达或格式无效，未使用样例补充。</p>
      : items === null ? <p role="status">正在读取真实数据库实验记录…</p>
        : items.length === 0 ? <p>暂无数据库实验记录。</p>
          : <><DatabaseComparison items={items} />{items.map(item => <DatabaseExperimentRecord key={item.id} item={item} />)}</>}
  </section>;
}
