import { Theme } from '../config/Theme';
import { WorkbenchEvent } from '../models/ApiModels';
import { statusLabel, timeLabel } from '../services/Presentation';

@Component
export struct EventRows {
  @Prop events: WorkbenchEvent[] = [];
  @Prop empty: string = '没有相关事件记录。';
  build() {
    Column({ space: 14 }) {
      if (this.events.length === 0) {
        Text(this.empty).fontSize(14).fontColor(Theme.muted).width('100%')
      }
      ForEach(this.events, (e: WorkbenchEvent) => {
        Column({ space: 7 }) {
          Text(`${statusLabel(e.stage)} · ${statusLabel(e.status)}`).fontSize(14).fontColor(Theme.accent).width('100%')
          Text(e.title).fontSize(15).fontColor(Theme.text).width('100%')
          if (e.detail && e.detail !== e.title) {
            Text(e.detail).fontSize(14).fontColor(Theme.text).width('100%')
          }
          Text(timeLabel(e.timestamp)).fontSize(12).fontColor(Theme.muted).width('100%')
          ForEach(e.evidence, (line: string, index: number) => {
            Text(`• ${line}`).fontSize(13).fontColor(Theme.muted).lineHeight(21).width('100%')
          }, (line: string, index: number) => `${index}`)
        }.alignItems(HorizontalAlign.Start).padding({ bottom: 14 }).width('100%')
          .border({ width: { bottom: 1 }, color: Theme.line })
      }, (e: WorkbenchEvent) => e.id)
    }.width('100%').alignItems(HorizontalAlign.Start)
  }
}
