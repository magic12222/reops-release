import { Theme } from '../config/Theme';
import { LocalCacheProbe, LocalProbeResult } from '../services/LocalCacheProbe';

@Component
export struct LocalMonitor {
  @State private phase: string = 'unprepared';
  @State private evidence: string = '准备一份专用测试缓存，开始本机检测。';
  @State private checkedAt: string = '尚未检测';
  @State private faultDetected: boolean = false;
  @State private repairVerified: boolean = false;
  private probe: LocalCacheProbe | null = null;
  private timer: number = -1;
  private repairTimer: number = -1;
  private repairAttempted: boolean = false;

  aboutToAppear(): void {
    try {
      const context = this.getUIContext().getHostContext();
      if (!context) throw new Error('context_unavailable');
      this.probe = new LocalCacheProbe(context.cacheDir);
      const result = this.probe.check();
      if (result.status === 'healthy') this.apply(result);
      this.timer = setInterval(() => {
        if (this.probe && this.phase !== 'unprepared') this.apply(this.probe.check());
      }, 1000);
    } catch { this.phase = 'error'; this.evidence = '本机缓存目录暂不可用'; }
  }
  aboutToDisappear(): void {
    if (this.timer !== -1) clearInterval(this.timer);
    if (this.repairTimer !== -1) clearTimeout(this.repairTimer);
    this.timer = -1;
    this.repairTimer = -1;
  }
  private apply(result: LocalProbeResult): void {
    this.evidence = result.message;
    this.checkedAt = new Date(result.checkedAt).toLocaleTimeString();
    if (result.status === 'healthy') {
      if (this.phase !== 'recovered') this.phase = 'normal';
    } else if (result.status === 'missing' || result.status === 'invalid') {
      this.phase = 'fault'; this.faultDetected = true; this.repairVerified = false;
      this.scheduleRepair();
    } else {
      this.phase = 'error'; this.repairVerified = false;
    }
  }
  private prepare(): void {
    if (!this.probe) return;
    this.faultDetected = false; this.repairVerified = false;
    this.repairAttempted = false;
    this.apply(this.probe.rebuild());
  }
  private inject(): void {
    if (!this.probe) return;
    this.repairVerified = false;
    this.repairAttempted = false;
    this.apply(this.probe.injectMissing());
  }
  private scheduleRepair(): void {
    if (this.repairAttempted || this.repairTimer !== -1) return;
    // Confirm the condition after a short debounce; one bounded repair per incident.
    this.repairTimer = setTimeout(() => {
      this.repairTimer = -1;
      if (!this.probe) return;
      const current = this.probe.check();
      if (current.status === 'healthy') { this.apply(current); return; }
      if (current.status === 'missing' || current.status === 'invalid') this.repair();
      else this.apply(current);
    }, 3000);
  }
  private repair(): void {
    if (!this.probe) return;
    this.repairAttempted = true;
    const result = this.probe.rebuild();
    this.apply(result);
    if (result.status === 'healthy') { this.phase = 'recovered'; this.repairVerified = true; }
  }
  build() {
    Column({ space: 16 }) {
      Text('手机本地缓存监控').id('localMonitorTitle').fontSize(25).fontWeight(FontWeight.Medium)
        .fontColor(Theme.text).width('100%')
      Text('鸿蒙本机 · 自动检测与修复 · 演示场景').fontSize(13).fontColor(Theme.accent).width('100%')
      Column({ space: 10 }) {
        Text(this.phase === 'unprepared' ? '待准备' : this.phase === 'normal' ? '正常' :
          this.phase === 'recovered' ? '恢复通过' : this.phase === 'error' ? '检测未通过' : '发现故障').id('localProbeStatus')
          .fontSize(34).fontWeight(FontWeight.Bold)
          .fontColor(this.phase === 'fault' || this.phase === 'error' ? '#F3B5AA' : Theme.accent).width('100%')
        Text(this.evidence).id('localProbeEvidence').fontSize(15).lineHeight(24).fontColor(Theme.text).width('100%')
        Text(`上次检测 ${this.checkedAt}`).id('localProbeTimestamp').fontSize(12).fontColor(Theme.muted).width('100%')
      }.width('100%').padding(18).backgroundColor(Theme.surface).borderRadius(10).alignItems(HorizontalAlign.Start)
      Column({ space: 12 }) {
        Text('检测异常 → 自动修复 → 验证通过').fontSize(17).fontColor(Theme.text).width('100%')
        Text(this.faultDetected ? '① 已检测到真实缓存读取失败' : '① 本地读取与内容校验')
          .id('localDetectionStep').fontSize(14).fontColor(this.faultDetected ? '#F3B5AA' : Theme.muted).width('100%')
        Text(this.repairVerified ? '② 已自动重建专用缓存' : this.phase === 'fault' ? '② 异常复查后自动重建' : '② 自动修复已开启')
          .id('localRepairStep').fontSize(14).fontColor(this.repairVerified ? Theme.accent : Theme.muted).width('100%')
        Text(this.repairVerified ? '③ 重新读取并逐字比对：通过' : '③ 等待独立读回验证')
          .id('localVerifyStep').fontSize(14).fontColor(this.repairVerified ? Theme.accent : Theme.muted).width('100%')
      }.width('100%').alignItems(HorizontalAlign.Start)
      if (this.phase === 'unprepared') {
        Button('准备本机监控').id('localPrepare').width('100%').backgroundColor(Theme.accent)
          .fontColor(Theme.background).onClick(() => this.prepare())
      } else {
        Button('清理缓存').id('localInjectFault').width('100%').enabled(this.phase === 'normal' || this.phase === 'recovered')
          .backgroundColor(Theme.surface).fontColor(Theme.text).onClick(() => this.inject())
        if (this.phase === 'error') {
          Button('重试修复').id('localRepair').width('100%').backgroundColor(Theme.accent)
            .fontColor(Theme.background).onClick(() => this.repair())
        }
      }
      Text('仅作用于本应用的专用演示缓存。当前页每秒检测，无需连接电脑。')
        .fontSize(12).fontColor(Theme.muted).lineHeight(20).width('100%')
    }.width('100%').alignItems(HorizontalAlign.Start)
  }
}
