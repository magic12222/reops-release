export type ApiErrorCode = 'configuration' | 'auth_unconfigured' | 'unauthorized' | 'forbidden' | 'service' | 'timeout' | 'network' | 'http' | 'json' | 'contract';
export class ApiError extends Error {
  code: ApiErrorCode;
  status: number;
  reason: string;
  constructor(code: ApiErrorCode, status: number = 0, reason: string = '') {
    super(code);
    this.code = code;
    this.status = status;
    this.reason = reason;
  }
}
export function errorMessage(error: Error): string {
  if (error instanceof ApiError) {
    if (error.code === 'configuration') return '请先配置服务地址';
    if (error.code === 'auth_unconfigured') return '请配置有效的专用只读凭据（至少32字符）';
    if (error.code === 'unauthorized') return 'HTTP 401：只读凭据无效或已失效，请重新配置';
    if (error.code === 'forbidden') return 'HTTP 403：当前只读访问被拒绝，请联系服务负责人';
    if (error.code === 'service') return error.reason === 'mobile_access_not_configured' ? 'HTTP 503：服务端未配置移动只读访问' : 'HTTP 503：只读数据服务不可用';
    if (error.code === 'timeout') return '请求超时，请检查网络后重试';
    if (error.code === 'network') return '无法连接服务，请检查地址与网络';
    if (error.code === 'http') return `服务返回 HTTP ${error.status}`;
    if (error.code === 'json') return '服务响应不是有效 JSON';
    return '服务数据与已审查契约不一致';
  }
  return '读取失败，请重试';
}
