import { Component, OnDestroy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { HttpClient } from '@angular/common/http';
import { catchError, forkJoin, of, retry, timeout } from 'rxjs';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule, RouterOutlet, RouterLink, RouterLinkActive,
    MatSidenavModule, MatToolbarModule, MatIconModule,
    MatButtonModule, MatTooltipModule, MatSnackBarModule,
  ],
  template: `
<mat-sidenav-container style="height:100vh">

  <mat-sidenav #drawer mode="side" [opened]="true"
    [style.width]="navExpanded ? '220px' : '60px'"
    style="transition:width .2s ease; overflow:hidden">

    <div style="display:flex;flex-direction:column;height:100%">

      <div style="height:56px;display:flex;align-items:center;
                  padding:0 16px;border-bottom:0.5px solid
                  var(--nx-border);gap:10px;overflow:hidden">
        <span style="font-size:18px;color:var(--nx-accent);
                     flex-shrink:0">A</span>
        <span *ngIf="navExpanded"
              style="font-size:13px;font-weight:600;
                     color:var(--nx-accent);
                     letter-spacing:.08em;
                     white-space:nowrap">ALGOVYUH</span>
      </div>

      <nav style="flex:1;padding:8px 0;overflow:hidden">
        <a *ngFor="let item of navItems"
           [routerLink]="item.path"
           routerLinkActive="nx-nav-active"
           class="nx-nav-item"
           [matTooltip]="navExpanded ? '' : item.label"
           matTooltipPosition="right">
          <mat-icon style="font-size:18px;width:18px;height:18px;
                           flex-shrink:0">
            {{item.icon}}
          </mat-icon>
          <span *ngIf="navExpanded"
                style="white-space:nowrap;font-size:13px">
            {{item.label}}
          </span>
        </a>
      </nav>

      <div style="padding:12px 16px;border-top:0.5px solid
                  var(--nx-border)">
        <button mat-icon-button (click)="expanded.set(!expanded())"
                style="color:var(--nx-text-3)">
          <mat-icon>
            {{navExpanded ? 'chevron_left' : 'chevron_right'}}
          </mat-icon>
        </button>
      </div>

    </div>
  </mat-sidenav>

  <mat-sidenav-content>

    <mat-toolbar style="min-height:52px;position:sticky;top:0;
                        z-index:100">
      <div style="display:flex;align-items:center;
                  gap:12px;width:100%;flex-wrap:wrap">

        <div style="display:flex;align-items:baseline;gap:6px">
          <span style="font-size:15px;font-weight:600;
                       color:var(--nx-text-1)">
            {{niftyPrice || '-'}}
          </span>
          <span [style.color]="niftyChange >= 0
            ? 'var(--nx-success)' : 'var(--nx-danger)'"
                style="font-size:12px">
            {{niftyChange >= 0 ? '+' : '-'}}
            {{niftyChangePct}}%
          </span>
          <span style="font-size:11px;color:var(--nx-text-3)">
            NIFTY 50
          </span>
        </div>

        <span class="nx-chip"
              [class]="backendOk
                ? 'nx-chip-ok' : 'nx-chip-fail'">
          BACKEND {{backendOk ? 'OK' : 'DOWN'}}
        </span>

        <!-- DHAN TOKEN COUNTDOWN -->
        <span *ngIf="backendOk && dhanConfigured" class="nx-chip" [ngClass]="dhanTokenAlertClass" [matTooltip]="dhanTokenTooltip">
          <mat-icon style="font-size:12px;width:12px;height:12px;vertical-align:middle;margin-right:2px">key</mat-icon>
          DHAN TOKEN: {{dhanTokenCountdownStr}}
        </span>
        <span *ngIf="!compact()" class="nx-chip nx-chip-paper">
          PAPER MODE
        </span>
        <span *ngIf="!compact()" class="nx-chip nx-chip-fail">
          ORDERS BLOCKED
        </span>
        <span *ngIf="!compact()" class="nx-chip nx-chip-warn">
          BROKER DISABLED
        </span>

        <span style="margin-left:auto;font-size:11px;
                     color:var(--nx-text-3);
                     letter-spacing:.06em">
          {{currentTime}}
        </span>

      </div>
    </mat-toolbar>

    <div [style.padding]="compact() ? '12px' : '20px'"
         style="min-height:calc(100vh - 52px)">
      <router-outlet/>
    </div>

  </mat-sidenav-content>
</mat-sidenav-container>
  `,
  styles: [`
    .nx-nav-item {
      display: flex; align-items: center; gap: 12px;
      padding: 10px 18px; color: var(--nx-text-3);
      text-decoration: none; cursor: pointer;
      transition: all .15s; white-space: nowrap;
      overflow: hidden;
    }
    .nx-nav-item:hover {
      background: var(--nx-accent-dim);
      color: var(--nx-text-2);
    }
    .nx-nav-active {
      background: var(--nx-accent-dim) !important;
      color: var(--nx-accent) !important;
      border-right: 2px solid var(--nx-accent);
    }
  `],
})
export class ShellComponent implements OnDestroy {
  expanded = signal(true);
  compact = signal(false);
  backendOk = false;
  currentTime = '';
  niftyPrice = '';
  niftyChange = 0;
  niftyChangePct = '0.00';
  dhanConfigured = false;
  dhanTokenCountdownStr = '...';
  dhanTokenAlertClass = 'nx-chip-neutral';
  dhanTokenTooltip = 'Dhan access token status';
  private dhanSecondsRemaining = 0;
  private backendWasOk: boolean | null = null;
  private backendFailureCount = 0;
  private tradeWatcherReady = false;
  private seenOpenTradeIds = new Set<string>();
  private seenClosedTradeIds = new Set<string>();
  private activeIssueKeys = new Set<string>();
  private issueFailureCounts = new Map<string, number>();
  private timers: number[] = [];

