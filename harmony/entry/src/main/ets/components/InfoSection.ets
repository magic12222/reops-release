import { Theme } from '../config/Theme';

@Component
export struct InfoSection {
  @Prop title: string = '';
  @Prop detail: string = '';
  @Prop value: string = '';
  build() {
    Column({ space: 10 }) {
      Text(this.title).fontSize(14).fontWeight(FontWeight.Medium).fontColor(Theme.muted)
      if (this.value.length > 0) {
        Text(this.value).fontSize(24).fontWeight(FontWeight.Medium).fontColor(Theme.accent)
      }
      Text(this.detail).fontSize(13).fontColor(Theme.muted).lineHeight(21)
    }.alignItems(HorizontalAlign.Start).width('100%').padding({ top: 14, bottom: 14 })
    .border({ width: { bottom: 1 }, color: Theme.line })
  }
}
