import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, forkJoin, of } from 'rxjs';

type LoadState = 'loading' | 'ready' | 'partial';

interface AgentStatus {
  enabled?: boolean;
  auto_apply?: boolean;
  last_run_at?: string | null;
  total_recommendations?: number;
  pending_count?: number;
  approved_count?: number;
  rejected_count?: number;
  config?: {
    lookback_days?: number;
    min_trades?: number;
    max_recs_per_run?: number;
    nightly_run_enabled?: boolean;
    nightly_run_time_ist?: string;
  };
}

interface CalibrationBucket {
  key?: string;
  range?: string;
  range_display?: string;
  trade_count?: number;
  win_count?: number;
  loss_count?: number;
  breakeven_count?: number;
  win_rate_pct?: number | null;
  avg_pnl?: number | null;
  bar_color?: string;
}

interface CalibrationResult {
  status?: string;
  calibration_grade?: string;
  recommended_floor?: number;
  current_confidence_floor?: number;
  total_trades_analyzed?: number;
  trades_needed?: number;
  min_required?: number;
  current_count?: number;
  insight?: string;
  buckets?: CalibrationBucket[];
}

interface FilterRow {
  filter_name?: string;
  display_name?: string;
  edge_score?: number;
  presence_in_winning_trades_pct?: number;
  presence_in_losing_trades_pct?: number;
  verdict?: string;
  recommendation?: string;
  reliability?: string;
}

interface FilterScorecard {
  status?: string;
  filters?: FilterRow[];
  minimum_filters_for_entry?: number | null;
  minimum_filters_note?: string;
  total_trades_analyzed?: number;
  trades_needed?: number;
  min_required?: number;
}

interface FailurePattern {
  pattern?: string;
  severity?: string;
  frequency?: number;
  frequency_pct?: number;
  win_rate_pct?: number;
  loss_rate_pct?: number;
  description?: string;
}

interface PatternResult {
  trade_count_analyzed?: number;
  patterns_detected?: number;
  patterns?: FailurePattern[];
}

interface Recommendation {
  id: number;
  created_at?: string;
  recommendation_type?: string;
  affected_module?: string;
  issue_detected?: string;
  suggested_change?: string;
  expected_benefit?: string;
  risk_level?: string;
  confidence?: number;
  status?: string;
  review_note?: string | null;
}

