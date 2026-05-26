import { Routes } from '@angular/router';

const lazyReloadKey = 'algovyuh_lazy_chunk_reload_once';

function isChunkLoadError(error: unknown): boolean {
  const message = String((error as Error)?.message ?? error ?? '')
    .toLowerCase();
  return message.includes('failed to fetch dynamically imported module')
    || message.includes('loading chunk')
    || message.includes('chunkloaderror')
    || message.includes('err_network_changed');
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function lazyComponent<T>(loader: () => Promise<T>): () => Promise<T> {
  return async () => {
    try {
      const result = await loader();
      sessionStorage.removeItem(lazyReloadKey);
      return result;
    } catch (firstError) {
      if (!isChunkLoadError(firstError)) throw firstError;

      await delay(600);
      try {
        const result = await loader();
        sessionStorage.removeItem(lazyReloadKey);
        return result;
      } catch (secondError) {
        if (!isChunkLoadError(secondError)) throw secondError;

        if (sessionStorage.getItem(lazyReloadKey) !== '1') {
          sessionStorage.setItem(lazyReloadKey, '1');
          window.location.reload();
          return new Promise<T>(() => undefined);
        }

        sessionStorage.removeItem(lazyReloadKey);
        throw secondError;
      }
    }
  };
}

export const routes: Routes = [
  { path: '',
    loadComponent: lazyComponent(() => import('./layout/shell/shell.component')
      .then(m => m.ShellComponent)),
    children: [
      { path: 'dashboard',
        loadComponent: lazyComponent(() =>
          import('./features/dashboard/dashboard.component')
          .then(m => m.DashboardComponent)) },
      {
        path: 'ai-analyst',
        loadComponent: lazyComponent(() => import('./features/ai-analyst/ai-analyst.component').then(m => m.AiAnalystComponent)),
        title: 'AI Analyst | MyAlgoTrading'
      },
      { path: 'signals',
        loadComponent: lazyComponent(() =>
          import('./features/signals/signals.component')
          .then(m => m.SignalsComponent)) },
      { path: 'live-paper',
        loadComponent: lazyComponent(() =>
          import('./features/live-paper/live-paper.component')
          .then(m => m.LivePaperComponent)) },
      { path: 'option-chain',
        loadComponent: lazyComponent(() =>
          import('./features/option-chain/option-chain.component')
          .then(m => m.OptionChainComponent)) },
      { path: 'market-flow',
        loadComponent: lazyComponent(() =>
          import('./features/market-flow/market-flow.component')
          .then(m => m.MarketFlowComponent)) },
      { path: 'market-chart',
        loadComponent: lazyComponent(() =>
          import('./features/market-chart/market-chart.component')
          .then(m => m.MarketChartComponent)) },
      { path: 'strategy-eval',
        loadComponent: lazyComponent(() =>
          import('./features/strategy-eval/strategy-eval.component')
          .then(m => m.StrategyEvalComponent)) },
      { path: 'replay',
        loadComponent: lazyComponent(() =>
          import('./features/replay/replay.component')
          .then(m => m.ReplayComponent)) },
      { path: 'reports',
        loadComponent: lazyComponent(() =>
          import('./features/reports/reports.component')
          .then(m => m.ReportsComponent)) },
      { path: 'risk-audit',
        loadComponent: lazyComponent(() =>
          import('./features/risk-audit/risk-audit.component')
          .then(m => m.RiskAuditComponent)) },
      { path: 'session-gate',
        loadComponent: lazyComponent(() =>
          import('./features/session-gate/session-gate.component')
          .then(m => m.SessionGateComponent)) },
      { path: 'strategy-builder',
        loadComponent: lazyComponent(() =>
          import('./features/strategy-builder/strategy-builder.component')
          .then(m => m.StrategyBuilderComponent)) },
      { path: 'research-lab',
        loadComponent: lazyComponent(() =>
          import('./features/research-lab/research-lab.component')
          .then(m => m.ResearchLabComponent)) },
      { path: 'agent-evolution',
        loadComponent: lazyComponent(() =>
          import('./features/agent-evolution/agent-evolution.component')
          .then(m => m.AgentEvolutionComponent)) },
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
    ]
  },
  { path: '**', redirectTo: 'dashboard' },
];
