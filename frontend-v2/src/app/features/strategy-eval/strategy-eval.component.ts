import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, forkJoin, of } from 'rxjs';

@Component({
  selector: 'app-strategy-eval',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatChipsModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">STRATEGY EVALUATION</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Paper Strategy Performance
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Closed paper trades only · no broker execution ·
        Updated: {{lastUpdated}}
      </p>
    </div>
    <button mat-stroked-button (click)="load()"
            style="color:var(--nx-text-2)">
      <mat-icon>refresh</mat-icon> Refresh
    </button>
  </div>

  <div *ngIf="(eval?.total_trades || 0) < 20"
       style="background:rgba(245,158,11,.08);
              border:0.5px solid rgba(245,158,11,.4);
              border-radius:8px;padding:12px 16px;
              font-size:12px;color:var(--nx-warning);
              margin-bottom:16px">
    <mat-icon style="font-size:14px;width:14px;height:14px;
                     vertical-align:middle;margin-right:6px">
      warning_amber
    </mat-icon>
    Only {{eval?.total_trades || 0}} closed trades recorded.
    Strategy evaluation needs 20+ for statistical reliability.
  </div>

  <div class="nx-card"
       style="margin-bottom:16px;
              display:flex;gap:20px;
              align-items:center;flex-wrap:wrap">
    <div echarts [options]="healthGauge"
         style="height:160px;width:200px;flex-shrink:0">
    </div>
    <div style="flex:1">
      <span class="nx-label">STRATEGY HEALTH</span>
      <div style="font-size:32px;font-weight:700;
                  margin:6px 0"
           [style.color]="healthColor">
        {{eval?.health_status || 'INSUFFICIENT_DATA'}}
      </div>
      <div style="font-size:13px;color:var(--nx-text-3)">
        {{eval?.recommendation || 'Accumulate more paper trades'}}
      </div>
      <div style="display:flex;gap:8px;
                  margin-top:12px;flex-wrap:wrap">
        <span class="nx-chip nx-chip-paper">
          {{eval?.total_trades || 0}} TOTAL TRADES
        </span>
        <span class="nx-chip"
              [ngClass]="(eval?.win_rate || 0) >= 50
                ? 'nx-chip-ok' : 'nx-chip-fail'">
          {{eval?.win_rate != null
            ? (eval.win_rate | number:'1.0-1') : '-'}}%
          WIN RATE
        </span>
        <span class="nx-chip"
              [ngClass]="(eval?.profit_factor || 0) >= 1.4
                ? 'nx-chip-ok' : 'nx-chip-warn'">
          PF {{eval?.profit_factor != null
            ? (eval.profit_factor | number:'1.2-2') : '-'}}
        </span>
      </div>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,
              minmax(160px,1fr));
              gap:10px;margin-bottom:16px">

    <div class="nx-card">
      <span class="nx-label">WIN RATE</span>
      <div class="nx-value"
           [ngClass]="(eval?.win_rate||0) >= 50
             ? 'c-success' : 'c-danger'">
        {{eval?.win_rate != null
          ? (eval.win_rate | number:'1.0-1') : '-'}}%
      </div>
      <div class="nx-progress">
        <div class="nx-progress-fill"
             [style.width]="boundedPct(eval?.win_rate) + '%'"
             [style.background]="
               (eval?.win_rate||0) >= 50
               ? 'var(--nx-success)' : 'var(--nx-danger)'">
        </div>
      </div>
    </div>

    <div class="nx-card">
      <span class="nx-label">PROFIT FACTOR</span>
      <div class="nx-value"
           [ngClass]="(eval?.profit_factor||0) >= 1.4
             ? 'c-success'
             : (eval?.profit_factor||0) >= 1
             ? 'c-warning' : 'c-danger'">
        {{eval?.profit_factor != null
          ? (eval.profit_factor | number:'1.2-2') : '-'}}
      </div>
      <div class="nx-sub">Target >= 1.4</div>
    </div>

    <div class="nx-card">
      <span class="nx-label">EXPECTANCY INR</span>
      <div class="nx-value"
           [ngClass]="(eval?.expectancy||0) >= 0
             ? 'c-success' : 'c-danger'">
        {{eval?.expectancy != null
          ? (eval.expectancy | number:'1.0-0') : '-'}}
      </div>
      <div class="nx-sub">Per trade average</div>
    </div>

    <div class="nx-card">
      <span class="nx-label">MAX DRAWDOWN</span>
      <div class="nx-value"
           [ngClass]="(eval?.max_drawdown||0) <= 10
             ? 'c-success' : 'c-danger'">
        {{eval?.max_drawdown != null
          ? (eval.max_drawdown | number:'1.0-1') : '-'}}%
      </div>
      <div class="nx-sub">Target <= 10%</div>
    </div>

    <div class="nx-card">
      <span class="nx-label">AVG WIN INR</span>
      <div class="nx-value c-success">
        {{eval?.avg_win != null
          ? (eval.avg_win | number:'1.0-0') : '-'}}
      </div>
      <div class="nx-sub">Average winning trade</div>
    </div>

    <div class="nx-card">
      <span class="nx-label">AVG LOSS INR</span>
      <div class="nx-value c-danger">
        {{eval?.avg_loss != null
          ? (eval.avg_loss | number:'1.0-0') : '-'}}
      </div>
      <div class="nx-sub">Average losing trade</div>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:1fr 1fr;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">WIN VS LOSS BY TYPE</span>
      <div *ngIf="hasWinLossChart; else noWinLossChart"
           echarts [options]="winLossChart"
           style="height:220px;width:100%">
      </div>
      <ng-template #noWinLossChart>
        <div class="nx-empty">
          No win/loss chart yet. It appears after signal-type rows exist.
        </div>
      </ng-template>
    </div>

    <div class="nx-card">
      <span class="nx-label">REJECTION BREAKDOWN</span>
      <div *ngIf="hasRejectionChart; else noRejectionChart"
           echarts [options]="rejectionChart"
           style="height:220px;width:100%">
      </div>
      <ng-template #noRejectionChart>
        <div class="nx-empty">
          No rejection breakdown yet. The chart appears after rejection rows exist.
        </div>
      </ng-template>
    </div>
  </div>

  <div class="nx-card">
    <span class="nx-label">SIGNAL TYPE PERFORMANCE</span>
    <div *ngIf="!signalRows.length"
         style="padding:24px;text-align:center;
                color:var(--nx-text-3);font-size:13px">
      No signal-type performance rows available yet.
    </div>
    <div *ngIf="signalRows.length"
         style="overflow-x:auto;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;
                    font-size:12px">
        <thead>
          <tr style="color:var(--nx-text-3);font-size:10px;
                     letter-spacing:.07em;
                     border-bottom:0.5px solid var(--nx-border)">
            <th style="text-align:left;padding:6px 8px">TYPE</th>
            <th style="text-align:right;padding:6px 8px">TRADES</th>
            <th style="text-align:right;padding:6px 8px">WIN %</th>
            <th style="text-align:right;padding:6px 8px">NET P&L</th>
            <th style="text-align:right;padding:6px 8px">PF</th>
            <th style="text-align:left;padding:6px 8px">STATUS</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of signalRows"
              style="border-bottom:0.5px solid var(--nx-border)">
            <td style="padding:7px 8px;
                       color:var(--nx-text-1);
                       font-weight:600">
              {{row.label}}
            </td>
            <td style="padding:7px 8px;text-align:right">
              {{row.total_trades || 0}}
            </td>
            <td style="padding:7px 8px;text-align:right">
              {{row.win_rate || 0 | number:'1.0-1'}}%
            </td>
            <td style="padding:7px 8px;text-align:right"
                [ngClass]="(row.net_pnl || 0) >= 0
                  ? 'c-success' : 'c-danger'">
              {{row.net_pnl || 0 | number:'1.0-0'}}
            </td>
            <td style="padding:7px 8px;text-align:right">
              {{row.profit_factor || 0 | number:'1.2-2'}}
            </td>
            <td style="padding:7px 8px">
              <span class="nx-chip"
                    [ngClass]="row.status === 'OK'
                      ? 'nx-chip-ok' : 'nx-chip-warn'">
                {{row.status || 'READ_ONLY'}}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

</div>
  `,
})
export class StrategyEvalComponent implements OnInit {
  eval: any = null;
  signalRows: any[] = [];
  rejectionRows: any[] = [];
  healthGauge: object = {};
  winLossChart: object = {};
  rejectionChart: object = {};
  hasWinLossChart = false;
  hasRejectionChart = false;
  lastUpdated = 'never';

  get healthColor(): string {
    const status = String(this.eval?.health_status || '');
    if (status.includes('HEALTHY')) return 'var(--nx-success)';
    if (status.includes('WARNING')) return 'var(--nx-warning)';
    if (status.includes('CRITICAL')) return 'var(--nx-danger)';
    return 'var(--nx-text-3)';
  }

  constructor(private http: HttpClient) {}

  ngOnInit() { this.load(); }

  load() {
    forkJoin({
      summary: this.http.get<any>('/api/strategy-evaluation/summary')
        .pipe(catchError(() => of(null))),
      health: this.http.get<any>('/api/strategy-evaluation/health-score')
        .pipe(catchError(() => of(null))),
      recommendation: this.http.get<any>(
        '/api/strategy-evaluation/recommendation')
        .pipe(catchError(() => of(null))),
      bySignalType: this.http.get<any>(
        '/api/strategy-evaluation/performance/by-signal-type')
        .pipe(catchError(() => of(null))),
      rejections: this.http.get<any>(
        '/api/strategy-evaluation/rejections')
        .pipe(catchError(() => of(null))),
    }).subscribe(data => {
      this.eval = this.normalizeEval(
        data.summary, data.health, data.recommendation);
      this.signalRows = this.normalizeMetricRows(data.bySignalType);
      this.rejectionRows = this.normalizeRejections(data.rejections);
      this.buildHealthGauge(this.eval.health_score || 0);
      this.buildCharts();
      this.lastUpdated = new Date().toLocaleTimeString(
        'en-IN', { timeZone: 'Asia/Kolkata' });
    });
  }

  normalizeEval(summary: any, health: any, recommendation: any): any {
    const paper = this.find(summary, ['live_paper'])
      || this.find(summary, ['paper'])
      || summary
      || {};
    return {
      total_trades: Number(
        this.find(paper, ['total_trades', 'closed_trades'])
        || this.find(health, ['total_trades'])
        || 0),
      win_rate: Number(
        this.find(paper, ['win_rate'])
        || this.find(health, ['win_rate'])
        || 0),
      profit_factor: Number(
        this.find(paper, ['profit_factor'])
        || this.find(health, ['profit_factor'])
        || 0),
      expectancy: Number(
        this.find(paper, ['expectancy'])
        || this.find(health, ['expectancy'])
        || 0),
      max_drawdown: Number(
        this.find(paper, ['max_drawdown'])
        || this.find(health, ['max_drawdown'])
        || 0),
      avg_win: Number(
        this.find(paper, ['average_win', 'avg_win'])
        || 0),
      avg_loss: Number(
        this.find(paper, ['average_loss', 'avg_loss'])
        || 0),
      health_score: Number(
        this.find(health, ['score', 'health_score'])
        || 0),
      health_status: String(
        this.find(health, ['label', 'status'])
        || 'INSUFFICIENT_DATA'),
      recommendation: String(
        this.find(recommendation, ['recommendation'])
        || this.find(health, ['recommendation'])
        || 'Accumulate more paper trades'),
    };
  }

  normalizeMetricRows(payload: any): any[] {
    const items = payload?.items || {};
    if (Array.isArray(items)) return items;
    if (!items || typeof items !== 'object') return [];
    return Object.entries(items).map(([label, raw]: [string, any]) => ({
      label,
      total_trades: Number(raw?.total_trades || 0),
      wins: Number(raw?.wins || 0),
      losses: Number(raw?.losses || 0),
      win_rate: Number(raw?.win_rate || 0),
      net_pnl: Number(raw?.net_pnl ?? raw?.gross_pnl ?? 0),
      profit_factor: Number(raw?.profit_factor || 0),
      status: raw?.status || 'READ_ONLY',
    }));
  }

  normalizeRejections(payload: any): any[] {
    const counts = payload?.counts || payload?.rejection_counts || {};
    if (!counts || typeof counts !== 'object') return [];
    return Object.entries(counts)
      .slice(0, 8)
      .map(([reason, count]) => ({
        reason,
        count: Number(count || 0),
      }));
  }

  boundedPct(value: unknown): number {
    return Math.max(0, Math.min(100, Number(value || 0)));
  }

  buildHealthGauge(score: number) {
    this.healthGauge = {
      backgroundColor: 'transparent',
      series: [{
        type: 'gauge',
        min: 0,
        max: 100,
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.4, '#ef4444'],
              [0.7, '#f59e0b'],
              [1.0, '#10b981'],
            ],
          },
        },
        pointer: {
          itemStyle: { color: 'inherit' },
          length: '55%',
          width: 4,
        },
        axisTick: { show: false },
        splitLine: {
          length: 8,
          lineStyle: { color: 'inherit', width: 2 },
        },
        axisLabel: { show: false },
        detail: {
          valueAnimation: true,
          fontSize: 22,
          fontWeight: 700,
          color: 'inherit',
          offsetCenter: [0, '40%'],
          formatter: '{value}',
        },
        data: [{ value: score, name: '' }],
      }],
    };
  }

  buildCharts() {
    this.hasWinLossChart = this.signalRows.length > 0;
    this.winLossChart = this.signalRows.length
      ? {
          backgroundColor: 'transparent',
          tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            backgroundColor: 'rgba(15,23,42,.92)',
            borderColor: '#1e293b',
            textStyle: { color: '#f1f5f9', fontSize: 11 },
          },
          legend: {
            top: 0,
            right: 0,
            textStyle: { color: '#64748b', fontSize: 10 },
          },
          grid: { left: 48, right: 12, top: 30, bottom: 28 },
          xAxis: {
            type: 'category',
            data: this.signalRows.map(row => row.label),
            axisLabel: { color: '#64748b', fontSize: 10 },
            axisLine: { lineStyle: { color: '#1e293b' } },
            axisTick: { show: false },
          },
          yAxis: {
            type: 'value',
            axisLabel: { color: '#64748b', fontSize: 9 },
            splitLine: {
              lineStyle: { color: '#1e293b', width: 0.5 },
            },
            axisLine: { show: false },
          },
          series: [
            {
              name: 'Wins',
              type: 'bar',
              data: this.signalRows.map(row => row.wins),
              barMaxWidth: 24,
              itemStyle: {
                color: '#10b981',
                borderRadius: [3, 3, 0, 0],
              },
            },
            {
              name: 'Losses',
              type: 'bar',
              data: this.signalRows.map(row => row.losses),
              barMaxWidth: 24,
              itemStyle: {
                color: '#ef4444',
                borderRadius: [3, 3, 0, 0],
              },
            },
          ],
        }
      : {};

    this.hasRejectionChart = this.rejectionRows.length > 0;
    this.rejectionChart = this.rejectionRows.length
      ? {
          backgroundColor: 'transparent',
          tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(15,23,42,.92)',
            borderColor: '#1e293b',
            textStyle: { color: '#f1f5f9', fontSize: 11 },
          },
          legend: {
            bottom: 0,
            textStyle: { color: '#64748b', fontSize: 10 },
          },
          series: [{
            type: 'pie',
            radius: ['36%', '62%'],
            center: ['50%', '44%'],
            label: { show: false },
            data: this.rejectionRows.map((row, index) => ({
              value: row.count,
              name: row.reason,
              itemStyle: {
                color: [
                  '#f59e0b', '#ef4444', '#6366f1',
                  '#06b6d4', '#10b981',
                ][index % 5],
              },
            })),
          }],
        }
      : {};
  }

  find(value: unknown, keys: string[]): any {
    const seen = new Set<unknown>();
    const walk = (current: unknown): any => {
      if (!current || typeof current !== 'object' ||
          seen.has(current)) return undefined;
      seen.add(current);
      if (Array.isArray(current)) {
        for (const item of current) {
          const found = walk(item);
          if (found !== undefined) return found;
        }
        return undefined;
      }
      const record = current as Record<string, unknown>;
      for (const key of keys) {
        if (record[key] !== undefined && record[key] !== null) {
          return record[key];
        }
      }
      for (const item of Object.values(record)) {
        const found = walk(item);
        if (found !== undefined) return found;
      }
      return undefined;
    };
    return walk(value);
  }
}
