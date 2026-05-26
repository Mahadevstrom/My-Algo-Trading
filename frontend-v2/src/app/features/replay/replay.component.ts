import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { catchError, of } from 'rxjs';

@Component({
  selector: 'app-replay',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatSelectModule,
    MatFormFieldModule,
    MatProgressBarModule,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="margin-bottom:20px">
    <p class="nx-label">BACKTEST REPLAY</p>
    <h1 style="font-size:22px;font-weight:500;
               color:var(--nx-text-1);margin:0">
      Trade Replay Viewer
    </h1>
    <p style="font-size:12px;color:var(--nx-text-3);
              margin:4px 0 0">
      Step through backtest trades one by one ·
      paper only · no execution
    </p>
  </div>

  <div style="background:rgba(239,68,68,.06);
              border:0.5px solid rgba(239,68,68,.3);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#ef4444;
              margin-bottom:16px;display:flex;
              gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>PAPER BACKTEST ONLY</span>
    <span>NO LIVE EXECUTION</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Runs replay APIs only
    </span>
  </div>

  <div class="nx-card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
      <div>
        <span class="nx-label">LIVE DAY ENGINE REPLAY</span>
        <div style="font-size:12px;color:var(--nx-text-3);margin-top:4px">
          Replays stored candles and paper trades for one trading day.
        </div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <input type="date" [(ngModel)]="liveDate"
               style="height:36px;background:var(--nx-bg-raised);border:1px solid var(--nx-border);
                      border-radius:8px;color:var(--nx-text-1);padding:0 10px">
        <button mat-stroked-button (click)="loadLiveReplay()"
                [disabled]="liveReplayLoading"
                style="color:var(--nx-text-2)">
          <mat-icon>refresh</mat-icon> Replay
        </button>
      </div>
    </div>
    <mat-progress-bar *ngIf="liveReplayLoading"
                      mode="indeterminate"
                      color="accent"
                      style="margin-top:12px">
    </mat-progress-bar>
    <div *ngIf="liveReplayError"
         style="margin-top:12px;color:var(--nx-danger);font-size:12px">
      {{liveReplayError}}
    </div>

    <ng-container *ngIf="liveReplay && !liveReplayLoading">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
                  gap:10px;margin-top:14px">
        <div *ngFor="let stat of liveReplayStats"
             style="background:var(--nx-bg-raised);border-radius:8px;padding:10px">
          <div style="font-size:10px;color:var(--nx-text-3);text-transform:uppercase">
            {{stat.label}}
          </div>
          <div style="font-size:20px;font-weight:700;margin-top:4px"
               [style.color]="stat.color">
            {{stat.value}}
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);
                  gap:12px;margin-top:14px">
        <div style="background:var(--nx-bg-raised);border-radius:8px;padding:12px">
          <span class="nx-label">TOP BLOCKERS</span>
          <div *ngFor="let row of liveBlockers"
               style="display:flex;justify-content:space-between;gap:10px;
                      padding:8px 0;border-bottom:1px solid var(--nx-border);
                      font-size:12px">
            <span style="color:var(--nx-text-2)">{{row.name}}</span>
            <strong style="color:var(--nx-warning)">{{row.count}}</strong>
          </div>
        </div>

        <div style="background:var(--nx-bg-raised);border-radius:8px;padding:12px">
          <span class="nx-label">NEAR MISSES</span>
          <div *ngFor="let event of liveNearMisses"
               style="display:grid;grid-template-columns:82px 80px 80px minmax(0,1fr);gap:8px;
                      padding:8px 0;border-bottom:1px solid var(--nx-border);
                      font-size:12px;align-items:center">
            <strong style="color:var(--nx-text-1)">{{event.timeLabel}}</strong>
            <span [style.color]="event.direction === 'BULLISH' ? 'var(--nx-success)' : 'var(--nx-danger)'">
              {{event.direction}}
            </span>
            <strong style="color:var(--nx-warning)">{{event.score}} / {{event.required_score}}</strong>
            <span style="color:var(--nx-text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              {{event.failedLabel}}
            </span>
          </div>
        </div>
      </div>
    </ng-container>
  </div>

  <div class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">SELECT BACKTEST RUN</span>
    <div style="display:flex;gap:10px;
                align-items:flex-start;margin-top:8px">
      <mat-form-field appearance="outline"
                      style="flex:1;color:var(--nx-text-1)">
        <mat-select [(ngModel)]="selectedRunId"
                    (selectionChange)="loadRun()"
                    placeholder="Choose a backtest run">
          <mat-option *ngFor="let run of runs"
                      [value]="run.id">
            #{{run.id}} · {{run.strategy_name || run.name || '?'}}
            · {{run.underlying || 'NIFTY'}}
            · {{run.from_date}} to {{run.to_date}}
          </mat-option>
        </mat-select>
      </mat-form-field>
      <button mat-stroked-button (click)="loadRuns()"
              style="color:var(--nx-text-2);
                     margin-top:4px">
        <mat-icon>refresh</mat-icon>
      </button>
    </div>
    <mat-progress-bar *ngIf="loading"
                      mode="indeterminate"
                      color="accent">
    </mat-progress-bar>
  </div>

  <div *ngIf="trades.length" class="nx-card"
       style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;
                font-size:11px;color:var(--nx-text-3);
                margin-bottom:6px">
      <span>
        Trade {{currentIndex + 1}} of {{trades.length}}
      </span>
      <span>{{progressPct()}}% reviewed</span>
    </div>
    <mat-progress-bar mode="determinate"
                      [value]="progressPct()"
                      color="accent"
                      style="margin-bottom:14px">
    </mat-progress-bar>

    <div style="display:flex;gap:8px;
                align-items:center;flex-wrap:wrap">
      <button mat-stroked-button (click)="goFirst()"
              [disabled]="currentIndex === 0"
              style="color:var(--nx-text-2)">
        <mat-icon>first_page</mat-icon>
      </button>
      <button mat-stroked-button (click)="goPrev()"
              [disabled]="currentIndex === 0"
              style="color:var(--nx-text-2)">
        <mat-icon>chevron_left</mat-icon> Prev
      </button>
      <button mat-flat-button (click)="goNext()"
              [disabled]="currentIndex >= trades.length - 1"
              style="background:var(--nx-accent);
                     color:#fff">
        Next <mat-icon>chevron_right</mat-icon>
      </button>
      <button mat-stroked-button (click)="goLast()"
              [disabled]="currentIndex >= trades.length - 1"
              style="color:var(--nx-text-2)">
        <mat-icon>last_page</mat-icon>
      </button>
    </div>
  </div>

  <ng-container *ngIf="currentTrade as trade">
    <div style="display:grid;
                grid-template-columns:1fr 1fr;
                gap:12px;margin-bottom:16px">

      <div class="nx-card"
           style="border-left:3px solid"
           [style.border-left-color]="tradeResultColor(trade)">
        <span class="nx-label">TRADE DETAILS</span>
        <div *ngFor="let row of tradeDetails(trade)"
             style="display:flex;
                    justify-content:space-between;
                    padding:6px 0;
                    border-bottom:0.5px solid
                    var(--nx-border);font-size:12px">
          <span style="color:var(--nx-text-3)">
            {{row.label}}
          </span>
          <span style="color:var(--nx-text-1);
                       font-weight:500">
            {{row.value}}
          </span>
        </div>
      </div>

      <div style="display:flex;
                  flex-direction:column;gap:10px">

        <div class="nx-card" style="text-align:center">
          <span class="nx-label">NET P&L</span>
          <div style="font-size:36px;font-weight:700;
                      margin-top:6px"
               [style.color]="tradeResultColor(trade)">
            {{tradePnl(trade) >= 0 ? '+' : ''}}
            INR {{tradePnl(trade) | number:'1.0-2'}}
          </div>
          <span class="nx-chip"
                [ngClass]="tradePnl(trade) >= 0
                  ? 'nx-chip-ok' : 'nx-chip-fail'">
            {{trade.result || trade.status || 'REVIEW'}}
          </span>
        </div>

        <div class="nx-card">
          <span class="nx-label">EXIT REASON</span>
          <div style="font-size:14px;font-weight:600;
                      margin-top:6px"
               [style.color]="exitColor(trade.exit_reason)">
            {{trade.exit_reason || trade.rejection_reason || 'OPEN'}}
          </div>
        </div>

        <div class="nx-card">
          <span class="nx-label">TIMING</span>
          <div style="font-size:11px;
                      color:var(--nx-text-3)">Entry</div>
          <div style="font-size:12px;color:var(--nx-text-1);
                      margin-bottom:6px">
            {{trade.entry_time || trade.signal_time || '-'}}
          </div>
          <div style="font-size:11px;
                      color:var(--nx-text-3)">Exit</div>
          <div style="font-size:12px;
                      color:var(--nx-text-1)">
            {{trade.exit_time || '-'}}
          </div>
        </div>
      </div>
    </div>
  </ng-container>

  <div *ngIf="trades.length && currentIndex >= 0"
       class="nx-card">
    <span class="nx-label">
      RUNNING TOTALS - trades 1 to {{currentIndex + 1}}
    </span>
    <div style="display:grid;
                grid-template-columns:repeat(auto-fit,
                minmax(120px,1fr));
                gap:10px;margin-top:10px">
      <div *ngFor="let stat of runningStats"
           style="background:var(--nx-bg-raised);
                  border-radius:8px;padding:10px;
                  text-align:center">
        <div style="font-size:10px;
                    color:var(--nx-text-3)">
          {{stat.label}}
        </div>
        <div style="font-size:20px;font-weight:600;
                    margin-top:4px"
             [style.color]="stat.color">
          {{stat.value}}
        </div>
      </div>
    </div>
  </div>

  <div *ngIf="!loading && runs.length === 0"
       class="nx-card"
       style="text-align:center;padding:48px">
    <mat-icon style="font-size:40px;width:40px;height:40px;
                     color:var(--nx-text-3)">
      replay
    </mat-icon>
    <div style="font-size:14px;color:var(--nx-text-2);
                margin-top:12px">
      No backtest runs found
    </div>
    <div style="font-size:12px;color:var(--nx-text-3);
                margin-top:4px">
      Run a backtest from Strategy Evaluation first.
    </div>
  </div>

</div>
  `,
})
export class ReplayComponent implements OnInit {
  liveDate = this.todayIst();
  liveReplay: any = null;
  liveReplayLoading = false;
  liveReplayError = '';
  runs: any[] = [];
  trades: any[] = [];
  selectedRunId: number | null = null;
  currentIndex = 0;
  loading = false;

  get currentTrade(): any {
    return this.trades[this.currentIndex] ?? null;
  }

  get liveReplayStats(): any[] {
    const summary = this.liveReplay?.summary || {};
    const decisions = summary.signal_decision_counts || {};
    const comparisons = summary.comparison_counts || {};
    return [
      {
        label: 'Candles',
        value: Object.values(summary.candle_counts || {})
          .reduce((sum: number, value: any) => sum + Number(value || 0), 0),
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Signals',
        value: summary.signal_event_count ?? 0,
        color: 'var(--nx-info)',
      },
      {
        label: 'No Trade',
        value: decisions.NO_TRADE ?? 0,
        color: 'var(--nx-warning)',
      },
      {
        label: 'Paper Trades',
        value: summary.paper_trade_count ?? 0,
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Exit Checks',
        value: summary.expected_exit_count ?? 0,
        color: 'var(--nx-success)',
      },
      {
        label: 'Mismatches',
        value: Object.values(comparisons)
          .reduce((sum: number, value: any) => sum + Number(value || 0), 0),
        color: Object.keys(comparisons).length ? 'var(--nx-danger)' : 'var(--nx-success)',
      },
    ];
  }

  get liveBlockers(): any[] {
    const counts = new Map<string, number>();
    for (const event of this.liveEvents()) {
      const checks = event.failed_checks?.length
        ? event.failed_checks
        : ['NO_FAILED_CHECK'];
      for (const check of checks) {
        counts.set(check, (counts.get(check) || 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }

  get liveNearMisses(): any[] {
    return this.liveEvents()
      .map((event: any) => ({
        ...event,
        timeLabel: this.timeLabel(event.time_ist || event.time),
        failedLabel: (event.failed_checks || []).join(', ') || '-',
      }))
      .sort((a: any, b: any) => Number(b.score || 0) - Number(a.score || 0))
      .slice(0, 8);
  }

  get runningStats(): any[] {
    const slice = this.trades
      .slice(0, this.currentIndex + 1)
      .filter((trade: any) => trade.status !== 'REJECTED');
    const wins = slice.filter((trade: any) =>
      this.tradePnl(trade) > 0).length;
    const losses = slice.filter((trade: any) =>
      this.tradePnl(trade) < 0).length;
    const cumPnl = Math.round(
      slice.reduce((sum: number, trade: any) =>
        sum + this.tradePnl(trade), 0) * 100
    ) / 100;
    const winRate = slice.length
      ? Math.round(wins / slice.length * 100)
      : 0;
    return [
      {
        label: 'Reviewed',
        value: this.currentIndex + 1,
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Wins',
        value: wins,
        color: 'var(--nx-success)',
      },
      {
        label: 'Losses',
        value: losses,
        color: 'var(--nx-danger)',
      },
      {
        label: 'Win Rate',
        value: winRate + '%',
        color: winRate >= 50
          ? 'var(--nx-success)'
          : 'var(--nx-danger)',
      },
      {
        label: 'Cum. P&L INR',
        value: (cumPnl >= 0 ? '+' : '') +
          cumPnl.toLocaleString('en-IN'),
        color: cumPnl >= 0
          ? 'var(--nx-success)'
          : 'var(--nx-danger)',
      },
    ];
  }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.loadLiveReplay();
    this.loadRuns();
  }

  loadLiveReplay() {
    if (!this.liveDate) return;
    this.liveReplayLoading = true;
    this.liveReplayError = '';
    this.http.get<any>(
      `/api/replay/live-day?trading_date=${this.liveDate}&underlying=NIFTY&max_signal_events=250`
    ).pipe(catchError(() => of(null)))
      .subscribe(response => {
        this.liveReplay = response?.ok ? response : null;
        this.liveReplayError = response?.ok
          ? ''
          : 'Live-day replay is unavailable.';
        this.liveReplayLoading = false;
      });
  }

  loadRuns() {
    this.loading = true;
    this.http.get<any>('/api/backtest/runs')
      .pipe(catchError(() => of(null)))
      .subscribe(response => {
        this.runs = response?.items || response?.runs || [];
        this.loading = false;
      });
  }

  loadRun() {
    if (!this.selectedRunId) return;
    this.loading = true;
    this.currentIndex = 0;
    this.http.get<any>(
      `/api/backtest/runs/${this.selectedRunId}/trades`
    ).pipe(catchError(() => of(null)))
      .subscribe(response => {
        this.trades = response?.items || response?.trades || [];
        this.loading = false;
      });
  }

  progressPct(): number {
    if (!this.trades.length) return 0;
    return Math.round(
      (this.currentIndex + 1) / this.trades.length * 100
    );
  }

  goNext() {
    if (this.currentIndex < this.trades.length - 1) {
      this.currentIndex++;
    }
  }

  goPrev() {
    if (this.currentIndex > 0) this.currentIndex--;
  }

  goFirst() { this.currentIndex = 0; }

  goLast() {
    this.currentIndex = Math.max(0, this.trades.length - 1);
  }

  tradePnl(trade: any): number {
    return Number(trade?.net_pnl ?? trade?.pnl ?? 0);
  }

  tradeResultColor(trade: any): string {
    const pnl = this.tradePnl(trade);
    if (pnl > 0) return 'var(--nx-success)';
    if (pnl < 0) return 'var(--nx-danger)';
    return 'var(--nx-text-3)';
  }

  exitColor(reason: string): string {
    if (!reason) return 'var(--nx-text-3)';
    if (reason.includes('TARGET')) return 'var(--nx-success)';
    if (reason.includes('STOP')) return 'var(--nx-danger)';
    return 'var(--nx-text-2)';
  }

  tradeDetails(trade: any): Array<{label: string; value: any}> {
    return [
      {
        label: 'Symbol',
        value: trade.underlying || trade.symbol || '-',
      },
      {
        label: 'Signal type',
        value: trade.signal_type || '-',
      },
      {
        label: 'Strike',
        value: trade.selected_strike || '-',
      },
      {
        label: 'Spot at entry',
        value: this.price(trade.spot_price),
      },
      {
        label: 'Entry price',
        value: this.price(trade.entry_price),
      },
      {
        label: 'Exit price',
        value: this.price(trade.exit_price),
      },
      {
        label: 'Stop loss',
        value: this.price(trade.stop_loss),
      },
      {
        label: 'Target',
        value: this.price(trade.target),
      },
      {
        label: 'Qty',
        value: trade.qty || '-',
      },
    ];
  }

  price(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n.toFixed(2) : '-';
  }

  private liveEvents(): any[] {
    return this.liveReplay?.signal_replay?.events || [];
  }

  private timeLabel(value: string | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '-';
    return date.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'Asia/Kolkata',
    });
  }

  private todayIst(): string {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date());
    const part = (type: string) =>
      parts.find(item => item.type === type)?.value || '01';
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
}
