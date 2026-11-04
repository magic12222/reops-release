import { initialConfig, normalizeBaseUrl, ApiConfig } from '../config/ApiConfig';
import { SessionCredential } from '../config/SessionCredential';
import { TestBootstrap } from '../config/TestBootstrap';
import { Theme } from '../config/Theme';
import { LoadState } from '../models/ApiModels';
import { MobileOverview, IncidentSummary, MobileDetail } from '../models/MobileModels';
import { ApiService } from '../services/ApiService';
import { ApiError, errorMessage } from '../services/ApiError';
import { Overview } from './Overview';
import { Incidents } from './Incidents';
import { Diagnosis } from './Diagnosis';
import { LocalMonitor } from './LocalMonitor';
import { timeLabel } from '../services/Presentation';
import BuildProfile from 'BuildProfile';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { common } from '@kit.AbilityKit';
import { decodeConnectionCode } from '../config/ConnectionCode';

@Entry
@Component
struct Index {
  @State private tab: number = 0;
  @State private settings: boolean = false;
  @State private apiInput: string = '';
  @State private tokenDraft: string = '';
  @State private configError: string = '';
  @State private overview: MobileOverview | null = null;
  @State private items: IncidentSummary[] = [];
  @State private listTotal: number = 0;
  @State private hasMore: boolean = false;
  @State private overviewState: LoadState = 'unconfigured';
  @State private listState: LoadState = 'unconfigured';
  @State private detailState: LoadState = 'idle';
  @State private overviewMessage: string = '尚未配置移动只读服务。';
  @State private listMessage: string = '尚未配置移动只读服务。';
  @State private detailMessage: string = '';
  @State private selectedId: string = '';
  @State private selectedTrace: string = '';
  @State private detail: MobileDetail | null = null;
  @State private connected: boolean = false;
  private nextOffset: number = 0;
  private config: ApiConfig = initialConfig();
  private generation: number = 0;
  private detailGeneration: number = 0;
  private pageGeneration: number = 0;
  private contentScroller: Scroller = new Scroller();

