import { Theme } from '../config/Theme';
import { InfoSection } from '../components/InfoSection';
import { DataState } from '../components/DataState';
import { LoadState } from '../models/ApiModels';
import { MobileOverview, FreshTarget, IncidentSummary } from '../models/MobileModels';
import { statusLabel, timeLabel, incidentTitle } from '../services/Presentation';

@Component
export struct Overview {
  @Prop state: LoadState = 'unconfigured';
  @Prop message: string = '';
  @Prop overview: MobileOverview | null = null;
  retry: () => void = () => {};
  select: (id: string, trace: string) => void = () => {};
  showIncidents: () => void = () => {};
  build() {
    Column({ space: 16 }) {
      Text('监控概览').id('overviewTitle').fontSize(28).fontWeight(FontWeight.Medium).fontColor(Theme.text).width('100%')
      Text('电脑端业务监控 · 鸿蒙手机查看').fontSize(12).fontColor(Theme.muted).width('100%')
      DataState({ state: this.state, message: this.message, retry: this.retry })
      if (this.overview) {
        Column({ space: 12 }) {
          Row() {
            Text('当前业务健康').fontSize(14).fontColor(Theme.muted).layoutWeight(1)
            Text(this.overview.a_status === 'ready' ? '监控已连接' : '监控未连接').fontSize(12).fontColor(Theme.accent)
          }.width('100%')
          Text(statusLabel(this.overview.target_health)).id('overviewHealth').fontSize(36).fontWeight(FontWeight.Bold)
            .fontColor(this.overview.target_health === 'unhealthy' ? '#F3B5AA' : Theme.accent).width('100%')
          if (this.overview.targets.length === 0) {
            Text('尚无实时采样，历史记录仍可查询。').fontSize(13).fontColor(Theme.muted).width('100%')
          }
          ForEach(this.overview.targets, (target: FreshTarget) => {
            Text(`${target.id === 'reops-vikunja-demo' ? 'Vikunja 业务服务' : target.id} · ${statusLabel(target.health)}`)
              .fontSize(14).fontColor(Theme.text).width('100%')
            Text(`采样 ${timeLabel(target.observed_at)} · ${target.freshness === 'fresh' ? '新鲜采样' : target.freshness === 'stale' ? '采样已过期' : '暂无采样'}`)
              .fontSize(12).fontColor(Theme.muted).width('100%')
          }, (target: FreshTarget) => target.id)
        }.padding(18).width('100%').backgroundColor(Theme.surface).borderRadius(10).alignItems(HorizontalAlign.Start)
        Row() {
          Text('历史故障').fontSize(18).fontColor(Theme.text).layoutWeight(1)
          Button('全部记录').id('overviewIncidents').fontSize(13).fontColor(Theme.accent).backgroundColor(Theme.background)
            .onClick(() => this.showIncidents())
        }.width('100%')
        Row({ space: 12 }) {
          Column({ space: 6 }) { Text(`${this.overview.total}`).fontSize(28).fontColor(Theme.text); Text('记录总数').fontSize(12).fontColor(Theme.muted) }.layoutWeight(1)
          Column({ space: 6 }) { Text(`${this.overview.counts_by_status['recovered']}`).fontSize(28).fontColor(Theme.accent); Text('已恢复').fontSize(12).fontColor(Theme.muted) }.layoutWeight(1)
          Column({ space: 6 }) { Text(`${this.overview.counts_by_status['failed']}`).fontSize(28).fontColor(Theme.text); Text('失败记录').fontSize(12).fontColor(Theme.muted) }.layoutWeight(1)
        }.width('100%').padding({ top: 8, bottom: 12 })
        Text(`未知 ${this.overview.counts_by_status['unknown']} · 处理中 ${this.overview.total - this.overview.counts_by_status['recovered'] - this.overview.counts_by_status['failed'] - this.overview.counts_by_status['unknown']} · 历史结果与当前健康分别统计`)
          .fontSize(12).fontColor(Theme.muted).width('100%')
        Text('最近故障').fontSize(18).fontColor(Theme.text).width('100%')
        ForEach(this.overview.recent_incidents.slice(0, 3), (item: IncidentSummary) => {
          Button() {
            Column({ space: 8 }) {
              Row() { Text(incidentTitle(item.title)).fontSize(16).fontColor(Theme.text).layoutWeight(1); Text(statusLabel(item.status)).fontSize(12).fontColor(Theme.accent) }.width('100%')
              Text(`${timeLabel(item.started_at)} · 业务验证${statusLabel(item.verification.status)}`).fontSize(12).fontColor(Theme.muted).width('100%')
            }.padding(16).alignItems(HorizontalAlign.Start)
          }.id(`recent-incident-${item.id}`).type(ButtonType.Normal).backgroundColor(Theme.surface).width('100%').borderRadius(8)
            .onClick(() => this.select(item.id, item.trace_id))
        }, (item: IncidentSummary) => item.id)
      } else {
        InfoSection({ title: '连接你的监控服务', detail: '点击右上角连接，可读取实时业务状态与历史诊断。' })
      }
    }.alignItems(HorizontalAlign.Start).width('100%')
  }
}