  navItems = [
    { path: 'dashboard',     label: 'Trading Desk',   icon: 'monitoring'      },
    { path: 'ai-analyst',    label: 'AI Analyst',     icon: 'psychology'      },
    { path: 'signals',       label: 'Signals V2',     icon: 'analytics'       },
    { path: 'option-chain',  label: 'Option Chain',   icon: 'schema'          },
    { path: 'live-paper',    label: 'Live Paper',     icon: 'play_circle'     },
    { path: 'market-flow',   label: 'Market Flow',    icon: 'waterfall_chart' },
    { path: 'market-chart',  label: 'Market Chart',   icon: 'candlestick_chart'},
    { path: 'strategy-eval', label: 'Strategy Eval',  icon: 'assessment'      },
    { path: 'strategy-builder', label: 'Algo Builder', icon: 'construction'    },
    { path: 'research-lab',  label: 'Research Lab',   icon: 'science'         },
    { path: 'agent-evolution', label: 'Agent Evolution', icon: 'model_training' },
    { path: 'replay',        label: 'Replay',         icon: 'replay'          },
    { path: 'reports',       label: 'Reports',        icon: 'summarize'       },
    { path: 'risk-audit',    label: 'Risk / Audit',   icon: 'security'        },
    { path: 'session-gate',  label: 'Session Gate',   icon: 'schedule'        },
  ];

  constructor(private http: HttpClient, private snackBar: MatSnackBar) {
    this.updateCompact();
    window.addEventListener('resize', this.updateCompact);
    this.tick();
    this.timers.push(window.setInterval(() => this.tick(), 1000));
    this.checkHealth();
    this.timers.push(window.setInterval(() => this.checkHealth(), 30000));
    this.fetchNifty();
    this.timers.push(window.setInterval(() => this.fetchNifty(), 10000));
    this.fetchDhanStatus();
    this.timers.push(window.setInterval(() => this.fetchDhanStatus(), 30000));
    this.checkSystemIssues();
    this.timers.push(window.setInterval(() => this.checkSystemIssues(), 20000));
    this.watchTradeEvents();
    this.timers.push(window.setInterval(() => this.watchTradeEvents(), 15000));
  }

  get navExpanded(): boolean {
    return this.expanded() && !this.compact();
  }

  private updateCompact = () => {
    this.compact.set(window.innerWidth < 760);
  };

  ngOnDestroy() {
    window.removeEventListener('resize', this.updateCompact);
    for (const timer of this.timers) {
      window.clearInterval(timer);
    }
    this.timers = [];
  }

