# HarmonyOS只读业务接口契约

版本：mobile-v1。本文定义手机读取概览、故障历史及诊断证据的接口，原Snapshot和Run接口保持兼容。

## 数据来源与运行方式

手机概览读取电脑端Vikunja业务监控及持久历史；本机监控页操作App自己的专用缓存文件，两者独立。本机页面不具备读取其他应用私有数据的权限。

`--history-read-only`仅查询既存历史，不启动业务采样。`--live-monitoring`通过独立任务读写基线连接Vikunja并持续采样，不启动模型或自动恢复。手机展示已保存模型回复，查询不发起新推理。

Windows私网入口使用HTTPS、独立Bearer和子网限制，仅开放移动GET路径。额外鉴权的`GET /api/v1/mobile/deployment`返回deployment-v1，包括实例、源码指纹、记录指纹、历史数量和监控状态。mode为persisted_history_read_only或live_monitoring_with_persisted_history。此路径不属于三条mobile-v1业务响应结构。详细配置见[移动端说明](../harmony/README.md)及[项目指南](../README.md)。

## mobile-v1 请求约定

三条新增路由已挂载到 Dashboard 和独立工作台服务，也可通过原Dashboard的移动只读模式提供。所有请求均为 GET、无请求体。`Base URL` 是服务根地址，不包含 `/api/v1`。C 将其作为可切换配置，不能写死电脑回环地址。跨设备入口由 A 确认；Dashboard或移动只读模式持有同源 Dashboard Store 时可附带 Run 链接，独立工作台返回 `run_link_status=unavailable`。

每个请求必须带 `Authorization: Bearer <当前专用查询凭据>`。后端通过当前进程 `REOPS_MOBILE_READ_TOKEN` 注入至少32字符的随机凭据；缺失/过短时所有新增路由返回503，错误或缺失 Header 返回401。凭据不放源码、文档、命令参数、报告或移动端公开配置仓库；由 A 通过安全渠道配置。它只有这三条 GET 的读取权，不产生监控、模型或恢复批准。响应包括 `Cache-Control: no-store`，浏览器/网关不得缓存业务明文。

| Method / Path | 参数、缺省值、范围 | 200 内容 | 特有错误 |
|---|---|---|---|
| GET /api/v1/mobile/overview | since、until 可空 | Overview：统计、缓存目标健康、最近5故障/10事件 | 非法时间422；未接数据源503 |
| GET /api/v1/mobile/incidents | limit=20（1..100）、offset=0（≥0）；status、target_id、since、until 可空 | Page：items、total、limit、offset、has_more | 非法分页/状态/时间422；severity 参数422 |
| GET /api/v1/mobile/incidents/{incident_id} | 必填原始 string ID，URL 编码；不生成新 ID | Detail：完整故障、诊断、经验、恢复/验证、精确 Run 引用、缺口 | 缺失记录404；无数据源503 |

全部接口共享错误：401 `mobile_authentication_required`（含 WWW-Authenticate: Bearer）；503 `mobile_access_not_configured` 或 `mobile_data_unavailable`；405 不支持的 HTTP 方法。参数错误为422，FastAPI 类型/范围校验使用 `detail` 数组；时间口径错误 `{"detail":"invalid_time_range"}`，严重程度筛选 `{"detail":"severity_not_recorded"}`。404为 `{"detail":"incident_not_found"}`。503不返回数据库路径、原异常或凭据。错误出现时 C 保留旧数据显示“读取失败/上次数据”，不可更新为健康或空库。

`since`/`until` 接受带时区 ISO 8601，按 Incident.started_at 的 `[since, until)` 过滤；都省略时统计全部可读取持久历史。空字符串不可用作时间值（客户端应省略）；不把查询时间当故障发生时间。所有输出的 generated_at / observed_at / started_at / Event.timestamp / 派生 updated_at 统一 UTC `+00:00`，C 可转换 Asia/Shanghai 展示。原模型请求/回复是脱敏原文，内部时间不重新改写。

排序为 started_at 倒序，再 ID 倒序。`total` 是同一快照过滤后的总数，不是当前页数量；offset 超界返回200空 items、has_more=false。读到新故障后从 offset=0 刷新再追加分页；offset 分页期间可能有插入/状态改变，客户端按原 ID 去重，不能承诺跨请求固定页。建议前台每5秒刷新；隐藏/离页暂停，失败退避；详情有模型运行时仍只做 GET。此建议是客户端轮询，不启动后端采样。

### 字段与 null

精确类型也可在实际服务 `/openapi.json` 的 Page / Overview / Detail / Incident / Event / ModelCall / Experience / Verification 查看；运行只读审计脚本会生成 `runtime/harmony-b/mobile-openapi.json`，没有真实运行记录或凭据。

