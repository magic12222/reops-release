import { ApiError } from '../services/ApiError';

// Memory only. Never AppStorage, preferences, files, logs, launch parameters or clipboard.
export class SessionCredential {
  private value: string = '';
  set(value: string): void {
    const token = value.trim();
    if (token.length < 32 || !/^[A-Za-z0-9._~+\/-]+=*$/.test(token)) throw new ApiError('auth_unconfigured');
    this.value = token;
  }
  configured(): boolean { return this.value.length >= 32; }
  authorization(): string {
    if (!this.configured()) throw new ApiError('auth_unconfigured');
    return 'Bearer ' + this.value;
  }
  clear(): void { this.value = ''; }
  toJSON(): string { return '[redacted session credential]'; }
}
