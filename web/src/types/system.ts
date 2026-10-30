export type SystemPhase = 'healthy' | 'failed' | 'detect' | 'locate' | 'reason' | 'decide' | 'execute' | 'verify' | 'recovered' | 'learn';
export type NodeId = 'api' | 'redis' | 'postgres' | 'worker' | 'agent' | 'monitor';
export interface SystemNode { id: NodeId; label: string; detail: string; x: number; y: number; latency: string; conceptual?: boolean }
export interface ServiceView { id: string; name: string; status: 'healthy' | 'failed' | 'checking' | 'recovering'; detail: string }