| 对象 | 字段 / 类型 / null 规则 |
|---|---|
| 公共 Context | schema_version 固定 string mobile-v1；source 为 real / offline_fixture；generated_at string；a_status、b_status 为 ready / not_connected。ready 只代表接线，不代表健康或真实模型调用；a_status=not_connected时仍可读已连接BStore的历史 |
| IncidentSummary | id、target_id、trace_id、title、status、started_at、updated_at、diagnosis_source、summary 均 string；severity 恒 null；verification 为 Verification。updated_at 是开始时间与事件时间的最大值，不包含无时间字段的 ModelCall 更新 |
| Incident | Summary 中原始字段（不含 severity/updated_at），另 events: Event[]、model_calls: ModelCall[]、experience_ids: string[]；故障上下文与来源保留在 summary/events/evidence，不额外伪造 Observation |
| Page | Context + items: IncidentSummary[]；total/limit/offset: integer；has_more: boolean；since/until: string 或 null |
| Overview | Context + total: integer；counts_by_status: Record<IncidentStatus,integer>（含0项）；since/until 可 null；statistics_scope 固定 persisted_workbench_incidents_started_at；latest_incident_update_at: string 或 null；target_health: healthy / unhealthy / unknown；freshness_threshold_seconds: integer=60；targets: FreshTarget[]；recent_incidents: IncidentSummary[]；recent_events: RelatedEvent[] |
| FreshTarget | id: string；monitoring: watching / paused / not_connected；health: healthy / unhealthy / unknown；observed_at: string 或 null；age_seconds: number 或 null（未来采样可为负且不算 fresh）；freshness: fresh / stale / unavailable |
| Event | id: string；sequence: integer≥0（单个 Incident 内连续）；timestamp/stage/status/title/detail: string；evidence: string[]。RelatedEvent 额外带 incident_id/trace_id 防止最近事件混配 |
| ModelCall | id/model/request: string；response: string 或 null；status: running / succeeded / failed / unknown；duration_ms/input_tokens/output_tokens: integer≥0 或 null；redacted: true。null 表示未记录，不补0；没有调用时 calls=[] |
| Verification | status: passed / failed / pending / unknown；checks: string[]。passed 是已存独立业务验证事实，不由 API 存活/命令退出码推断 |
| Experience | id/target_id/incident_id/title/symptom/root_cause/action: string；conditions: string[]；status: verified / failed / retired / unverified。action 是经验描述，不是当前执行事实 |
| Diagnosis | status: not_started / running / succeeded / failed / unavailable；source 保留原 diagnosis_source；diagnosed_at/failure_reason 当前为 null（上游无统一字段）；calls: ModelCall[]；evidence_events: Event[]（定位/RCA） |
| Recovery | decision_events/safety_events/authorization_events/execution_events/verification_events: Event[]；verification: Verification；outcome: verified / failed / pending / unknown |
| RunLink | run_id/incident_id/trace_id/source/status: string；event_ids: string[]；只返回 source + incident + trace 三者完全一致的已导入 Dashboard Run。具体 Run/Event 原始详情沿用旧查询接口，但移动网关不要直接开放这些未鉴权路径 |
| Detail | Context + incident: Incident；severity: null；updated_at: string；diagnosis: Diagnosis；knowledge: Experience[]（精确 experience_ids 引用）；recovery: Recovery；run_link_status: matched / not_imported / unavailable；runs: RunLink[]；gaps: string[] |

IncidentStatus：observing / diagnosing / waiting_human / executing / verifying / recovered / failed / unknown。
Event.stage：observe / failure_detection / localization / root_cause_analysis / recovery_decision / recovery_execution / verification / experience_update。
Event.status：running / succeeded / failed / skipped / waiting_human / unknown。
diagnosis_source：model / experience / rule / unknown。

### 状态的业务含义

`Diagnosis.status` 取保存顺序中最新 ModelCall：running / failed 原样；succeeded 必须有非空 response；unknown 或成功但无回复为 unavailable；没有调用为 not_started。只有经验或规则时不能显示“AI 已诊断成功”。`source=rule` 且 calls 有成功回复是合法的：原固定恢复由规则执行，后续模型分析独立保存。完整模型回复保留在 calls.response，B 不生成新的根因、不重新发起诊断；失败/不确定原始记录保留在 calls 与 evidence_events，failure_reason=null 不能被写成“没有错误”。

Recovery 按原 stage 展示决策与动作；只有精确安全事件才能进入 safety_events，明确授权等待/消费证据进入 authorization_events。各项数组可重叠，不得加总当成动作次数。授权等待不等于已授权；消费不等于执行；skipped 不算执行成功。只有原 Incident=recovered 且 Verification=passed 才输出 outcome=verified；命令 succeeded、SQL ready、经验 verified 或计划生成都不能独立得到此结果。计划/动作类型和时间以事件 title/evidence/timestamp 为准，上游未记录时返回空数组，不从历史经验补计划。不重建授权 ID 或虚构 Verify ID。

`target_health` 仅汇总缓存采样：watching 且 observed_at 不晚于 generated_at、相差≤60秒才可信；过期/暂停/未连接/缺时间均 unknown。有 fresh unhealthy 则整体 unhealthy；至少一个目标且全部 fresh healthy 才 healthy。历史目标也可能使汇总 unknown，这是保守展示，不代表刚探测过。60秒只是展示的新鲜度阈值，不改变 A 的采样或恢复策略。generated_at 仅代表投影响应生成时间。

