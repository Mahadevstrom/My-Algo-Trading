import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, forkJoin, interval, of, startWith, Subscription, switchMap, timeout } from 'rxjs';

@Component({
  selector: 'app-risk-audit',
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
      <p class="nx-label">RISK / AUDIT</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Risk and Audit Monitor
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Read-only risk layer · audit trail · data quality ·
        Updated: {{lastUpdated}}
      </p>
    </div>
    <button mat-stroked-button (click)="refresh()"
            style="color:var(--nx-text-2)">
      <mat-icon>refresh</mat-icon> Refresh
    </button>
  </div>

  <div style="background:rgba(239,68,68,.06);
              border:0.5px solid rgba(239,68,68,.3);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#ef4444;
              margin-bottom:16px;display:flex;
              gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>NO KILL SWITCH MUTATION</span>
    <span>NO RISK LIMIT CHANGES</span>
    <span>LIVE ORDERS BLOCKED</span>
  </div>

  <div *ngIf="loadError" class="nx-alert">
    Some risk, audit, or data-quality endpoints are unavailable.
    The monitor is showing partial data.
  </div>

  <div *ngIf="loading" class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">LOADING RISK CONTEXT</span>
    <div class="nx-loading-line" style="margin-top:10px"></div>
    <div class="nx-loading-line" style="width:72%;margin-top:10px"></div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,
              minmax(170px,1fr));
              gap:10px;margin-bottom:16px">
    <div *ngFor="let card of riskCards"
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
              grid-template-columns:1fr 1fr;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">RISK LIMITS</span>
      <div style="display:grid;
                  grid-template-columns:repeat(2,1fr);
                  gap:8px;margin-top:8px">
        <div *ngFor="let item of limitItems"
             style="background:var(--nx-bg-raised);
                    border-radius:8px;padding:10px">
          <div style="font-size:10px;color:var(--nx-text-3);
                      letter-spacing:.06em">
            {{item.label}}
          </div>
          <div style="font-size:16px;font-weight:600;
                      margin-top:4px;color:var(--nx-text-1)">
            {{item.value}}
          </div>
        </div>
      </div>
    </div>

    <div class="nx-card">
      <span class="nx-label">AUDIT SEVERITY</span>
      <div *ngIf="hasAuditChart; else noAuditChart"
           echarts [options]="auditChart"
           style="height:220px;width:100%">
      </div>
      <ng-template #noAuditChart>
        <div class="nx-empty">
          No audit severity counts yet. Recent audit events will populate this.
        </div>
      </ng-template>
    </div>
  </div>

  <div class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">RECENT AUDIT EVENTS</span>
    <div *ngIf="!auditRows.length"
         style="padding:24px;text-align:center;
                color:var(--nx-text-3);font-size:13px">
      No audit events available.
    </div>
    <div *ngIf="auditRows.length"
         style="overflow-x:auto;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;
                    font-size:12px">
        <thead>
          <tr style="color:var(--nx-text-3);font-size:10px;
                     letter-spacing:.07em;
                     border-bottom:0.5px solid var(--nx-border)">
            <th style="text-align:left;padding:6px 8px">TIME</th>
            <th style="text-align:left;padding:6px 8px">EVENT</th>
            <th style="text-align:left;padding:6px 8px">SOURCE</th>
            <th style="text-align:left;padding:6px 8px">SEVERITY</th>
            <th style="text-align:left;padding:6px 8px">MODE</th>
            <th style="text-align:left;padding:6px 8px">MESSAGE</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of auditRows"
              style="border-bottom:0.5px solid var(--nx-border)">
            <td style="padding:7px 8px;color:var(--nx-text-3)">
              {{formatTime(row.created_at)}}
            </td>
            <td style="padding:7px 8px;color:var(--nx-text-1);
                       font-weight:600">
              {{row.event_type || '-'}}
            </td>
            <td style="padding:7px 8px;color:var(--nx-text-2)">
              {{row.source || '-'}}
            </td>
            <td style="padding:7px 8px">
              <span class="nx-chip"
                    [ngClass]="severityClass(row.severity)">
                {{row.severity || 'INFO'}}
              </span>
            </td>
            <td style="padding:7px 8px;color:var(--nx-text-2)">
              {{row.mode || 'PAPER'}}
            </td>
            <td style="padding:7px 8px;color:var(--nx-text-2)">
              {{row.message || '-'}}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="nx-card">
    <span class="nx-label">RISK / SESSION REJECTIONS</span>
    <div *ngIf="!rejectionRows.length"
         style="padding:24px;text-align:center;
                color:var(--nx-text-3);font-size:13px">
      No rejection rows available.
    </div>
    <div *ngFor="let row of rejectionRows"
         style="display:flex;justify-content:space-between;
                gap:12px;padding:8px 0;
                border-bottom:0.5px solid var(--nx-border);
                font-size:12px">
      <div style="color:var(--nx-text-2)">
        {{row.reason || row.message || '-'}}
      </div>
      <div style="color:var(--nx-warning);white-space:nowrap">
        {{row.gate || row.source || row.module || 'LIVE_PAPER'}}
      </div>
    </div>
  </div>

</div>
  `,
})
export class RiskAuditComponent implements OnInit, OnDestroy {
  risk: any = null;
  limits: any = null;
  auditRows: any[] = [];
  rejectionRows: any[] = [];
  quality: any = null;
  lastUpdated = 'never';
  auditChart: object = {};
  hasAuditChart = false;
  loading = true;
  loadError = false;
  private sub?: Subscription;

  get riskCards(): any[] {
    const kill = this.risk?.kill_switch || {};
    return [
      {
        label: 'Risk Status',
        value: kill.kill_switch_enabled ? 'BLOCKED' : 'SAFE',
        sub: this.risk?.message || 'Risk layer active',
        color: kill.kill_switch_enabled
          ? 'var(--nx-danger)' : 'var(--nx-success)',
      },
      {
        label: 'Kill Switch',
        value: kill.kill_switch_enabled ? 'ENABLED' : 'DISABLED',
        sub: kill.reason || 'No active kill-switch reason',
        color: kill.kill_switch_enabled
          ? 'var(--nx-danger)' : 'var(--nx-success)',
      },
      {
        label: 'Live Orders',
        value: this.risk?.live_order_status || 'BLOCKED',
        sub: 'Execution safety',
        color: String(this.risk?.live_order_status || '').includes('BLOCKED')
          ? 'var(--nx-success)' : 'var(--nx-danger)',
      },
      {
        label: 'Live Feed',
        value: this.risk?.live_feed_connected ? 'CONNECTED' : 'DISCONNECTED',
        sub: this.risk?.live_feed_source || '-',
        color: this.risk?.live_feed_connected
          ? 'var(--nx-success)' : 'var(--nx-warning)',
      },
      {
        label: 'Data Quality',
        value: this.quality?.overall_status || this.quality?.status || 'UNKNOWN',
        sub: 'Risk input quality',
        color: this.statusColor(this.quality?.overall_status || this.quality?.status),
      },
      {
        label: 'Audit Events',
        value: this.auditRows.length,
        sub: 'Latest audit rows',
        color: 'var(--nx-accent)',
      },
    ];
  }

  get limitItems(): any[] {
    const limits = this.limits || {};
    return [
      ['Max Daily Loss', this.money(limits.max_daily_loss)],
      ['Max Trades / Day', limits.max_trades_per_day ?? '-'],
      ['Max Open Positions', limits.max_open_positions ?? limits.max_open_trades ?? '-'],
      ['Cooldown Minutes', limits.cooldown_after_loss_minutes ?? limits.cooldown_minutes ?? '-'],
      ['Max Quantity', limits.max_quantity ?? limits.max_position_size ?? '-'],
      ['Max Exposure', this.money(limits.max_position_exposure)],
      ['Min Confidence', limits.min_confidence ?? '-'],
      ['Max Spread %', limits.max_spread_pct ?? '-'],
    ].map(([label, value]) => ({ label, value }));
  }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(30000).pipe(
      startWith(0),
      switchMap(() => this.load())
    ).subscribe(state => this.applyState(state));
  }

  ngOnDestroy() { this.sub?.unsubscribe(); }

  refresh() {
    this.loading = true;
    this.load().subscribe(state => this.applyState(state));
  }

  load() {
    return forkJoin({
      risk: this.get('/api/risk/status'),
      limits: this.get('/api/risk/limits'),
      audit: this.get('/api/audit/events?limit=100'),
      rejections: this.get('/api/live-paper/rejections'),
      quality: this.get('/api/data-quality/status'),
      auditSummary: this.get('/api/reports/audit-summary'),
    });
  }

  get(path: string) {
    return this.http.get<any>(path).pipe(
      timeout(8000),
      catchError(() => of(null))
    );
  }

  applyState(state: any) {
    this.loading = false;
    this.loadError = Object.values(state).some(value => value === null);
    this.risk = state.risk;
    this.limits = state.limits?.limits || state.risk?.limits || {};
    this.auditRows = state.audit?.items || [];
    this.rejectionRows = state.rejections?.items
      || state.rejections?.rejections
      || [];
    this.quality = state.quality;
    this.lastUpdated = new Date().toLocaleTimeString(
      'en-IN', { timeZone: 'Asia/Kolkata' });
    this.buildAuditChart(state.auditSummary);
  }

  buildAuditChart(summary: any) {
    const counts = this.auditRows.reduce((acc, row) => {
      const key = String(row.severity || 'INFO').toUpperCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    const summaryCounts = this.find(summary, ['severity_counts']);
    const finalCounts = Object.keys(counts).length ? counts : summaryCounts || {};
    const data = Object.entries(finalCounts).map(([name, value], index) => ({
      name,
      value,
      itemStyle: {
        color: ['#10b981', '#f59e0b', '#ef4444', '#6366f1'][index % 4],
      },
    }));
    this.hasAuditChart = data.some((item) => Number(item.value) > 0);
    this.auditChart = {
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
        data,
      }],
    };
  }

  find(value: unknown, keys: string[]): any {
    if (!value || typeof value !== 'object') return undefined;
    const record = value as Record<string, any>;
    for (const key of keys) {
      if (record[key] !== undefined && record[key] !== null) return record[key];
    }
    for (const item of Object.values(record)) {
      const found = this.find(item, keys);
      if (found !== undefined) return found;
    }
    return undefined;
  }

  severityClass(severity: string): string {
    const s = String(severity || '').toUpperCase();
    if (s.includes('ERROR') || s.includes('CRITICAL')) return 'nx-chip-fail';
    if (s.includes('WARN')) return 'nx-chip-warn';
    return 'nx-chip-info';
  }

  statusColor(status: unknown): string {
    const text = String(status || '').toUpperCase();
    if (text.includes('OK')) return 'var(--nx-success)';
    if (text.includes('PARTIAL') || text.includes('WARN')) return 'var(--nx-warning)';
    return 'var(--nx-text-2)';
  }

  formatTime(value: unknown): string {
    if (!value) return '-';
    const date = new Date(String(value));
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
  }

  money(value: unknown): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2) : '-';
  }
}
