export interface StrategyMetrics {
  id: string; name: string; successRate: number; recoveryTime: number; toolCalls: number;
  tokens: number; coverage: number; samples: number; sparkline: number[];
  provenance: 'demo';
}