### 请求与 JSON 示例

概览请求：`GET {Base URL}/api/v1/mobile/overview`；无请求体，携前述 Bearer Header。空但已连接数据库的合法200响应如下（结构示例，不是真实实验）：

```json
{"schema_version":"mobile-v1","source":"real","generated_at":"2026-11-02T09:00:00+00:00","a_status":"ready","b_status":"ready","total":0,"counts_by_status":{"observing":0,"diagnosing":0,"waiting_human":0,"executing":0,"verifying":0,"recovered":0,"failed":0,"unknown":0},"since":null,"until":null,"statistics_scope":"persisted_workbench_incidents_started_at","latest_incident_update_at":null,"target_health":"unknown","freshness_threshold_seconds":60,"targets":[],"recent_incidents":[],"recent_events":[]}
```

分页请求：`GET {Base URL}/api/v1/mobile/incidents?limit=1&offset=0&status=recovered`。下列业务字段来自本机持久记录，generated_at 为查询时刻示例，不代表新故障或新模型调用：

```json
{"schema_version":"mobile-v1","source":"real","generated_at":"2026-11-02T09:00:00+00:00","a_status":"ready","b_status":"ready","items":[{"id":"incident-vikunja-auto-ece1a7a790ba418f8c6fde29e2604790","target_id":"reops-vikunja-demo","trace_id":"trace-vikunja-auto-279d01e1d2334ca5a30999348031d70b","title":"Automatic dependency recovery","status":"recovered","severity":null,"started_at":"2026-10-30T11:46:25.660220+00:00","updated_at":"2026-10-30T11:48:41.164269+00:00","diagnosis_source":"rule","summary":"Dependency audit projection · fixed execution policy · original model calls 0 · original B loop false","verification":{"status":"passed","checks":["fresh_business_read_and_sql;observation_id=obs-vikunja-89ca4a18287a46f2abd65e8cc260ba48","fresh_business_read_and_sql;observation_id=obs-vikunja-3b753a9d812b4b27b0704639d3d92eef"]}}],"total":13,"limit":1,"offset":0,"has_more":true,"since":null,"until":null}
```

详情请求：`GET {Base URL}/api/v1/mobile/incidents/incident-vikunja-auto-f5aa13bcbeaf47f499af8e7f5cd91fdf`。完整200响应见脚本生成的 `persisted-audit.json` 的 detail；以下是独立结构示例，fixture ID 明确标记，无模型/恢复/验证发生：

```json
{"schema_version":"mobile-v1","source":"offline_fixture","generated_at":"2026-11-02T09:00:00+00:00","a_status":"ready","b_status":"ready","incident":{"id":"fixture-empty","target_id":"fixture-target","trace_id":"fixture-trace","title":"尚未诊断的结构示例","started_at":"2026-11-02T09:00:00+00:00","status":"observing","diagnosis_source":"unknown","summary":"","events":[],"model_calls":[],"experience_ids":[],"verification":{"status":"pending","checks":[]}},"severity":null,"updated_at":"2026-11-02T09:00:00+00:00","diagnosis":{"status":"not_started","source":"unknown","diagnosed_at":null,"failure_reason":null,"calls":[],"evidence_events":[]},"knowledge":[],"recovery":{"decision_events":[],"safety_events":[],"authorization_events":[],"execution_events":[],"verification_events":[],"verification":{"status":"pending","checks":[]},"outcome":"pending"},"run_link_status":"unavailable","runs":[],"gaps":["severity_not_recorded","diagnosis_timestamp_and_failure_reason_not_standardized","updated_at_is_latest_incident_event_not_model_call_time","dashboard_run_unavailable"]}
```

## 数据关系、兼容性与验收

逻辑链：Incident.id → 同一 Incident.trace_id → 内嵌 Event / ModelCall → experience_ids 精确引用 → Event 的 decision/safety/authorization/execution → verification 与原检查证据。Experience.incident_id 指向其来源故障，通常与当前使用它的故障不同；必须同 target，不能把来源故障当当前故障。Knowledge 为已有引用，不调用新检索算法；实际模型请求内的检索回执与 evidence 保留原值。后端可能保存多个模型轮次，最后一轮失败不删除前轮原记录。

Dashboard Run 只在已导入时按 incident_id + trace_id + source 查询，读 Run 和 Event 使用同一 SQLite 快照。查询接口没有主动导入、生成合成 Run 或迁移历史数据。独立工作台未注入 Dashboard Store 时 unavailable；已提供 Store 但没有精确匹配时 not_imported；Dashboard 读故障也为 unavailable（主 BStore 详情仍可读）。BStore 不可用或引用冲突时整体503，不能伪装200空列表。

读取已有数据库使用SQLite只读模式，不创建缺失库。单库读取使用同一快照，两个数据库及JSONL投影之间没有跨存储事务，可能存在同步延迟。分页基于工作台快照生成。