  aboutToAppear(): void {
    if (BuildProfile.CONTRACT_TEST) {
      this.apiInput = 'http://127.0.0.1:18882/api/v1';
      this.tokenDraft = TestBootstrap.take();
      this.connect();
    }
  }
  aboutToDisappear(): void { this.disconnect(); }
  onBackPress(): boolean {
    if (this.settings) { this.settings = false; this.tokenDraft = ''; return true; }
    if (this.tab === 2 && this.selectedId) { this.navigate(1); return true; }
    if (this.tab === 1 && this.selectedId) { this.clearSelection(); return true; }
    if (this.tab !== 0) { this.navigate(0); return true; }
    return false;
  }
  private navigate(tab: number): void {
    this.tab = tab; this.settings = false; this.tokenDraft = '';
    this.contentScroller.scrollTo({ xOffset: 0, yOffset: 0 });
  }
  private clearSelection(): void {
    this.detailGeneration++; this.selectedId = ''; this.selectedTrace = ''; this.detail = null;
    this.contentScroller.scrollTo({ xOffset: 0, yOffset: 0 });
  }
  private disconnect(): void {
    this.generation++; this.detailGeneration++; this.pageGeneration++;
    this.config.credential.clear(); this.tokenDraft = ''; this.connected = false;
    this.overview = null; this.items = []; this.detail = null; this.hasMore = false;
    this.selectedId = ''; this.selectedTrace = '';
    this.overviewState = 'unconfigured'; this.listState = 'unconfigured'; this.detailState = 'idle';
    this.overviewMessage = '尚未配置移动只读服务。'; this.listMessage = '尚未配置移动只读服务。';
  }
  private authFailure(error: Error): boolean {
    const message = errorMessage(error);
    if (!(error instanceof ApiError) || (error.code !== 'unauthorized' && error.code !== 'forbidden')) return false;
    this.disconnect();
    this.overviewState = 'error'; this.listState = 'error'; this.detailState = 'error';
    this.overviewMessage = message; this.listMessage = message; this.detailMessage = message;
    return true;
  }
  private async scanConnection(): Promise<void> {
    const version = this.generation;
    this.tokenDraft = ''; this.configError = '';
    try {
      const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
      const options: scanBarcode.ScanOptions = {
        scanTypes: [scanCore.ScanType.QR_CODE], enableAlbum: false, enableMultiMode: false
      };
      const result: scanBarcode.ScanResult = await scanBarcode.startScanForResult(context, options);
      if (!this.settings || version !== this.generation) return;
      const code = decodeConnectionCode(result.originalValue);
      this.apiInput = code.baseUrl; this.tokenDraft = code.token;
      this.configError = '已读入连接信息，请核对上方地址，再点击连接并读取。';
    } catch {
      this.tokenDraft = '';
      this.configError = '扫码未完成或连接码无效/已过期，请重试。';
    }
  }
  private connect(): void {
    const credential = new SessionCredential();
    try {
      const base = normalizeBaseUrl(this.apiInput);
      credential.set(this.tokenDraft);
      this.disconnect();
      this.config = { baseUrl: base, credential: credential, timeoutMs: 8000, testEnvironment: BuildProfile.CONTRACT_TEST };
      this.connected = true; this.configError = ''; this.settings = false;
      this.refresh();
    } catch (error) {
      credential.clear(); this.tokenDraft = '';
      this.configError = error instanceof ApiError ? errorMessage(error as Error) : (error as Error).message;
    }
  }
  private refresh(): void {
    if (!this.connected) { this.settings = true; return; }
    const version = ++this.generation;
    this.pageGeneration++; this.detailGeneration++;
    const service = new ApiService(this.config);
    this.readOverview(service, version); this.readPage(service, version, false);
    if (this.selectedId) this.readDetail();
  }
  private async readOverview(service: ApiService, version: number): Promise<void> {
    this.overviewState = 'loading'; this.overviewMessage = '正在读取概览…';
    try {
      const result = await service.overview();
      if (version !== this.generation) return;
      this.overview = result; this.overviewState = 'ready';
      this.overviewMessage = `${BuildProfile.CONTRACT_TEST ? '测试环境 / FIXTURE' : '已连接'} · 更新 ${timeLabel(result.generated_at)}`;
    } catch (error) {
      if (version !== this.generation || this.authFailure(error as Error)) return;
      this.overviewState = 'error'; this.overviewMessage = errorMessage(error as Error) + (this.overview ? '；以下保留上次数据。' : '');
    }
  }
  private async readPage(service: ApiService, version: number, append: boolean): Promise<void> {
    const pageVersion = ++this.pageGeneration;
    const offset = append ? this.nextOffset : 0;
    this.listState = 'loading'; this.listMessage = '正在读取故障列表…';
    try {
      const page = await service.incidents(offset);
      if (version !== this.generation || pageVersion !== this.pageGeneration) return;
      const combined: IncidentSummary[] = append ? this.items.slice() : [];
      page.items.forEach((item: IncidentSummary) => {
        const position = combined.findIndex((old: IncidentSummary) => old.id === item.id);
        if (position >= 0) {
          if (combined[position].trace_id !== item.trace_id) throw new ApiError('contract');
          combined[position] = item;
        } else combined.push(item);
      });
      this.items = combined; this.nextOffset = page.offset + page.limit; this.hasMore = page.has_more; this.listTotal = page.total;
      this.listState = this.items.length === 0 ? 'empty' : 'ready';
      this.listMessage = `${BuildProfile.CONTRACT_TEST ? '测试环境 / FIXTURE · ' : ''}已加载 ${this.items.length} / ${page.total} 条历史记录`;
    } catch (error) {
      if (version !== this.generation || pageVersion !== this.pageGeneration || this.authFailure(error as Error)) return;
      this.listState = 'error'; this.listMessage = errorMessage(error as Error) + (this.items.length > 0 ? '；以下保留上次数据。' : '');
    }
  }
  private select(id: string, trace: string): void {
    this.selectedId = id; this.selectedTrace = trace; this.detail = null; this.navigate(1); this.readDetail();
  }
  private async readDetail(): Promise<void> {
    if (!this.selectedId || !this.connected) return;
    const version = this.generation; const detailVersion = ++this.detailGeneration;
    const id = this.selectedId; const trace = this.selectedTrace;
    this.detailState = 'loading'; this.detailMessage = '正在读取故障详情…';
    try {
      const result = await new ApiService(this.config).detail(id, trace);
      if (version !== this.generation || detailVersion !== this.detailGeneration) return;
      this.detail = result; this.detailState = 'ready'; this.detailMessage = `历史记录 · 更新 ${timeLabel(result.generated_at)}`;
    } catch (error) {
      if (version !== this.generation || detailVersion !== this.detailGeneration || this.authFailure(error as Error)) return;
      if (error instanceof ApiError && error.status === 404) this.detail = null;
      this.detailState = 'error'; this.detailMessage = errorMessage(error as Error) + (this.detail ? '；以下为上次详情。' : '');
    }
  }
  @Builder
  private navigation(label: string, index: number) {
    Button(label).id(`tab${index}`).type(ButtonType.Normal).layoutWeight(1).height(54).fontSize(12)
      .fontWeight(this.tab === index ? FontWeight.Bold : FontWeight.Normal)
      .fontColor(this.tab === index ? Theme.accent : Theme.muted).backgroundColor(Theme.background)
      .border({ width: { top: this.tab === index ? 2 : 0 }, color: Theme.accent }).onClick(() => this.navigate(index))
  }
  build() {
    Column() {
      Row({ space: 12 }) {
        Text('ReOps').fontSize(24).fontWeight(FontWeight.Bold).fontColor(Theme.text).layoutWeight(1)
        Text(this.tab === 3 ? '手机本地' : '只读').fontSize(12).fontColor(Theme.accent)
        Button(this.settings ? '关闭' : '连接').id('connectionSettings').fontSize(14).height(40)
          .backgroundColor(Theme.surface).fontColor(Theme.text).onClick(() => { this.settings = !this.settings; this.tokenDraft = ''; })
      }.width('100%').padding({ left: 24, right: 24, top: 14, bottom: 18 })
      if (BuildProfile.CONTRACT_TEST) {
        Text('测试环境 / FIXTURE · 非真实后端结果').id('testEnvironmentBanner').fontSize(14).fontColor('#FFD187')
          .width('100%').padding({ left: 24, right: 24, bottom: 10 })
      }
      Scroll(this.contentScroller) {
        Column() {
          if (this.settings) {
            Column({ space: 14 }) {
              Text('服务连接').id('settingsTitle').fontSize(24).fontColor(Theme.text).width('100%')
              Text('填写已授权的 mobile-v1 服务地址与专用只读凭据。仅本次会话使用，不保存到磁盘。')
                .fontSize(14).fontColor(Theme.muted).lineHeight(22)
              Button('扫描电脑连接码').id('scanConnection').width('100%').backgroundColor(Theme.surface)
                .fontColor(Theme.accent).onClick(() => this.scanConnection())
              Text('API Base URL').fontSize(14).fontColor(Theme.text).width('100%')
              TextInput({ placeholder: 'https://主机:端口 或 /api/v1 入口', text: this.apiInput }).id('apiUrl')
                .fontColor(Theme.text).placeholderColor(Theme.muted).backgroundColor(Theme.surface)
                .onChange((value: string) => { this.apiInput = value; })
              Text('专用只读 Token（不含 Bearer 前缀）').fontSize(14).fontColor(Theme.text).width('100%')
              TextInput({ placeholder: '至少32字符，仅本次会话', text: this.tokenDraft }).id('readToken').type(InputType.Password)
                .showPasswordIcon(false).copyOption(CopyOptions.None).fontColor(Theme.text).backgroundColor(Theme.surface)
                .onChange((value: string) => { this.tokenDraft = value; })
              if (this.configError) { Text(this.configError).id('configError').fontSize(14).fontColor('#F3B5AA') }
              Button('连接并读取').id('connectButton').width('100%').backgroundColor(Theme.accent).fontColor(Theme.background).onClick(() => this.connect())
              Button('断开并清除凭据').id('disconnectButton').fontColor(Theme.muted).backgroundColor(Theme.surface)
                .onClick(() => { this.disconnect(); this.configError = ''; })
            }.alignItems(HorizontalAlign.Start).width('100%')
          } else if (this.tab === 0) {
            Overview({ state: this.overviewState, message: this.overviewMessage, overview: this.overview,
              retry: () => this.refresh(), select: (id: string, trace: string) => this.select(id, trace),
              showIncidents: () => { this.clearSelection(); this.navigate(1); } })
          } else if (this.tab === 1) {
            Incidents({ state: this.listState, message: this.listMessage, items: this.items, hasMore: this.hasMore,
              detail: this.detail, showDetail: this.selectedId.length > 0, detailState: this.detailState, detailMessage: this.detailMessage,
              retry: () => this.refresh(), retryDetail: () => this.readDetail(), loadMore: () => this.readPage(new ApiService(this.config), this.generation, true),
              select: (id: string, trace: string) => this.select(id, trace), back: () => this.clearSelection(), diagnose: () => this.navigate(2) })
          } else if (this.tab === 2) {
            Diagnosis({ detail: this.detail, state: this.detailState, message: this.detailMessage,
              retry: () => this.readDetail(), chooseIncident: () => { this.clearSelection(); this.navigate(1); }, back: () => this.navigate(1) })
          } else {
            LocalMonitor()
          }
        }.width('100%').padding({ left: 24, right: 24, top: 10, bottom: 24 })
      }.layoutWeight(1).width('100%').align(Alignment.Top).scrollBar(BarState.Auto)
      if (!this.settings && this.connected && this.tab !== 3) {
        Button('刷新只读数据').id('refreshData').height(38).fontSize(13).backgroundColor(Theme.background)
          .fontColor(Theme.accent).onClick(() => this.refresh()).margin({ bottom: 4 })
      }
      Row() { this.navigation('概览', 0); this.navigation('故障', 1); this.navigation('AI诊断', 2); this.navigation('本机监控', 3) }
        .width('100%').border({ width: { top: 1 }, color: Theme.line })
    }.width('100%').height('100%').backgroundColor(Theme.background)
  }
}