  tick() {
    const now = new Date();
    this.currentTime = now.toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'Asia/Kolkata', hour12: false,
    }) + ' IST';
    if (this.dhanConfigured && this.dhanSecondsRemaining > 0) {
      this.dhanSecondsRemaining--;
      this.updateDhanCountdownString();
    }
  }

  fetchDhanStatus() {
    if (!this.shouldRunPolling()) return;
    this.http.get<any>('/api/broker/dhan/status')
      .pipe(
        timeout(6000),
        retry({ count: 1, delay: 750 }),
        catchError(() => of(null))
      )
      .subscribe(r => {
        if (!r) {
          this.dhanConfigured = false;
          return;
        }
        this.dhanConfigured = r.configured;
        if (this.dhanConfigured) {
          this.dhanSecondsRemaining = Math.floor(r.token_seconds_remaining ?? 0);
          this.updateDhanCountdownString();
        } else {
          this.dhanTokenCountdownStr = 'MISSING';
          this.dhanTokenAlertClass = 'nx-chip-fail';
          this.dhanTokenTooltip = 'Dhan credentials are not configured in backend/.env!';
        }
      });
  }

  updateDhanCountdownString() {
    if (this.dhanSecondsRemaining <= 0) {
      this.dhanTokenCountdownStr = 'EXPIRED';
      this.dhanTokenAlertClass = 'nx-chip-fail';
      this.dhanTokenTooltip = 'Dhan access token has expired! Please generate a new 24-hour token and update backend/.env.';
      return;
    }
    const hrs = Math.floor(this.dhanSecondsRemaining / 3600);
    const mins = Math.floor((this.dhanSecondsRemaining % 3600) / 60);
    const secs = Math.floor(this.dhanSecondsRemaining % 60);
    let timeStr = '';
    if (hrs > 0) {
      timeStr += `${hrs}h ${mins}m`;
    } else if (mins > 0) {
      timeStr += `${mins}m ${secs}s`;
    } else {
      timeStr += `${secs}s`;
    }
    this.dhanTokenCountdownStr = timeStr;
    if (hrs >= 4) {
      this.dhanTokenAlertClass = 'nx-chip-ok';
      this.dhanTokenTooltip = `Dhan access token is fresh. Expires in ${hrs}h ${mins}m.`;
    } else if (hrs >= 1) {
      this.dhanTokenAlertClass = 'nx-chip-warn';
      this.dhanTokenTooltip = `Dhan access token is in warning status. Expires in ${hrs}h ${mins}m.`;
    } else {
      this.dhanTokenAlertClass = 'nx-chip-fail';
      this.dhanTokenTooltip = `Dhan access token is about to expire in ${mins}m ${secs}s! Update backend/.env immediately.`;
    }
  }

  checkHealth() {
    this.http.get('/api/health', { observe: 'response' })
      .pipe(
        timeout(5000),
        retry({ count: 1, delay: 750 }),
        catchError(() => of(null))
      )
      .subscribe(r => {
        const ok = r?.status === 200;
        if (ok) {
          this.backendFailureCount = 0;
          this.backendOk = true;
        } else {
          this.backendFailureCount += 1;
          if (this.backendFailureCount >= 2) {
            this.backendOk = false;
          }
        }
        if (this.backendWasOk === null) {
          this.backendWasOk = ok;
          return;
        }
        if (!ok && this.backendWasOk && this.backendFailureCount >= 2) {
          this.popup('Backend is not reachable. Check the FastAPI server on port 8018.', 'problem');
          this.backendWasOk = false;
          return;
        }
        if (ok && !this.backendWasOk) {
          this.popup('Backend connection restored.', 'success');
        }
        if (ok) {
          this.backendWasOk = true;
        }
      });
  }

  fetchNifty() {
    if (!this.shouldRunPolling()) return;
    this.http.get<any>('/api/live-monitor/nifty/overview')
      .pipe(
        timeout(6000),
        retry({ count: 1, delay: 750 }),
        catchError(() => of(null))
      )
      .subscribe(r => {
        if (!r) return;
        const ltp = r?.nifty?.ltp ?? r?.spot ?? r?.ltp ??
          r?.last_price ?? r?.latest_price;
        const prev = r?.nifty?.prev_close ?? r?.prev_close ??
          r?.previous_close;
        if (ltp) {
          this.niftyPrice = Number(ltp).toLocaleString('en-IN',
            { minimumFractionDigits: 2 });
          if (prev) {
            this.niftyChange = ltp - prev;
            this.niftyChangePct =
              Math.abs((ltp - prev) / prev * 100).toFixed(2);
          }
        }
      });
  }

  private checkSystemIssues() {
    if (!this.shouldRunPolling()) return;
    forkJoin({
      risk: this.safeGet('/api/risk/status'),
      quality: this.safeGet('/api/data-quality/status'),
      livePaper: this.safeGet('/api/live-paper/status'),
    }).subscribe(state => {
      if (!state.risk) {
        this.raiseIssue('risk_api_down', 'Risk status is not responding.');
      } else {
        this.clearIssue('risk_api_down');
        const killSwitch = state.risk?.kill_switch?.kill_switch_enabled;
        if (killSwitch) {
          this.raiseIssue('kill_switch_on', `Kill switch is active: ${state.risk?.kill_switch?.reason || 'risk block active'}`);
        } else {
          this.clearIssue('kill_switch_on');
        }
      }

      if (!state.quality) {
        this.raiseIssue('data_quality_down', 'Data quality engine is not responding.');
      } else {
        this.clearIssue('data_quality_down');
        const qualityStatus = String(state.quality?.overall_status || state.quality?.status || '').toUpperCase();
        if (qualityStatus && !['OK', 'HEALTHY', 'GOOD', 'NORMAL'].includes(qualityStatus)) {
          this.raiseIssue('data_quality_bad', `Data quality warning: ${qualityStatus}`);
        } else {
          this.clearIssue('data_quality_bad');
        }
      }

      if (!state.livePaper) {
        this.raiseIssue('live_paper_down', 'Live Paper simulator status is not responding.');
      } else {
        this.clearIssue('live_paper_down');
      }
    });
  }

  private watchTradeEvents() {
    if (!this.shouldRunPolling()) return;
    forkJoin({
      open: this.safeGet('/api/live-paper/open-trades'),
      closed: this.safeGet('/api/live-paper/closed-trades'),
    }).subscribe(state => {
      if (!state.open || !state.closed) {
        this.raiseIssue('trade_watch_down', 'Trade event watcher cannot reach Live Paper trade endpoints.');
        return;
      }
      this.clearIssue('trade_watch_down');

      const openTrades = this.arrayFrom(state.open, ['items', 'trades']);
      const closedTrades = this.arrayFrom(state.closed, ['items', 'trades']);
      const openIds = new Set(openTrades.map(trade => this.tradeId(trade)).filter(Boolean));
      const closedIds = new Set(closedTrades.map(trade => this.tradeId(trade)).filter(Boolean));

      if (!this.tradeWatcherReady) {
        this.seenOpenTradeIds = openIds;
        this.seenClosedTradeIds = closedIds;
        this.tradeWatcherReady = true;
        return;
      }

      for (const trade of openTrades) {
        const id = this.tradeId(trade);
        if (id && !this.seenOpenTradeIds.has(id)) {
          this.popup(`Paper trade opened: ${this.tradeLabel(trade)}`, 'trade');
        }
      }

      for (const trade of closedTrades) {
        const id = this.tradeId(trade);
        if (id && !this.seenClosedTradeIds.has(id)) {
          this.popup(`Paper trade closed: ${this.tradeLabel(trade)} · PnL ${this.tradePnl(trade)}`, 'trade');
        }
      }

      this.seenOpenTradeIds = openIds;
      this.seenClosedTradeIds = closedIds;
    });
  }

  private safeGet(path: string) {
    return this.http.get<any>(path).pipe(
      timeout(6000),
      retry({ count: 1, delay: 750 }),
      catchError(() => of(null))
    );
  }

  private shouldRunPolling(): boolean {
    return typeof document === 'undefined' || !document.hidden;
  }

  private raiseIssue(key: string, message: string) {
    const failures = (this.issueFailureCounts.get(key) ?? 0) + 1;
    this.issueFailureCounts.set(key, failures);
    if (failures < 2) return;
    if (this.activeIssueKeys.has(key)) return;
    this.activeIssueKeys.add(key);
    this.popup(message, 'problem');
  }

  private clearIssue(key: string) {
    this.issueFailureCounts.delete(key);
    this.activeIssueKeys.delete(key);
  }

  private popup(message: string, type: 'problem' | 'trade' | 'success') {
    const panelClass = type === 'problem'
      ? ['nx-snack-problem']
      : type === 'success'
        ? ['nx-snack-success']
        : ['nx-snack-trade'];
    this.snackBar.open(message, 'OK', {
      duration: type === 'problem' ? 7000 : 5000,
      horizontalPosition: 'right',
      verticalPosition: 'top',
      panelClass,
    });
  }

  private arrayFrom(value: any, keys: string[]): any[] {
    if (Array.isArray(value)) return value;
    for (const key of keys) {
      if (Array.isArray(value?.[key])) return value[key];
    }
    return [];
  }

  private tradeId(trade: any): string {
    const id = trade?.id ?? trade?.trade_id ?? trade?.paper_trade_id;
    return id === undefined || id === null ? '' : String(id);
  }

  private tradeLabel(trade: any): string {
    const symbol = trade?.symbol || trade?.underlying || 'TRADE';
    const side = trade?.side || trade?.signal_type || trade?.option_type || trade?.direction || '';
    const price = trade?.entry_price ?? trade?.exit_price ?? trade?.current_price;
    return `${symbol} ${side}`.trim() + (price ? ` @ ${Number(price).toFixed(2)}` : '');
  }

  private tradePnl(trade: any): string {
    const pnl = trade?.pnl ?? trade?.realized_pnl ?? trade?.net_pnl ?? 0;
    return Number(pnl).toLocaleString('en-IN', {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    });
  }
}
