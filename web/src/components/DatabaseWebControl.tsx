import { useEffect, useRef, useState } from 'react';
import { ControlError, createControlClient } from '../data/webControl';
import type { ControlStatus, PendingConfirmation, WebJob } from '../data/webControl';
import './DatabaseWebControl.css';

const purposeLabels = { experiment: '确认停库实验与必要善后', model: '确认本次模型诊断', recovery: '确认本次数据库恢复' };

export function ConfirmationCard({ pending, job, busy, onConfirm, onCancel }: {
  pending: PendingConfirmation; job: WebJob; busy: boolean;
  onConfirm: (answer: string) => void; onCancel: () => void;
}) {
  const [answer, setAnswer] = useState('');
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = Math.max(0, Math.ceil(pending.expires_at - now / 1000));
  const purpose = pending.request.purpose;
  return <section className="database-confirmation" aria-label="当次人工授权">
    <h4>{purposeLabels[purpose]}</h4>
    <p>{purpose === 'experiment' ? '本次已准备新测试数据。批准后仅停止隔离 PostgreSQL 一次，并在必要时执行独立善后。'
      : purpose === 'model' ? '最多调用模型一次，输出预算 512 Token；用量以当次服务端返回为准。'
        : '批准后仅对本次绑定的隔离 PostgreSQL 执行 restart_service(postgres)，随后独立核验业务。'}</p>
    {job.strategy === 'experience' && purpose === 'model' && <p>本次经验未满足快速通道条件，需要模型诊断确认。</p>}
    <p>目标：ResearchLoop-AI 隔离环境 · API / PostgreSQL</p>
    <details><summary>核对本次绑定对象</summary><pre>{JSON.stringify(pending.request, null, 2)}</pre></details>
    <p>请手动输入以下当次挑战；网页不会自动代填。</p>
    <code className="database-challenge">{pending.challenge}</code>
    <form onSubmit={event => { event.preventDefault(); const value = answer; setAnswer(''); onConfirm(value); }}>
      <label>当次授权回复<input value={answer} onChange={event => setAnswer(event.target.value)} autoComplete="off"
        spellCheck={false} placeholder="手动输入上方完整挑战" disabled={busy || remaining === 0} /></label>
      <div className="database-control-actions">
        <button className="button" disabled={busy || remaining === 0 || answer !== pending.challenge}>确认本次操作</button>
        <button className="trace-button" type="button" onClick={onCancel} disabled={busy}>拒绝并完成必要善后</button>
        <span role="status">{remaining > 0 ? `本次确认剩余 ${remaining} 秒` : '确认已到期，等待流程收口'}</span>
      </div>
    </form>
  </section>;
}

export function DatabaseWebControl({ visible = true }: { visible?: boolean }) {
  const client = useRef(createControlClient()).current;
  const [state, setState] = useState<ControlStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const active = useRef(visible);
  active.current = visible;
  useEffect(() => {
    if (!visible) return;
    let current = true;
    let reading = false;
    const abort = new AbortController();
    const poll = async () => {
      if (reading) return;
      reading = true;
      try {
        const value = await client.status(abort.signal);
        if (current) setState(value);
      } catch { if (current) setState(null); }
      finally { reading = false; }
    };
    void poll();
    const timer = window.setInterval(poll, 1200);
    return () => { current = false; abort.abort(); window.clearInterval(timer); };
  }, [client, visible]);
  const action = async (operation: () => Promise<unknown>, success = '') => {
    setBusy(true); setError(''); setNotice('');
    try {
      await operation();
      const value = await client.status();
      if (active.current) { setState(value); setNotice(success); }
    } catch (err) { if (active.current) setError(err instanceof ControlError ? err.message : '操作未完成，请核对当前状态。'); }
    finally { setBusy(false); }
  };
  const job = state?.job;
  const pending = job?.confirmation;
  const disabled = busy || !state?.enabled || state.busy;
  return <section id="researchloop-controls" className="live-panel experiment-control database-web-control" aria-label="ResearchLoop 演示操作">
    <h3>自己跑一次 <small>ResearchLoop-AI 隔离演示</small></h3>
    <p>在 API 页面配置并测试连接后启动。停库、模型调用和恢复仍逐项向你确认，原项目数据不参与。</p>
    {!state ? <p role="status">操作服务暂未连接，启动与授权保持不可用。</p>
      : !state.enabled && <p role="status">本机网页操作入口尚未启用，历史记录仍可查看。</p>}
    <div className="database-model-heading"><h4>模型连接</h4><span>{state?.model.verified ? '连接已验证' : state?.model.configured ? 'Key 已配置，等待连接测试' : '等待配置 Key'}</span></div>
    <p>{state?.model.name ?? '模型服务'} · {state?.model.model ?? '尚未读取模型'} · <a className="trace-button" href="/api">前往 API 管理</a></p>
    <h4>选择本次路径</h4>
    <div className="database-control-actions">
      <button className="button" disabled={disabled || !state?.model.verified} onClick={() => void action(() => client.start('model'))}>启动模型诊断实验</button>
      <button className="trace-button" disabled={disabled || !state?.model.verified} onClick={() => void action(() => client.start('experience'))}>启动经验复用实验</button>
    </div>
    <p>经验模式只有在当前故障与成功经验严格匹配时才跳过模型。每次新建实验，实际 Token 和验证结果以本次记录为准。</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {job && <div className="database-job-state" role="status">
      <strong>{job.state === 'finished' ? job.result === 'passed' ? '本次验收通过' : job.result === 'rejected' ? '本次未获授权，已结束' : '本次未通过或结果未知，请核对下方台账'
        : job.cancel_requested ? '已请求取消，正在完成必要验证或善后' : pending ? '等待你确认本次操作' : '流程运行中，请等待验证与善后结束'}</strong>
      <p>本次 Trace：{job.trace_id}</p>
      {job.state === 'running' && !pending && <button className="trace-button" disabled={busy || job.cancel_requested} onClick={() => void action(() => client.cancel(job))}>取消本次实验并完成必要善后</button>}
    </div>}
    {visible && pending && job?.state === 'running' && <ConfirmationCard key={pending.id} pending={pending} job={job} busy={busy}
      onConfirm={answer => void action(() => client.confirm(job, pending, answer))}
      onCancel={() => void action(() => client.cancel(job))} />}
  </section>;
}
