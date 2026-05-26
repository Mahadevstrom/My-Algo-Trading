import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { catchError, forkJoin, interval, of, startWith, Subscription, switchMap, timeout } from 'rxjs';

const SCHEDULE_LABELS: Record<string, string> = {
  pre_market_start: 'Pre-market',
  market_open: 'Open',
  first_trade_time: 'First Trade',
  midday_start: 'Midday Caution',
  midday_end: 'Afternoon Resume',
  late_session_start: 'Late Session',
  no_new_trade_after: 'No New Trades',
  square_off_time: 'Square-off Review',
  market_close: 'Close',
  post_market_end: 'Post-market End',
};

@Component({
  selector: 'app-session-gate',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">SESSION GATE</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Market Session Controls
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Read-only entry/exit window monitor ·
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
    <span>NO CONFIG MUTATION</span>
    <span>NO PAPER TRADE CREATION</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Gate route group: /api/session-gate
    </span>
  </div>

  <div *ngIf="loadError" class="nx-alert">
    Some session-gate endpoints are unavailable.
    Showing the latest partial session context.
  </div>

  <div *ngIf="loading" class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">LOADING SESSION GATE</span>
    <div class="nx-loading-line" style="margin-top:10px"></div>
    <div class="nx-loading-line" style="width:68%;margin-top:10px"></div>
  </div>

  <div class="nx-card"
       style="margin-bottom:16px;border-left:4px solid"
       [style.border-left-color]="sessionColor">
    <div style="display:grid;
                grid-template-columns:1fr auto;
                gap:16px;align-items:start">
      <div>
        <span class="nx-label">CURRENT SESSION</span>
        <div style="font-size:34px;font-weight:700;
                    margin:6px 0"
             [style.color]="sessionColor">
          {{decision?.session_status || status?.session_status || 'UNKNOWN'}}
        </div>
        <div style="font-size:13px;color:var(--nx-text-3);
                    line-height:1.6">
          {{decision?.block_reason || decision?.caution_reason ||
            explain?.explanation || 'Session gate is active.'}}
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;
                  justify-content:flex-end">
        <span class="nx-chip"
              [ngClass]="decision?.allow_new_signal
                ? 'nx-chip-ok' : 'nx-chip-warn'">
          SIGNAL {{decision?.allow_new_signal ? 'YES' : 'NO'}}
        </span>
        <span class="nx-chip"
              [ngClass]="decision?.allow_paper_entry
                ? 'nx-chip-ok' : 'nx-chip-warn'">
          ENTRY {{decision?.allow_paper_entry ? 'YES' : 'NO'}}
        </span>
        <span class="nx-chip"
              [ngClass]="decision?.allow_paper_exit
                ? 'nx-chip-ok' : 'nx-chip-warn'">
          EXIT {{decision?.allow_paper_exit ? 'YES' : 'NO'}}
        </span>
      </div>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,
              minmax(170px,1fr));
              gap:10px;margin-bottom:16px">
    <div *ngFor="let card of statusCards"
         class="nx-card">
      <span class="nx-label">{{card.label}}</span>
      <div class="nx-value"
           [style.color]="card.color">
        {{card.value}}
      </div>
      <div class="nx-sub">{{card.sub}}</div>
    </div>
  </div>

  <div class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">MARKET HOURS TIMELINE</span>
    <div style="position:relative;margin-top:18px;
                padding-top:18px">
      <div style="position:absolute;left:0;right:0;top:24px;
                  height:2px;background:var(--nx-border)">
      </div>
      <div style="display:grid;
                  grid-template-columns:repeat(auto-fit,
                  minmax(110px,1fr));
                  gap:8px;position:relative">
        <div *ngFor="let row of scheduleRows"
             style="text-align:center;position:relative">
          <div style="width:10px;height:10px;border-radius:50%;
                      margin:0 auto 8px;border:2px solid"
               [style.background]="row.active
                 ? 'var(--nx-accent)' : 'var(--nx-bg-surface)'"
               [style.border-color]="row.active
                 ? 'var(--nx-accent)' : 'var(--nx-border)'">
          </div>
          <div style="font-size:11px;font-weight:600;
                      color:var(--nx-text-2)">
            {{row.time}}
          </div>
          <div style="font-size:10px;color:var(--nx-text-3);
                      margin-top:2px">
            {{row.label}}
          </div>
        </div>
      </div>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:1fr 1fr;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">SESSION FILTER CONFIG</span>
      <div style="display:grid;
                  grid-template-columns:repeat(2,1fr);
                  gap:8px;margin-top:8px">
        <div *ngFor="let item of filterItems"
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
      <span class="nx-label">POLICY EXPLANATION</span>
      <div *ngFor="let line of explanationLines"
           style="display:flex;gap:8px;align-items:flex-start;
                  padding:7px 0;border-bottom:0.5px solid
                  var(--nx-border)">
        <mat-icon style="font-size:15px;width:15px;height:15px;
                         color:var(--nx-cyan);margin-top:1px">
          info
        </mat-icon>
        <div style="font-size:12px;color:var(--nx-text-2);
                    line-height:1.5">
          {{line}}
        </div>
      </div>
    </div>
  </div>

</div>
  `,
})
export class SessionGateComponent implements OnInit, OnDestroy {
  status: any = null;
  schedule: any = null;
  decision: any = null;
  explain: any = null;
  lastUpdated = 'never';
  loading = true;
  loadError = false;
  private sub?: Subscription;

  get sessionColor(): string {
    const text = String(
      this.decision?.session_status || this.status?.session_status || ''
    ).toUpperCase();
    if (text.includes('ACTIVE') || text.includes('OPEN')) return 'var(--nx-success)';
    if (text.includes('CAUTION') || text.includes('WAIT') || text.includes('LATE')) return 'var(--nx-warning)';
    if (text.includes('CLOSED') || text.includes('BLOCK') || text.includes('NO_NEW')) return 'var(--nx-danger)';
    return 'var(--nx-text-3)';
  }

  get statusCards(): any[] {
    return [
      {
        label: 'IST Now',
        value: this.status?.now_ist || '-',
        sub: this.status?.weekday || '-',
        color: 'var(--nx-text-1)',
      },
      {
        label: 'Market Day',
        value: this.status?.is_market_day ? 'YES' : 'NO',
        sub: this.status?.trading_date || '-',
        color: this.status?.is_market_day ? 'var(--nx-success)' : 'var(--nx-warning)',
      },
      {
        label: 'Market Open',
        value: this.status?.is_market_open ? 'YES' : 'NO',
        sub: this.status?.timezone || 'Asia/Kolkata',
        color: this.status?.is_market_open ? 'var(--nx-success)' : 'var(--nx-danger)',
      },
      {
        label: 'Next Change',
        value: this.decision?.next_session_change || '-',
        sub: 'Gate transition',
        color: 'var(--nx-cyan)',
      },
      {
        label: 'Square-off Review',
        value: this.decision?.allow_square_off_review ? 'YES' : 'NO',
        sub: 'Exit-only safety',
        color: this.decision?.allow_square_off_review ? 'var(--nx-success)' : 'var(--nx-text-3)',
      },
      {
        label: 'Broker Safety',
        value: this.decision?.safety_summary?.live_order_status || 'BLOCKED',
        sub: this.decision?.safety_summary?.trading_mode || 'PAPER',
        color: 'var(--nx-success)',
      },
    ];
  }

  get scheduleRows(): any[] {
    const schedule = this.schedule?.schedule || this.status?.schedule || {};
    const now = this.minutesFromText(this.status?.now_ist);
    let activeIndex = -1;
    const rows = Object.entries(SCHEDULE_LABELS).map(([key, label], index) => {
      const time = schedule[key] || '-';
      const minutes = this.minutesFromText(time);
      if (minutes >= 0 && now >= minutes) activeIndex = index;
      return { key, label, time, active: false };
    });
    return rows.map((row, index) => ({
      ...row,
      active: index === activeIndex,
    }));
  }

  get filterItems(): any[] {
    const filters = this.schedule?.filters || this.status?.filters || {};
    const names = [
      ['block_first_minutes', 'Block First Minutes'],
      ['block_expiry_last_30_min', 'Expiry Last 30 Min'],
      ['allow_midday_trades', 'Midday Trades'],
      ['allow_late_session_trades', 'Late Session Trades'],
      ['holiday_calendar_enabled', 'Holiday Calendar'],
    ];
    return names.map(([key, label]) => {
      const value = key === 'holiday_calendar_enabled'
        ? (this.status?.holiday_calendar_enabled || this.schedule?.holiday_calendar_enabled)
        : filters[key];
      return {
        label,
        value: value === true ? 'YES' : value === false ? 'NO' : 'UNKNOWN',
        color: value === true ? 'var(--nx-success)'
          : value === false ? 'var(--nx-warning)' : 'var(--nx-text-3)',
      };
    });
  }

  get explanationLines(): string[] {
    return [
      this.explain?.explanation,
      this.explain?.entry_policy,
      this.explain?.exit_policy,
      this.decision?.block_reason,
      this.decision?.caution_reason,
      this.explain?.safety_note,
    ].filter(Boolean);
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
      status: this.get('/api/session-gate/status'),
      schedule: this.get('/api/session-gate/schedule'),
      decision: this.get('/api/session-gate/decision'),
      explain: this.get('/api/session-gate/explain'),
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
    this.status = state.status;
    this.schedule = state.schedule;
    this.decision = state.decision;
    this.explain = state.explain;
    this.lastUpdated = new Date().toLocaleTimeString(
      'en-IN', { timeZone: 'Asia/Kolkata' });
  }

  minutesFromText(value: string | undefined): number {
    if (!value) return -1;
    const match = String(value).match(/(\d{1,2}):(\d{2})/);
    if (!match) return -1;
    return Number(match[1]) * 60 + Number(match[2]);
  }
}
