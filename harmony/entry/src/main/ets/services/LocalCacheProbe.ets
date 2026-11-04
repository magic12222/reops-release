import { fileIo as fs } from '@kit.CoreFileKit';

export interface LocalProbeResult {
  status: string;
  message: string;
  checkedAt: number;
}

const CONTENT_PREFIX: string = 'ReOps local cache probe v1\n';
const CONTENT_SUFFIX: string = '\ncomplete\n';

// The only mutable resource is this application's dedicated synthetic cache file.
export class LocalCacheProbe {
  private readonly path: string;
  constructor(cacheDir: string) {
    if (!cacheDir || !cacheDir.startsWith('/')) throw new Error('cache_directory_unavailable');
    this.path = cacheDir.replace(/\/+$/, '') + '/reops-local-probe-v1.txt';
  }
  check(): LocalProbeResult {
    try {
      if (!fs.accessSync(this.path)) return this.result('missing', '读取失败：专用测试缓存不存在');
      const value = fs.readTextSync(this.path);
      if (!value.startsWith(CONTENT_PREFIX) || !value.endsWith(CONTENT_SUFFIX) ||
          value.length <= CONTENT_PREFIX.length + CONTENT_SUFFIX.length) {
        return this.result('invalid', '读取失败：测试缓存内容校验不通过');
      }
      return this.result('healthy', '已实际读取手机本地测试缓存，内容校验通过');
    } catch {
      return this.result('unavailable', '本地文件读取失败，尚未确认恢复');
    }
  }
  injectMissing(): LocalProbeResult {
    try {
      fs.unlinkSync(this.path);
      return this.check();
    } catch {
      const actual = this.check();
      return actual.status === 'healthy' ? this.result('healthy', '测试故障未能注入；缓存读取仍正常') : actual;
    }
  }
  rebuild(): LocalProbeResult {
    const content = CONTENT_PREFIX + Date.now().toString() + '-' + Math.random().toString() + CONTENT_SUFFIX;
    try {
      const file = fs.openSync(this.path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try {
        const written = fs.writeSync(file.fd, content);
        if (written !== content.length) return this.result('unavailable', '缓存写入不完整，未确认恢复');
        fs.fsyncSync(file.fd);
      } finally { fs.closeSync(file); }
      if (fs.readTextSync(this.path) !== content) {
        return this.result('invalid', '重建后读取内容不一致，验证未通过');
      }
      return this.result('healthy', '重建写入成功；重新读取逐字比对通过');
    } catch {
      return this.result('unavailable', '重建或读回失败，验证未通过');
    }
  }
  private result(status: string, message: string): LocalProbeResult {
    return { status: status, message: message, checkedAt: Date.now() };
  }
}