@Component({
  selector: 'app-agent-evolution',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTabsModule,
    MatTooltipModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1500px;margin:0 auto">

  <div class="ae-header">
    <div>
      <p class="nx-label">AGENT EVOLUTION</p>
      <h1 class="ae-title">Learning Loop Dashboard</h1>
      <p class="ae-subtitle">
        Confidence calibration, filter edge, failure patterns, and human-reviewed recommendations.
      </p>
    </div>
    <div class="ae-actions">
      <span class="nx-chip nx-chip-paper">PAPER MODE</span>
      <span class="nx-chip nx-chip-fail">AUTO APPLY OFF</span>
      <button mat-stroked-button (click)="runAnalysis()" [disabled]="runningAnalysis">
        <mat-icon>{{runningAnalysis ? 'sync' : 'psychology'}}</mat-icon>
        Run Analysis
      </button>
      <button mat-stroked-button (click)="refresh()" [disabled]="state === 'loading'">
        <mat-icon>refresh</mat-icon>
        Refresh
      </button>
    </div>
  </div>

  <div *ngIf="state === 'loading'" class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">LOADING AGENT STATE</span>
    <mat-progress-bar mode="indeterminate" color="accent" style="margin-top:12px"></mat-progress-bar>
  </div>

  <div *ngIf="loadError" class="nx-alert">
    Some Agent Evolution endpoints are unavailable. The dashboard is showing the data it could load.
  </div>

  <div class="ae-status-grid">
    <div class="nx-card" *ngFor="let card of statusCards">
      <span class="nx-label">{{card.label}}</span>
      <div class="nx-value" [style.color]="card.color">{{card.value}}</div>
      <div class="nx-sub">{{card.sub}}</div>
    </div>
  </div>

  <div class="ae-main-grid">
    <div class="nx-card">
      <div class="ae-card-head">
        <div>
          <span class="nx-label">CONFIDENCE CALIBRATION</span>
          <div class="ae-card-title">
            {{calibration?.calibration_grade || calibration?.status || 'UNKNOWN'}}
          </div>
        </div>
        <mat-icon matTooltip="Shows whether higher signal confidence has produced better trade outcomes.">
          help_outline
        </mat-icon>
      </div>

      <div *ngIf="calibration?.status === 'INSUFFICIENT_DATA'" class="nx-empty">
        Need {{calibration?.trades_needed || calibration?.min_required || 20}} more closed birth-certificate trades.
      </div>

      <div *ngIf="calibration?.status !== 'INSUFFICIENT_DATA'">
        <div echarts [options]="calibrationChart" style="height:280px;width:100%;margin-top:8px"></div>
        <div class="ae-metric-row">
          <div>
            <span class="nx-label">CURRENT FLOOR</span>
            <strong>{{percent(calibration?.current_confidence_floor)}}</strong>
          </div>
          <div>
            <span class="nx-label">RECOMMENDED FLOOR</span>
            <strong>{{percent(calibration?.recommended_floor)}}</strong>
          </div>
          <div>
            <span class="nx-label">SAMPLE</span>
            <strong>{{calibration?.total_trades_analyzed || 0}}</strong>
          </div>
        </div>
      </div>

      <p *ngIf="calibration?.insight" class="ae-note">{{calibration?.insight}}</p>
    </div>

    <div class="nx-card">
      <div class="ae-card-head">
        <div>
          <span class="nx-label">FAILURE PATTERNS</span>
          <div class="ae-card-title">{{patterns?.patterns_detected || 0}} detected</div>
        </div>
        <mat-icon matTooltip="Patterns are created from closed paper trades with birth certificates.">
          help_outline
        </mat-icon>
      </div>

      <div *ngIf="!patternRows.length" class="nx-empty">
        No failure patterns yet. Keep collecting closed paper trades.
      </div>

      <div class="ae-pattern-list" *ngIf="patternRows.length">
        <div class="ae-pattern" *ngFor="let pattern of patternRows">
          <div class="ae-pattern-top">
            <strong>{{formatLabel(pattern.pattern)}}</strong>
            <span class="nx-chip" [ngClass]="riskClass(pattern.severity)">
              {{pattern.severity || 'INFO'}}
            </span>
          </div>
          <div class="ae-pattern-meta">
            {{patternMetric(pattern)}} · {{patterns?.trade_count_analyzed || 0}} trades scanned
          </div>
          <p>{{pattern.description || '-'}}</p>
        </div>
      </div>
    </div>
  </div>

  <div class="nx-card" style="margin-top:16px">
    <div class="ae-card-head">
      <div>
        <span class="nx-label">FILTER SCORECARD</span>
        <div class="ae-card-title">
          Minimum reliable filters:
          {{scorecard?.minimum_filters_for_entry || 'review'}}
        </div>
      </div>
      <mat-icon matTooltip="Edge score compares filter presence in winning trades versus losing trades.">
        help_outline
      </mat-icon>
    </div>

    <div *ngIf="scorecard?.status === 'INSUFFICIENT_DATA'" class="nx-empty">
      Need {{scorecard?.trades_needed || scorecard?.min_required || 15}} more closed trades with filter data.
    </div>

    <div *ngIf="filterRows.length" class="ae-table-wrap">
      <table class="nx-table">
        <thead>
          <tr>
            <th style="text-align:left">FILTER</th>
            <th style="text-align:right">EDGE</th>
            <th style="text-align:right">WIN PRESENCE</th>
            <th style="text-align:right">LOSS PRESENCE</th>
            <th style="text-align:left">VERDICT</th>
            <th style="text-align:left">NOTE</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of filterRows">
            <td>
              <strong>{{row.display_name || formatLabel(row.filter_name)}}</strong>
              <div class="nx-sub">{{row.filter_name}}</div>
            </td>
            <td style="text-align:right" [style.color]="edgeColor(row.edge_score)">
              {{number(row.edge_score)}}%
            </td>
            <td style="text-align:right">{{number(row.presence_in_winning_trades_pct)}}%</td>
            <td style="text-align:right">{{number(row.presence_in_losing_trades_pct)}}%</td>
            <td>
              <span class="nx-chip" [ngClass]="verdictClass(row.verdict)">
                {{row.verdict || 'UNKNOWN'}}
              </span>
            </td>
            <td class="ae-muted-cell">{{row.recommendation || '-'}}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p *ngIf="scorecard?.minimum_filters_note" class="ae-note">
      {{scorecard?.minimum_filters_note}}
    </p>
  </div>

  <div class="nx-card" style="margin-top:16px">
    <mat-tab-group color="accent" animationDuration="150ms">
      <mat-tab label="Pending Review">
        <div class="ae-tab-body">
          <div *ngIf="!pendingRecommendations.length" class="nx-empty">
            No pending recommendations. New items appear after analysis has enough closed trades.
          </div>
          <div *ngFor="let rec of pendingRecommendations" class="ae-rec">
            <div class="ae-rec-head">
              <div>
                <span class="nx-label">{{rec.recommendation_type}}</span>
                <h3>{{rec.issue_detected}}</h3>
              </div>
              <div class="ae-rec-badges">
                <span class="nx-chip" [ngClass]="riskClass(rec.risk_level)">
                  {{rec.risk_level || 'LOW'}}
                </span>
                <span class="nx-chip nx-chip-info">{{percent(rec.confidence)}}</span>
              </div>
            </div>
            <div class="ae-rec-module">{{rec.affected_module}} · {{formatTime(rec.created_at)}}</div>
            <p>{{rec.suggested_change}}</p>
            <div class="ae-rec-benefit">{{rec.expected_benefit}}</div>
            <div class="ae-rec-actions">
              <button mat-stroked-button (click)="review(rec, 'APPROVED')" [disabled]="reviewingId === rec.id">
                <mat-icon>check_circle</mat-icon>
                Approve
              </button>
              <button mat-stroked-button (click)="review(rec, 'REJECTED')" [disabled]="reviewingId === rec.id">
                <mat-icon>cancel</mat-icon>
                Reject
              </button>
            </div>
          </div>
        </div>
      </mat-tab>

      <mat-tab label="Approved / Rejected History">
        <div class="ae-tab-body">
          <div *ngIf="!historyRecommendations.length" class="nx-empty">
            Reviewed recommendations will appear here.
          </div>
          <div class="ae-table-wrap" *ngIf="historyRecommendations.length">
            <table class="nx-table">
              <thead>
                <tr>
                  <th style="text-align:left">STATUS</th>
                  <th style="text-align:left">TYPE</th>
                  <th style="text-align:left">MODULE</th>
                  <th style="text-align:left">ISSUE</th>
                  <th style="text-align:left">DATE</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let rec of historyRecommendations">
                  <td>
                    <span class="nx-chip" [ngClass]="statusClass(rec.status)">
                      {{rec.status}}
                    </span>
                  </td>
                  <td>{{rec.recommendation_type}}</td>
                  <td>{{rec.affected_module}}</td>
                  <td class="ae-muted-cell">{{rec.issue_detected}}</td>
                  <td>{{formatTime(rec.created_at)}}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </mat-tab>
    </mat-tab-group>
  </div>
</div>
  `,
  styles: [`
    .ae-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .ae-title {
      font-size: 22px;
      font-weight: 500;
      color: var(--nx-text-1);
      margin: 0;
    }
    .ae-subtitle {
      font-size: 12px;
      color: var(--nx-text-3);
      margin: 4px 0 0;
    }
    .ae-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .ae-status-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .ae-main-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(320px, .75fr);
      gap: 16px;
    }
    .ae-card-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 10px;
    }
    .ae-card-title {
      color: var(--nx-text-1);
      font-size: 16px;
      font-weight: 600;
    }
    .ae-metric-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 10px;
    }
    .ae-metric-row > div {
      background: var(--nx-bg-raised);
      border-radius: 8px;
      padding: 10px;
    }
    .ae-note {
      font-size: 12px;
      color: var(--nx-text-2);
      margin: 12px 0 0;
      line-height: 1.5;
    }
    .ae-pattern-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .ae-pattern {
      background: var(--nx-bg-raised);
      border: 0.5px solid var(--nx-border);
      border-radius: 8px;
      padding: 12px;
    }
    .ae-pattern-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
    }
    .ae-pattern-meta {
      color: var(--nx-text-3);
      font-size: 11px;
      margin-top: 4px;
    }
    .ae-pattern p {
      color: var(--nx-text-2);
      font-size: 12px;
      line-height: 1.45;
      margin: 8px 0 0;
    }
    .ae-table-wrap {
      overflow-x: auto;
      margin-top: 8px;
    }
    .ae-muted-cell {
      color: var(--nx-text-2);
      max-width: 420px;
      line-height: 1.4;
    }
    .ae-tab-body {
      padding-top: 14px;
    }
    .ae-rec {
      border: 0.5px solid var(--nx-border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 12px;
      background: var(--nx-bg-raised);
    }
    .ae-rec-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }
    .ae-rec h3 {
      font-size: 15px;
      font-weight: 600;
      color: var(--nx-text-1);
      margin: 0;
    }
    .ae-rec p {
      font-size: 12px;
      color: var(--nx-text-2);
      line-height: 1.5;
      margin: 10px 0;
    }
    .ae-rec-module,
    .ae-rec-benefit {
      font-size: 11px;
      color: var(--nx-text-3);
      margin-top: 5px;
    }
    .ae-rec-badges,
    .ae-rec-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .ae-rec-actions {
      justify-content: flex-end;
      margin-top: 12px;
    }
    @media (max-width: 900px) {
      .ae-main-grid,
      .ae-metric-row {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class AgentEvolutionComponent implements OnInit {
  state: LoadState = 'loading';
  loadError = false;
  runningAnalysis = false;
  reviewingId: number | null = null;

  status: AgentStatus | null = null;
  calibration: CalibrationResult | null = null;
  scorecard: FilterScorecard | null = null;
  patterns: PatternResult | null = null;
  pendingRecommendations: Recommendation[] = [];
  historyRecommendations: Recommendation[] = [];
  calibrationChart: object = {};

  constructor(private http: HttpClient, private snackBar: MatSnackBar) {}

  ngOnInit() {
    this.refresh();
  }

  get filterRows(): FilterRow[] {
    return this.scorecard?.filters || [];
  }

  get patternRows(): FailurePattern[] {
    return this.patterns?.patterns || [];
  }

  get statusCards() {
    return [
      {
        label: 'Engine',
        value: this.status?.enabled ? 'ENABLED' : 'DISABLED',
        sub: 'Agent Evolution',
        color: this.status?.enabled ? 'var(--nx-success)' : 'var(--nx-danger)',
      },
      {
        label: 'Last Run',
        value: this.status?.last_run_at ? this.formatTime(this.status.last_run_at) : 'NEVER',
        sub: 'Latest recommendation timestamp',
        color: 'var(--nx-accent)',
      },
      {
        label: 'Next Run',
        value: this.status?.config?.nightly_run_enabled
          ? `${this.status?.config?.nightly_run_time_ist || '18:30'} IST`
          : 'OFF',
        sub: 'Nightly analysis',
        color: this.status?.config?.nightly_run_enabled ? 'var(--nx-cyan)' : 'var(--nx-warning)',
      },
      {
        label: 'Pending',
        value: this.status?.pending_count ?? 0,
        sub: `${this.status?.total_recommendations ?? 0} total recommendations`,
        color: (this.status?.pending_count || 0) > 0 ? 'var(--nx-warning)' : 'var(--nx-success)',
      },
      {
        label: 'Sample Size',
        value: this.patterns?.trade_count_analyzed ?? this.calibration?.total_trades_analyzed ?? 0,
        sub: `Minimum ${this.status?.config?.min_trades || 20}`,
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Auto Apply',
        value: this.status?.auto_apply ? 'ON' : 'OFF',
        sub: 'Human review required',
        color: this.status?.auto_apply ? 'var(--nx-danger)' : 'var(--nx-success)',
      },
    ];
  }

  refresh() {
    this.state = 'loading';
    forkJoin({
      status: this.safeGet<AgentStatus>('/api/agent-evolution/status'),
      scorecard: this.safeGet<any>('/api/agent-evolution/scorecard'),
      patterns: this.safeGet<PatternResult>('/api/agent-evolution/failure-patterns'),
      pending: this.safeGet<Recommendation[]>('/api/agent-evolution/recommendations?status=PENDING&limit=50'),
      history: this.safeGet<Recommendation[]>('/api/agent-evolution/recommendations?status=ALL&limit=100'),
    }).subscribe((state) => {
      this.status = state.status;
      this.calibration = state.scorecard?.confidence_calibration || null;
      this.scorecard = state.scorecard?.filter_scorecard || null;
      this.patterns = state.patterns;
      this.pendingRecommendations = Array.isArray(state.pending) ? state.pending : [];
      const allHistory = Array.isArray(state.history) ? state.history : [];
      this.historyRecommendations = allHistory.filter((item) => item.status !== 'PENDING');
      this.loadError = Object.values(state).some((value) => value === null);
      this.state = this.loadError ? 'partial' : 'ready';
      this.buildCalibrationChart();
    });
  }

  runAnalysis() {
    this.runningAnalysis = true;
    this.http.post<any>('/api/agent-evolution/run-analysis', {})
      .pipe(catchError(() => of({ __error: true })))
      .subscribe((res) => {
        this.runningAnalysis = false;
        if (res?.__error) {
          this.toast('Analysis request failed');
          return;
        }
        if (res?.status === 'INSUFFICIENT_DATA') {
          this.toast(`Need ${res.trades_needed ?? 'more'} closed trades before analysis`);
        } else {
          this.toast(`Analysis complete: ${res?.recommendations_generated || 0} recommendations`);
        }
        this.refresh();
      });
  }

  review(rec: Recommendation, status: 'APPROVED' | 'REJECTED') {
    this.reviewingId = rec.id;
    this.http.post<Recommendation>(`/api/agent-evolution/recommendations/${rec.id}/review`, {
      status,
      note: `Marked ${status} from Agent Evolution Dashboard`,
    }).pipe(catchError(() => of(null))).subscribe((res) => {
      this.reviewingId = null;
      if (!res) {
        this.toast('Review update failed');
        return;
      }
      this.toast(`Recommendation marked ${status}`);
      this.refresh();
    });
  }

  private safeGet<T>(path: string) {
    return this.http.get<T>(path).pipe(catchError(() => of(null)));
  }

  private buildCalibrationChart() {
    const buckets = this.calibration?.buckets || [];
    const labels = buckets.map((b) => b.range_display || b.range || b.key || '-');
    const values = buckets.map((b) => b.win_rate_pct ?? 0);
    const colors = buckets.map((b) => this.bucketColor(b.bar_color, b.win_rate_pct, b.trade_count));
    const currentFloor = (this.calibration?.current_confidence_floor || 0) * 100;

    this.calibrationChart = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,.94)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9', fontSize: 11 },
      },
      grid: { left: 36, right: 18, top: 22, bottom: 36 },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#1e293b' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [{
        type: 'bar',
        data: values.map((value, index) => ({
          value,
          itemStyle: { color: colors[index] },
        })),
        barWidth: '48%',
        markLine: currentFloor > 0 ? {
          symbol: 'none',
          label: {
            formatter: `Floor ${Math.round(currentFloor)}%`,
            color: '#94a3b8',
            fontSize: 10,
          },
          lineStyle: { color: '#f59e0b', type: 'dashed' },
          data: [{ yAxis: currentFloor }],
        } : undefined,
      }],
    };
  }

  private bucketColor(color?: string, winRate?: number | null, count?: number) {
    if (!count || color === 'gray') return '#475569';
    if (color === 'green' || (winRate ?? 0) >= 55) return '#10b981';
    if (color === 'yellow' || (winRate ?? 0) >= 40) return '#f59e0b';
    return '#ef4444';
  }

  patternMetric(pattern: FailurePattern) {
    if (pattern.win_rate_pct !== undefined) return `Win rate ${this.number(pattern.win_rate_pct)}%`;
    if (pattern.loss_rate_pct !== undefined) return `Loss rate ${this.number(pattern.loss_rate_pct)}%`;
    if (pattern.frequency_pct !== undefined) return `${this.number(pattern.frequency_pct)}% of losses`;
    return `${pattern.frequency || 0} trades`;
  }

  number(value?: number | null) {
    if (value === undefined || value === null || Number.isNaN(value)) return '0.0';
    return Number(value).toFixed(1);
  }

  percent(value?: number | null) {
    if (value === undefined || value === null || Number.isNaN(value)) return '-';
    const n = value <= 1 ? value * 100 : value;
    return `${Math.round(n)}%`;
  }

  formatTime(value?: string | null) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  formatLabel(value?: string) {
    return String(value || '-').replace(/_/g, ' ').toUpperCase();
  }

  edgeColor(value?: number) {
    if ((value || 0) >= 10) return 'var(--nx-success)';
    if ((value || 0) < 0) return 'var(--nx-danger)';
    return 'var(--nx-warning)';
  }

  verdictClass(value?: string) {
    const v = String(value || '').toUpperCase();
    if (v === 'HIGH_VALUE' || v === 'USEFUL') return 'nx-chip-ok';
    if (v === 'HARMFUL') return 'nx-chip-fail';
    if (v === 'QUESTIONABLE' || v === 'WEAK') return 'nx-chip-warn';
    return 'nx-chip-info';
  }

  riskClass(value?: string) {
    const v = String(value || '').toUpperCase();
    if (v === 'HIGH') return 'nx-chip-fail';
    if (v === 'MEDIUM') return 'nx-chip-warn';
    if (v === 'LOW') return 'nx-chip-ok';
    return 'nx-chip-info';
  }

  statusClass(value?: string) {
    const v = String(value || '').toUpperCase();
    if (v === 'APPROVED') return 'nx-chip-ok';
    if (v === 'REJECTED') return 'nx-chip-fail';
    if (v === 'ARCHIVED') return 'nx-chip-warn';
    return 'nx-chip-info';
  }

  private toast(message: string) {
    this.snackBar.open(message, 'OK', { duration: 2600 });
  }
}
