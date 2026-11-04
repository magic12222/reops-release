import { Theme } from '../config/Theme';
import { InfoSection } from '../components/InfoSection';
import { DataState } from '../components/DataState';
import { EventRows } from '../components/EventRows';
import { LoadState } from '../models/ApiModels';
import { IncidentSummary, MobileDetail, RunLink } from '../models/MobileModels';
import { statusLabel, timeLabel, incidentTitle } from '../services/Presentation';

@Component
export struct Incidents {
  @State private sourceExpanded: boolean = false;
  @Prop state: LoadState = 'unconfigured';
  @Prop message: string = '';
  @Prop items: IncidentSummary[] = [];
  @Prop hasMore: boolean = false;
  @Prop detail: MobileDetail | null = null;
  @Prop showDetail: boolean = false;
  @Prop detailState: LoadState = 'idle';
  @Prop detailMessage: string = '';
  retry: () => void = () => {};
  retryDetail: () => void = () => {};
  loadMore: () => void = () => {};
  select: (id: string, trace: string) => void = () => {};
  back: () => void = () => {};
  diagnose: () => void = () => {};
  build() {
    Column({ space: 14 }) {
      Text('故障记录').id('incidentsTitle').fontSize(30).fontWeight(FontWeight.Medium).fontColor(Theme.text).width('100%')
      if (this.showDetail) {
        Button('返回故障列表').id('backToList').fontColor(Theme.accent).backgroundColor(Theme.surface).onClick(() => this.back())
        DataState({ state: this.detailState, message: this.detailMessage, retry: this.retryDetail })
        if (this.detail) {
          Text(incidentTitle(this.detail.incident.title)).id('incidentDetailTitle').fontSize(22).fontColor(Theme.text).width('100%')
          InfoSection({ title: '故障状态', value: statusLabel(this.detail.incident.status), detail: `开始：${timeLabel(this.detail.incident.started_at)}\n目标：${this.detail.incident.target_id}` })
          Button('查看诊断与验证').id('openDiagnosis').fontColor(Theme.background).backgroundColor(Theme.accent).onClick(() => this.diagnose())
          Row({ space: 16 }) {
            Text(`${this.detail.incident.events.length} 个事件`).fontSize(13).fontColor(Theme.muted)
            Text(`${this.detail.diagnosis.calls.length} 条模型记录`).fontSize(13).fontColor(Theme.muted)
          }.width('100%')
          Text(`Run：${this.detail.run_link_status === 'not_imported' ? '未导入' : this.detail.run_link_status === 'unavailable' ? '不可用' : '已关联'}`)
            .fontSize(12).fontColor(Theme.muted).width('100%')
          Button(this.sourceExpanded ? '收起完整记录' : '查看完整记录与证据').id('toggleIncidentSource')
            .fontColor(Theme.accent).backgroundColor(Theme.surface).onClick(() => { this.sourceExpanded = !this.sourceExpanded; })
          if (this.sourceExpanded) {
          Text(`Incident  ${this.detail.incident.id}\nTrace  ${this.detail.incident.trace_id}`).id('incidentIdentity')
            .fontSize(12).fontColor(Theme.muted).lineHeight(22).width('100%').copyOption(CopyOptions.InApp)
          InfoSection({ title: '故障摘要', detail: this.detail.incident.summary || '该记录没有摘要。' })
          InfoSection({ title: 'Run 关联', detail: this.detail.run_link_status === 'not_imported' ? '未导入：Dashboard 中没有同来源、同 Incident / Trace 的 Run。' :
            this.detail.run_link_status === 'unavailable' ? 'Run 查询不可用；不补造关联。' : '以下为后端精确关联的Run引用；多个Run分别展示，不推断唯一。' })
          ForEach(this.detail.runs, (run: RunLink) => {
            Text(`Run  ${run.run_id}\n状态 ${run.status} · Event引用 ${run.event_ids.length}\n${run.event_ids.join('\n')}`)
              .id(`run-${run.run_id}`).fontSize(13).fontColor(Theme.text).width('100%')
          }, (run: RunLink) => run.run_id)
          Text('移动契约仅提供Run和Event ID引用，不访问旧的未鉴权详情接口。').fontSize(12).fontColor(Theme.muted).width('100%')
          if (this.detail.gaps.length > 0) {
            InfoSection({ title: '数据缺口', detail: this.detail.gaps.join('\n') })
          }
          InfoSection({ title: '故障事件记录', detail: '按后端sequence顺序；当前监控离线不会隐藏历史事件。' })
          EventRows({ events: this.detail.incident.events })
          }
        }
      } else {
        DataState({ state: this.state, message: this.message, retry: this.retry })
        if (this.items.length > 0) {
          Text('真实历史记录 · 按发生时间排序').fontSize(12).fontColor(Theme.muted).width('100%')
          ForEach(this.items, (item: IncidentSummary) => {
            Button() {
              Column({ space: 8 }) {
                Text(incidentTitle(item.title)).fontSize(17).fontColor(Theme.text).width('100%')
                Text(`${statusLabel(item.status)} · ${item.target_id}`).fontSize(13).fontColor(Theme.accent).width('100%')
                Text(timeLabel(item.started_at)).fontSize(12).fontColor(Theme.muted).width('100%')
                Text(`诊断来源：${statusLabel(item.diagnosis_source)} · 业务验证${statusLabel(item.verification.status)}`).fontSize(14).fontColor(Theme.muted).width('100%').maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis })
              }.padding(18).alignItems(HorizontalAlign.Start)
            }.id(`incident-${item.id}`).type(ButtonType.Normal).width('100%').backgroundColor(Theme.surface).borderRadius(8)
              .onClick(() => this.select(item.id, item.trace_id))
          }, (item: IncidentSummary) => item.id)
        } else if (this.state === 'empty') {
          InfoSection({ title: '暂无故障记录', detail: '已连接数据源本次查询为空，不据此推断当前系统健康。' })
        }
        if (this.hasMore) {
          Button('加载更多').id('loadMore').enabled(this.state !== 'loading').backgroundColor(Theme.surface).fontColor(Theme.accent).onClick(() => this.loadMore())
        }
      }
    }.alignItems(HorizontalAlign.Start).width('100%')
  }
}
