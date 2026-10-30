/** Presentation of the existing browser simulation, never an online status model. */
export const labStages = [
  { name: '正常', index: -1 }, { name: '故障', index: 0 },
  { name: '定位', index: 1 }, { name: '恢复', index: 5 }, { name: '验证', index: 6 },
] as const;

export function recoveryLabState(index: number) {
  const stage = index < 0 ? 0 : index === 0 ? 1 : index < 5 ? 2 : index === 5 ? 3 : 4;
  const complete = index >= 7;
  const database = index < 0 || complete ? 'healthy' : index === 6 ? 'checking' : index === 5 ? 'recovering' : 'failed';
  const messages = [
    ['业务路径正常。', '请求依次查询数据库、写入缓存，再返回业务结果。', 'GET /users → 200'],
    ['一个依赖失效，业务路径中断。', 'PostgreSQL 停止，数据库连接失败。API 进程仍存活。', 'GET /users → 503'],
    ['故障信号已关联。', '业务失败与数据库异常关联，开始排查依赖。', 'database_query · failed'],
    ['故障范围收敛到数据库。', 'Redis 健康，连接拒绝指向 PostgreSQL。', 'Connection refused · postgres:5432'],
    ['根因：PostgreSQL 服务停止。', '服务停机与连接拒绝证据一致。', 'postgres_service_down'],
    ['局部恢复动作已选定。', '选定数据库局部重启，通过白名单限定动作范围。', 'restart_service → postgres'],
    ['正在恢复数据库。', '模拟执行器重启 PostgreSQL，等待新的业务核验。', 'restart_service(postgres)'],
    ['服务重启后，继续核验业务。', '重新检查数据库与 /users；业务验证尚未完成。', 'health_check() + GET /users'],
    ['业务恢复，验证通过。', '服务健康与业务请求均已通过模拟验证。', 'GET /users → 200 · 验证通过'],
  ];
  const [title, description, evidence] = messages[Math.min(Math.max(index + 1, 0), 8)];
  return { stage, complete, database, title, description, evidence,
    focused: index >= 2 && index <= 4,
    request: index < 0 || complete ? '200 OK' : index === 6 ? '核验中' : '503 ERROR',
  };
}
