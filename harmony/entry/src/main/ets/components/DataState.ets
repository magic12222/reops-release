import { Theme } from '../config/Theme';
import { LoadState } from '../models/ApiModels';

@Component
export struct DataState {
  @Prop state: LoadState = 'unconfigured';
  @Prop message: string = '';
  retry: () => void = () => {};
  build() {
    Column({ space: 12 }) {
      if (this.state === 'loading') {
        LoadingProgress().width(28).height(28).color(Theme.accent)
      }
      if (this.message) { Text(this.message).fontSize(12).fontColor(Theme.muted).lineHeight(19).width('100%') }
      if (this.state === 'error') {
        Button('重试').id('retryData').fontSize(14).fontColor(Theme.accent)
          .backgroundColor(Theme.surface).onClick(() => this.retry())
      }
    }.width('100%').alignItems(HorizontalAlign.Start).padding({ top: 4, bottom: 6 })
  }
}
