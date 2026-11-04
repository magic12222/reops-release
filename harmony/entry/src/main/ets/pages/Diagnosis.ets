import { Theme } from '../config/Theme';
import { InfoSection } from '../components/InfoSection';
import { DataState } from '../components/DataState';
import { EventRows } from '../components/EventRows';
import { LoadState, ExperienceRecord, ModelCall } from '../models/ApiModels';
import { MobileDetail } from '../models/MobileModels';
import { stageEvents, statusLabel, incidentTitle } from '../services/Presentation';

@Component
export struct Diagnosis {
  @State private evidenceExpanded: boolean = false;
  @State private sourceExpanded: boolean = false;
  @Prop detail: MobileDetail | null = null;
  @Prop state: LoadState = 'idle';
  @Prop message: string = '';
  retry: () => void = () => {};
  chooseIncident: () => void = () => {};
  back: () => void = () => {};
  build() {
    Column({ space: 14 }) {
      Text('AI 诊断').id('diagnosisTitle').fontSize(30).fontWeight(FontWeight.Medium).fontColor(Theme.text).width('100%')
      DataState({ state: this.state, message: this.message, retry: this.retry })
      if (this.detail) {
        Text(incidentTitle(this.detail.incident.title)).fontSize(20).fontColor(Theme.text).width('100%')
        Text(`历史诊断记录 · 执行来源：${statusLabel(this.detail.diagnosis.source)}`)
          .fontSize(12).fontColor(Theme.accent).width('100%')
        Row({ space: 12 }) {
          Column({ space: 8 }) {
            Text('模型分析').fontSize(12).fontColor(Theme.muted)
            Text(statusLabel(this.detail.diagnosis.status)).fontSize(24).fontColor(Theme.accent)
          }.layoutWeight(1).alignItems(HorizontalAlign.Start).padding(16).backgroundColor(Theme.surface).borderRadius(8)
          Column({ space: 8 }) {
            Text('业务验证').fontSize(12).fontColor(Theme.muted)
            Text(statusLabel(this.detail.recovery.verification.status)).fontSize(24).fontColor(Theme.accent)
          }.layoutWeight(1).alignItems(HorizontalAlign.Start).padding(16).backgroundColor(Theme.surface).borderRadius(8)
        }.width('100%')
        InfoSection({ title: '已保存的模型回复', detail: `${this.detail.diagnosis.calls.length} 条调用记录 · 原文展示` })
        if (this.detail.diagnosis.calls.length === 0) {
          Text('没有模型调用记录。').fontSize(14).fontColor(Theme.muted).width('100%')
        }
        ForEach(this.detail.diagnosis.calls, (m: ModelCall) => {
          Column({ space: 8 }) {
            Text(`${m.model || '模型不可用'} · ${statusLabel(m.status)} · 耗时 ${m.duration_ms === null ? '不可用' : `${m.duration_ms} ms`}`)
              .fontSize(13).fontColor(Theme.muted).width('100%')
            Text(m.response ?? '尚无模型回复原文。').fontSize(14).fontColor(Theme.text).lineHeight(24).width('100%')
          }.width('100%').padding(16).backgroundColor(Theme.surface).borderRadius(8).alignItems(HorizontalAlign.Start)
        }, (m: ModelCall) => m.id)
        Button(this.evidenceExpanded ? '收起证据、经验与验证' : '查看证据、经验与验证')
          .id('toggleDiagnosisEvidence').fontColor(Theme.accent).backgroundColor(Theme.surface)
          .onClick(() => { this.evidenceExpanded = !this.evidenceExpanded; })
        if (this.evidenceExpanded) {
        InfoSection({ title: '根因与关键证据', detail: '后端提供定位/RCA阶段记录，未提供统一根因字段、诊断时间和失败原因时明确不可用；不从摘要或回复推测确定根因。' })
        EventRows({ events: this.detail.diagnosis.evidence_events, empty: '根因分析记录不可用。' })
        InfoSection({ title: '观测与检测证据', detail: '历史记录与当前监控状态分开，保留证据所属状态。' })
        EventRows({ events: stageEvents(this.detail.incident, ['observe', 'failure_detection']), empty: '观测证据不可用。' })
        InfoSection({ title: '关联经验', detail: '仅展示本故障明确引用的经验；历史根因、动作和验证不当作本次执行事实。' })
        if (this.detail.knowledge.length === 0) {
          Text('当前故障未关联可用经验。').fontSize(14).fontColor(Theme.muted).width('100%')
        }
        ForEach(this.detail.knowledge, (e: ExperienceRecord) => {
          Column({ space: 8 }) {
            Text(e.title).fontSize(17).fontColor(Theme.text).width('100%')
            Text(`${statusLabel(e.status)} · ${e.id}`).fontSize(12).fontColor(Theme.accent).width('100%')
            Text(`历史根因：${e.root_cause || '不可用'}\n症状：${e.symptom || '不可用'}\n历史动作：${e.action || '不可用'}`).fontSize(14).fontColor(Theme.muted).width('100%')
            Text(`来源Incident：${e.incident_id}\n适用条件：${e.conditions.join('；') || '不可用'}`).fontSize(12).fontColor(Theme.muted).width('100%')
          }.padding({ bottom: 14 }).width('100%').alignItems(HorizontalAlign.Start)
        }, (e: ExperienceRecord) => e.id)
        InfoSection({ title: '已有恢复记录', value: statusLabel(this.detail.recovery.outcome), detail: '以下为该故障原始决策/执行记录，无执行操作；重叠事件不累加成动作次数。' })
        EventRows({ events: this.detail.recovery.decision_events, empty: '没有恢复决策记录。' })
        EventRows({ events: this.detail.recovery.execution_events, empty: '没有恢复执行记录。' })
        InfoSection({ title: '独立恢复验证', value: statusLabel(this.detail.recovery.verification.status), detail: '仅取本Incident/Trace的验证；命令成功、历史经验或模型成功不能替代业务验证。' })
        if (this.detail.recovery.verification.checks.length === 0) {
          Text('没有可用验证检查项。').fontSize(14).fontColor(Theme.muted).width('100%')
        }
        ForEach(this.detail.recovery.verification.checks, (line: string, index: number) => {
          Text(line).fontSize(14).fontColor(Theme.text).width('100%')
        }, (line: string, index: number) => `${index}`)
        EventRows({ events: this.detail.recovery.verification_events, empty: '没有独立验证事件。' })
        }
        Button(this.sourceExpanded ? '收起来源信息' : '记录来源与完整标识')
          .id('toggleDiagnosisSource').fontColor(Theme.muted).backgroundColor(Theme.background)
          .onClick(() => { this.sourceExpanded = !this.sourceExpanded; })
        if (this.sourceExpanded) {
          Text(`Incident  ${this.detail.incident.id}\nTrace  ${this.detail.incident.trace_id}`).id('diagnosisIdentity')
            .fontSize(12).fontColor(Theme.muted).lineHeight(20).width('100%')
          Text(this.detail.incident.summary).fontSize(12).fontColor(Theme.muted).width('100%')
          Text('规则执行与模型分析分别记录；历史回复不代表当前重新调用模型。').fontSize(12).fontColor(Theme.muted).width('100%')
          ForEach(this.detail.diagnosis.calls, (m: ModelCall) => {
            Text(m.id).fontSize(12).fontColor(Theme.muted).width('100%')
          }, (m: ModelCall) => m.id)
        }
        Button('返回故障详情').id('diagnosisDetail').fontColor(Theme.accent).backgroundColor(Theme.surface).onClick(() => this.back())
      } else {
        InfoSection({ title: '尚未选择可用故障', detail: '从故障列表或最近事件选择记录后，只读查询诊断。' })
        Button('选择故障').id('chooseIncident').fontSize(14).backgroundColor(Theme.surface).fontColor(Theme.accent).onClick(() => this.chooseIncident())
      }
    }.alignItems(HorizontalAlign.Start).width('100%')
  }
}
