import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, forkJoin, interval, of, retry, startWith, Subscription, switchMap, timeout } from 'rxjs';

type ReportState = Record<string, any>;

@Component({
  selector: 'app-reports',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">REPORTS</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Paper Trading Reports
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Read-only report hub · system health · daily review ·
        Updated: {{lastUpdated}}
      </p>
    </div>
    <button mat-stroked-button (click)="refresh()"
            style="color:var(--nx-text-2)">
      <mat-icon>refresh</mat-icon> Refresh
    </button>
  </div>

  <div style="background:rgba(99,102,241,.08);
              border:0.5px solid rgba(99,102,241,.35);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#818cf8;
              margin-bottom:16px;display:flex;
              gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>JSON REPORTS</span>
    <span>NO EXPORT DOWNLOAD TRIGGERED</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Backend route group: /api/reports
    </span>
  </div>

  <div *ngIf="loadError" class="nx-alert">
    Some report endpoints are slow or unavailable. Showing partial data only.
  </div>

  <div *ngIf="loading" class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">LOADING REPORTS</span>
    <div class="nx-loading-line" style="margin-top:10px"></div>
    <div class="nx-loading-line" style="width:70%;margin-top:10px"></div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,
              minmax(170px,1fr));
              gap:10px;margin-bottom:16px">
    <div *ngFor="let card of reportCards"
         class="nx-card">
      <span class="nx-label">{{card.label}}</span>
      <div class="nx-value"
           [style.color]="card.color">
        {{card.value}}
      </div>
      <div class="nx-sub">{{card.sub}}</div>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:1fr 300px;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">REPORT MODULE STATUS</span>
      <div *ngIf="hasReportCharts; else noModuleChart"
           echarts [options]="moduleChart"
           style="height:240px;width:100%">
      </div>
      <ng-template #noModuleChart>
        <div class="nx-empty">
          Report module chart needs at least one reachable report endpoint.
        </div>
      </ng-template>
    </div>
    <div class="nx-card">
      <span class="nx-label">REPORT HEALTH SPLIT</span>
      <div *ngIf="hasReportCharts; else noHealthChart"
           echarts [options]="healthDonut"
           style="height:240px;width:100%">
      </div>
      <ng-template #noHealthChart>
        <div class="nx-empty">
          Report health split appears when report statuses are available.
        </div>
      </ng-template>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:1fr 1fr;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">DAILY REVIEW</span>
      <div style="display:grid;
                  grid-template-columns:repeat(2,1fr);
                  gap:8px;margin-top:8px">
        <div *ngFor="let item of dailyItems"
             style="background:var(--nx-bg-raised);
                    border-radius:8px;padding:10px">
          <div style="font-size:10px;color:var(--nx-text-3);
                      letter-spacing:.06em">
            {{item.label}}
          </div>
          <div style="font-size:16px;font-weight:600;
                      margin-top:4px"
               [style.color]="item.color">
            {{item.value}}
          </div>
        </div>
      </div>
    </div>

    <div class="nx-card">
      <span class="nx-label">STRATEGY / PAPER SUMMARY</span>
      <div style="display:grid;
                  grid-template-columns:repeat(2,1fr);
                  gap:8px;margin-top:8px">
        <div *ngFor="let item of strategyItems"
             style="background:var(--nx-bg-raised);
                    border-radius:8px;padding:10px">
          <div style="font-size:10px;color:var(--nx-text-3);
                      letter-spacing:.06em">
            {{item.label}}
          </div>
          <div style="font-size:16px;font-weight:600;
                      margin-top:4px"
               [style.color]="item.color">
            {{item.value}}
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="nx-card">
    <span class="nx-label">WARNINGS / PARTIAL REPORTS</span>
    <div *ngIf="!warnings.length"
         style="padding:24px;text-align:center;
                color:var(--nx-text-3);font-size:13px">
      No report warnings found.
    </div>
    <div *ngFor="let warning of warnings"
         style="display:flex;gap:8px;align-items:flex-start;
                padding:7px 0;border-bottom:0.5px solid
                var(--nx-border)">
      <mat-icon style="font-size:15px;width:15px;height:15px;
                       color:var(--nx-warning);margin-top:1px">
        warning_amber
      </mat-icon>
      <div style="font-size:12px;color:var(--nx-text-2)">
        {{warning}}
      </div>
    </div>
  </div>

</div>
  `,
})
export class ReportsComponent implements OnInit, OnDestroy {
  reports: ReportState = {};
  lastUpdated = 'never';
  moduleChart: object = {};
  healthDonut: object = {};
  hasReportCharts = false;
  loading = true;
  loadError = false;
  private sub?: Subscription;

  get reportCards(): any[] {
    const status = this.reports['status'];
    const system = this.reports['systemHealth'];
    const daily = this.reports['dailyReview'];
    const strategy = this.reports['strategyEvaluation'];
    const paper = this.reports['livePaperSummary'];
    const quality = this.reports['dataQualitySummary'];
    return [
      {
        label: 'Reports API',
        value: this.statusText(status),
        sub: 'Status endpoint',
        color: this.statusColor(this.statusText(status)),
      },
      {
        label: 'System Health',
        value: this.statusText(system),
        sub: 'Backend and data sources',
        color: this.statusColor(this.statusText(system)),
      },
      {
        label: 'Daily P&L',
        value: this.money(this.find(daily, ['total_pnl', 'daily_pnl'])),
        sub: 'Current review',
        color: this.numberColor(this.find(daily, ['total_pnl', 'daily_pnl'])),
      },
      {
        label: 'Paper Trades',
        value: this.find(paper, ['total_trades', 'closed_trades']) ?? '-',
        sub: 'Report sample',
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Strategy Health',
        value: this.find(strategy, ['status', 'report_status', 'label']) ?? '-',
        sub: 'Paper evaluation',
        color: this.statusColor(String(this.find(strategy, ['status', 'report_status', 'label']) ?? '')),
      },
      {
        label: 'Data Quality',
        value: this.statusText(quality),
        sub: 'Report data quality',
        color: this.statusColor(this.statusText(quality)),
      },
    ];
  }

  get dailyItems(): any[] {
    const daily = this.reports['dailyReview'];
    return [
      this.item('Report Status', this.statusText(daily)),
      this.item('Trade Count', this.find(daily, ['trade_count', 'count']) ?? '0'),
      this.item('Daily P&L', this.money(this.find(daily, ['daily_pnl', 'total_pnl'])),
        this.numberColor(this.find(daily, ['daily_pnl', 'total_pnl']))),
      this.item('Recommendation', this.firstString(this.find(daily, ['recommendations']), 'CONTINUE_PAPER_TESTING')),
    ];
  }

  get strategyItems(): any[] {
    const strategy = this.reports['strategyEvaluation'];
    const paper = this.reports['livePaperSummary'];
    return [
      this.item('Win Rate', this.percent(this.find(strategy, ['win_rate']) ?? this.find(paper, ['win_rate']))),
      this.item('Profit Factor', this.fixed(this.find(strategy, ['profit_factor']) ?? this.find(paper, ['profit_factor']))),
      this.item('Expectancy', this.money(this.find(strategy, ['expectancy']) ?? this.find(paper, ['expectancy']))),
      this.item('Audit Events', this.find(this.reports['auditSummary'], ['total_events', 'count']) ?? '0'),
    ];
  }

  get warnings(): string[] {
    const names = Object.keys(this.reports);
    const warnings = names.flatMap(name =>
      this.asArray(this.find(this.reports[name], ['warnings']))
        .map(w => `${this.title(name)}: ${w}`));
    const missing = names
      .filter(name => !this.reports[name])
      .map(name => `${this.title(name)} unavailable`);
    return [...new Set([...warnings, ...missing])].slice(0, 20);
  }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(60000).pipe(
      startWith(0),
      switchMap(() => this.loadReports())
    ).subscribe(state => {
      this.loading = false;
      this.loadError = Object.values(state).some(value => value === null);
      this.reports = state;
      this.lastUpdated = new Date().toLocaleTimeString(
        'en-IN', { timeZone: 'Asia/Kolkata' });
      this.buildCharts();
    });
  }

  ngOnDestroy() { this.sub?.unsubscribe(); }

  refresh() {
    this.loading = true;
    this.loadReports().subscribe(state => {
      this.loading = false;
      this.loadError = Object.values(state).some(value => value === null);
      this.reports = state;
      this.lastUpdated = new Date().toLocaleTimeString(
        'en-IN', { timeZone: 'Asia/Kolkata' });
      this.buildCharts();
    });
  }

  loadReports() {
    return forkJoin({
      status: this.get('/api/reports/status'),
      systemHealth: this.get('/api/reports/system-health'),
      dailyReview: this.get('/api/reports/daily-review'),
      strategyEvaluation: this.get('/api/reports/strategy-evaluation'),
      livePaperSummary: this.get('/api/reports/live-paper-summary'),
      marketFlowSummary: this.get('/api/reports/market-flow-summary?symbol=NIFTY'),
      participantFlowSummary: this.get('/api/reports/participant-flow-summary?symbol=NIFTY'),
      sectorBreadthSummary: this.get('/api/reports/sector-breadth-summary?index=NIFTY'),
      dataQualitySummary: this.get('/api/reports/data-quality-summary'),
      auditSummary: this.get('/api/reports/audit-summary'),
    });
  }

  get(path: string) {
    return this.http.get<any>(path).pipe(
      timeout(8000),
      retry({ count: 2, delay: 750 }),
      catchError(() => of(null))
    );
  }

  buildCharts() {
    const modules = [
      ['System', this.statusText(this.reports['systemHealth'])],
      ['Daily', this.statusText(this.reports['dailyReview'])],
      ['Strategy', this.statusText(this.reports['strategyEvaluation'])],
      ['Paper', this.statusText(this.reports['livePaperSummary'])],
      ['Flow', this.statusText(this.reports['marketFlowSummary'])],
      ['Quality', this.statusText(this.reports['dataQualitySummary'])],
      ['Audit', this.statusText(this.reports['auditSummary'])],
    ];
    const scores = modules.map(([, status]) => this.statusScore(status));
    this.hasReportCharts = modules.some(([, status]) =>
      status !== 'NO_DATA'
    );
    this.moduleChart = {
      backgroundColor: 'transparent',
      grid: { left: 72, right: 16, top: 8, bottom: 20 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(15,23,42,.92)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9', fontSize: 11 },
      },
      xAxis: {
        type: 'value',
        max: 100,
        axisLabel: { color: '#64748b', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } },
      },
      yAxis: {
        type: 'category',
        data: modules.map(([name]) => name),
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: scores.map(score => ({
          value: score,
          itemStyle: {
            color: score >= 80 ? '#10b981'
              : score >= 45 ? '#f59e0b' : '#ef4444',
            borderRadius: [0, 4, 4, 0],
          },
        })),
        barMaxWidth: 18,
      }],
    };

    const ok = scores.filter(score => score >= 80).length;
    const partial = scores.filter(score => score >= 45 && score < 80).length;
    const fail = scores.filter(score => score < 45).length;
    this.healthDonut = {
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
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        label: { show: false },
        data: [
          { name: 'OK', value: ok, itemStyle: { color: '#10b981' } },
          { name: 'Partial', value: partial, itemStyle: { color: '#f59e0b' } },
          { name: 'Missing', value: fail, itemStyle: { color: '#ef4444' } },
        ],
      }],
    };
  }

  statusText(payload: any): string {
    return String(this.find(payload, ['status', 'report_status', 'overall_status']) ??
      (payload?.ok === true ? 'OK' : payload ? 'AVAILABLE' : 'NO_DATA'));
  }

  statusScore(status: string): number {
    const text = status.toUpperCase();
    if (text.includes('OK') || text.includes('AVAILABLE')) return 100;
    if (text.includes('PARTIAL') || text.includes('INSUFFICIENT') || text.includes('WARNING')) return 60;
    if (text.includes('NO') || text.includes('ERROR') || text.includes('HTTP')) return 20;
    return 50;
  }

  find(value: unknown, keys: string[]): any {
    const seen = new Set<unknown>();
    const walk = (current: unknown): any => {
      if (!current || typeof current !== 'object' || seen.has(current)) return undefined;
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
        if (record[key] !== undefined && record[key] !== null) return record[key];
      }
      for (const item of Object.values(record)) {
        const found = walk(item);
        if (found !== undefined) return found;
      }
      return undefined;
    };
    return walk(value);
  }

  asArray(value: unknown): any[] {
    return Array.isArray(value) ? value : [];
  }

  item(label: string, value: unknown, color = 'var(--nx-text-1)') {
    return { label, value: value ?? '-', color };
  }

  firstString(value: unknown, fallback: string): string {
    if (Array.isArray(value) && value.length) return String(value[0]);
    return value ? String(value) : fallback;
  }

  money(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : '-';
  }

  percent(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) ? `${n.toFixed(1)}%` : '-';
  }

  fixed(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : '-';
  }

  numberColor(value: unknown): string {
    const n = Number(value);
    if (!Number.isFinite(n) || n === 0) return 'var(--nx-text-1)';
    return n > 0 ? 'var(--nx-success)' : 'var(--nx-danger)';
  }

  statusColor(status: string): string {
    const score = this.statusScore(status);
    return score >= 80 ? 'var(--nx-success)'
      : score >= 45 ? 'var(--nx-warning)' : 'var(--nx-danger)';
  }

  title(value: string): string {
    return value.replace(/([A-Z])/g, ' $1')
      .replace(/^./, c => c.toUpperCase())
      .trim();
  }
}
