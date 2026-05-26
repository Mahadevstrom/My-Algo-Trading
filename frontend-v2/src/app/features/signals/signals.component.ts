import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, interval, of, startWith, Subscription, switchMap } from 'rxjs';

@Component({
  selector: 'app-signals',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDividerModule,
    MatIconModule,
    MatProgressBarModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">SIGNAL ENGINE V2</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Live Signal Analysis
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);margin:4px 0 0">
        Paper-only · No execution · Refreshes every 30s
      </p>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <span style="font-size:11px;color:var(--nx-text-3)">
        Updated: {{lastUpdated}}
      </span>
      <button mat-stroked-button (click)="refresh()"
              style="font-size:12px;color:var(--nx-text-2)">
        <mat-icon style="font-size:16px;width:16px;height:16px">
          refresh
        </mat-icon>
        Refresh
      </button>
    </div>
  </div>

  <div style="background:rgba(239,68,68,.06);
              border:0.5px solid rgba(239,68,68,.3);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#ef4444;
              margin-bottom:16px;
              display:flex;gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>PAPER ONLY</span>
    <span>NO BROKER ORDERS</span>
    <span>NO LIVE EXECUTION</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Capital protection active
    </span>
  </div>

  <div *ngIf="!vm && !loadError"
       class="nx-card"
       style="margin-bottom:16px;text-align:center;padding:32px">
    <div style="font-size:13px;color:var(--nx-text-3)">
      Loading latest Signal V2 context...
    </div>
  </div>

  <div *ngIf="loadError"
       class="nx-card"
       style="margin-bottom:16px;border-color:rgba(239,68,68,.35)">
    <span class="nx-label">SIGNAL API</span>
    <div style="font-size:16px;color:var(--nx-danger);font-weight:600">
      Unable to load latest signal
    </div>
    <div style="font-size:12px;color:var(--nx-text-3);margin-top:6px">
      Endpoint: {{signalEndpoint}}
    </div>
  </div>

  <ng-container *ngIf="vm">
    <div class="nx-card" style="margin-bottom:16px;
                                 position:relative;overflow:hidden">
      <div style="position:absolute;top:0;left:0;width:4px;
                  height:100%;border-radius:4px 0 0 4px"
           [style.background]="decisionColor">
      </div>
      <div style="padding-left:12px">
        <div style="display:grid;
                    grid-template-columns:1fr auto;
                    gap:16px;align-items:start">
          <div>
            <span class="nx-label">SIGNAL DECISION</span>
            <div style="display:flex;align-items:center;
                        gap:12px;margin:6px 0">
              <span style="font-size:32px;font-weight:700;
                           letter-spacing:.04em"
                    [style.color]="decisionColor">
                {{vm.decision || 'NO_TRADE'}}
              </span>
              <div *ngIf="vm.decision === 'NO_TRADE'"
                   style="max-width:330px">
                <p style="font-size:12px;color:var(--nx-text-3);
                          margin:0;line-height:1.6">
                  Not enough confirmed signal evidence.
                  Skipping this setup protects your capital.
                  <strong style="color:var(--nx-text-2)">
                    Not trading is a valid position.
                  </strong>
                </p>
              </div>
              <div *ngIf="vm.decision === 'BUY_CALL'"
                   style="max-width:330px">
                <p style="font-size:12px;color:var(--nx-text-3);
                          margin:0;line-height:1.6">
                  Bullish setup confirmed. CE option profits when
                  NIFTY moves up. Max loss is premium paid. Paper only.
                </p>
              </div>
              <div *ngIf="vm.decision === 'BUY_PUT'"
                   style="max-width:330px">
                <p style="font-size:12px;color:var(--nx-text-3);
                          margin:0;line-height:1.6">
                  Bearish setup confirmed. PE option profits when
                  NIFTY moves down. Max loss is premium paid. Paper only.
                </p>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <span class="nx-chip" [ngClass]="confidenceChip">
                {{vm.confidence || '-'}} CONFIDENCE
              </span>
              <span class="nx-chip nx-chip-info">
                Score {{vm.score || 0}} / {{vm.required_score || 70}}
              </span>
              <span class="nx-chip"
                    [ngClass]="vm.market_state?.time_gate?.allowed
                      ? 'nx-chip-ok' : 'nx-chip-warn'">
                {{vm.market_state?.time_gate?.window_name || 'UNKNOWN'}}
              </span>
              <span class="nx-chip nx-chip-paper">
                {{vm.status || 'PAPER'}}
              </span>
            </div>
          </div>

          <div echarts [options]="scoreGauge"
               style="height:160px;width:200px;flex-shrink:0">
          </div>
        </div>
      </div>
    </div>

    <div style="display:grid;
                grid-template-columns:1fr 1fr;
                gap:12px;margin-bottom:16px">

      <div class="nx-card">
        <div style="display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:6px">
          <span class="nx-label">FILTER BREAKDOWN</span>
          <span style="font-size:10px;color:var(--nx-text-3);
                       letter-spacing:.06em">
            {{filterRows.length}} CHECKS
          </span>
        </div>

        <div *ngFor="let f of filterRows"
             style="display:flex;justify-content:space-between;
                    align-items:center;padding:9px 0;
                    border-bottom:0.5px solid var(--nx-border)">
          <div>
            <div style="font-size:12px;
                        color:var(--nx-text-2);
                        font-weight:500">
              {{f.name}}
            </div>
            <div style="font-size:11px;
                        color:var(--nx-text-3);margin-top:2px">
              {{f.detail}}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <div style="width:64px;height:3px;
                        background:var(--nx-border);
                        border-radius:2px;overflow:hidden">
              <div [style.width]="f.pct + '%'"
                   [style.background]="f.ok
                     ? 'var(--nx-success)'
                     : f.warn
                     ? 'var(--nx-warning)'
                     : 'var(--nx-danger)'"
                   style="height:100%">
              </div>
            </div>
            <mat-icon style="font-size:14px;width:14px;height:14px"
                      [style.color]="f.ok
                        ? 'var(--nx-success)'
                        : f.warn
                        ? 'var(--nx-warning)'
                        : 'var(--nx-danger)'">
              {{f.ok ? 'check_circle'
                : f.warn ? 'warning' : 'cancel'}}
            </mat-icon>
            <span style="font-size:11px;font-weight:600;
                         min-width:72px;text-align:right"
                  [style.color]="f.ok
                    ? 'var(--nx-success)'
                    : f.warn
                    ? 'var(--nx-warning)'
                    : 'var(--nx-danger)'">
              {{f.value}}
            </span>
          </div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px">
        <div class="nx-card" style="flex:1">
          <span class="nx-label">MARKET DIAGNOSTICS</span>
          <div style="display:grid;
                      grid-template-columns:1fr 1fr;
                      gap:10px;margin-top:8px">

            <div *ngFor="let d of diagnostics"
                 style="background:var(--nx-bg-raised);
                        border-radius:8px;padding:10px">
              <div style="font-size:10px;
                          color:var(--nx-text-3);
                          letter-spacing:.06em">
                {{d.label}}
              </div>
              <div style="font-size:18px;font-weight:600;
                          margin-top:4px"
                   [style.color]="d.color">
                {{d.value}}
              </div>
              <div style="font-size:10px;
                          color:var(--nx-text-3);margin-top:2px">
                {{d.sub}}
              </div>
            </div>
          </div>
        </div>

        <div class="nx-card">
          <span class="nx-label">OPTION CANDIDATE</span>
          <div *ngIf="!vm.selected_strike"
               style="font-size:12px;color:var(--nx-text-3);
                      padding:8px 0">
            No option selected because the signal is below threshold.
          </div>
          <div *ngIf="vm.selected_strike"
               style="display:grid;
                      grid-template-columns:1fr 1fr;
                      gap:8px;margin-top:8px">
            <div *ngFor="let o of optionDetails"
                 style="background:var(--nx-bg-raised);
                        border-radius:6px;padding:8px">
              <div style="font-size:10px;
                          color:var(--nx-text-3)">{{o.label}}</div>
              <div style="font-size:14px;font-weight:500;
                          color:var(--nx-text-1);margin-top:3px">
                {{o.value}}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div style="display:grid;
                grid-template-columns:1fr 1fr;
                gap:12px;margin-bottom:16px">

      <div class="nx-card">
        <span class="nx-label">REASONS</span>
        <div *ngIf="!reasons.length"
             style="font-size:12px;color:var(--nx-text-3);
                    padding:8px 0">
          No blocking reasons
        </div>
        <div *ngFor="let r of reasons"
             style="display:flex;align-items:flex-start;
                    gap:8px;padding:6px 0;
                    border-bottom:0.5px solid var(--nx-border)">
          <mat-icon style="font-size:14px;width:14px;height:14px;
                           color:var(--nx-danger);margin-top:2px">
            error_outline
          </mat-icon>
          <span style="font-size:12px;color:var(--nx-text-2)">
            {{r}}
          </span>
        </div>
      </div>

      <div class="nx-card">
        <span class="nx-label">SUPPORTING CHECKS</span>
        <div *ngIf="!supporting.length"
             style="font-size:12px;color:var(--nx-text-3);
                    padding:8px 0">
          No supporting checks yet
        </div>
        <div *ngFor="let s of supporting"
             style="display:flex;align-items:flex-start;
                    gap:8px;padding:6px 0;
                    border-bottom:0.5px solid var(--nx-border)">
          <mat-icon style="font-size:14px;width:14px;height:14px;
                           color:var(--nx-success);margin-top:2px">
            check_circle_outline
          </mat-icon>
          <span style="font-size:12px;color:var(--nx-text-2)">
            {{s}}
          </span>
        </div>
      </div>
    </div>
  </ng-container>
</div>
  `,
})
export class SignalsComponent implements OnInit, OnDestroy {
  vm: any = null;
  lastUpdated = 'never';
  loadError = false;
  scoreGauge: object = {};
  readonly signalEndpoint = '/api/signals-v2/latest';
  private sub?: Subscription;

  get decisionColor(): string {
    const d = this.vm?.decision || '';
    if (d === 'BUY_CALL') return 'var(--nx-success)';
    if (d === 'BUY_PUT') return 'var(--nx-danger)';
    return 'var(--nx-text-3)';
  }

  get confidenceChip(): string {
    const c = this.vm?.confidence || '';
    if (c === 'HIGH') return 'nx-chip-ok';
    if (c === 'MEDIUM') return 'nx-chip-warn';
    return 'nx-chip-paper';
  }

  get reasons(): string[] {
    return this.vm?.reasons || [];
  }

  get supporting(): string[] {
    return this.vm?.supporting_checks || [];
  }

  get filterRows(): any[] {
    if (!this.vm) return [];
    const ms = this.vm.market_state || {};
    const rsi = this.num(ms.rsi);
    const adx = this.num(ms.adx);
    const missingTimeframes = this.vm.missing_timeframes || [];
    const candleCounts = this.vm.candle_counts_by_timeframe || {};
    const requiredCandles = this.vm.required_candles_by_timeframe || {};
    const candleRequiredCount = Object.keys(requiredCandles).length;
    const candleActualCount = Object.values(candleCounts)
      .reduce((sum: number, value: any) => sum + (Number(value) || 0), 0);
    const candleWarmupStatus = this.vm.candle_warmup_status
      || (candleRequiredCount === 0 ? 'NOT_RUN'
        : missingTimeframes.length ? 'INCOMPLETE' : 'READY');
    const optionCandidatePresent = this.vm.selected_option_present === true
      || !!this.vm.selected_option
      || !!this.vm.selected_strike;
    const trapRisk = this.vm.trap_risk || 'UNKNOWN';
    const oiAvailable = this.vm.oi_change_available === true;
    const flowStatus = this.vm.market_flow_status || 'UNKNOWN';
    const flowScore = this.num(this.vm.market_flow_score) ?? 0;
    const riskBlocked = this.hasFailed([
      'SESSION_GATE_',
      'RISK_',
      'SAFETY_',
      'KILL_SWITCH',
      'ORDER_',
    ]);
    const dataQualityFailed = this.hasFailed(['DATA_QUALITY_'])
      || this.vm.data_quality_gate_passed === false;
    const optionChainFailed = this.hasFailed(['OPTION_CHAIN_']);
    const liquidityFailed = this.hasFailed(['LIQUIDITY_']);
    const candleFailed = this.hasFailed(['LIVE_CANDLES_', 'CANDLE_', 'WARMUP_'])
      || missingTimeframes.length > 0;
    const marketFlowFailed = this.hasFailed(['MARKET_FLOW_', 'OI_CHANGE_REQUIRED'])
      || flowStatus === 'RATE_LIMITED'
      || flowStatus === 'NO_DATA';
    const optionCandidateFailed = this.hasFailed(['NO_OPTION_CANDIDATE'])
      || !optionCandidatePresent;

    return [
      {
        name: 'Risk / Safety Gate',
        detail: this.vm.risk_gate_status || 'Paper-only safety context',
        value: riskBlocked ? 'BLOCKED' : 'PASS',
        ok: !riskBlocked,
        warn: false,
        pct: riskBlocked ? 10 : 95,
      },
      {
        name: 'Data Quality',
        detail: this.vm.data_quality_status || 'UNKNOWN',
        value: dataQualityFailed ? (this.vm.data_quality_status || 'FAILED') : 'PASS',
        ok: !dataQualityFailed,
        warn: this.vm.data_quality_status === 'WARNING',
        pct: dataQualityFailed ? 20 : 90,
      },
      {
        name: 'Secondary Data',
        detail: this.vm.secondary_data_status || 'UNKNOWN',
        value: this.vm.secondary_data_status || 'UNKNOWN',
        ok: !['DISABLED', 'ERROR', 'UNAUTHORIZED'].includes(this.vm.secondary_data_status || ''),
        warn: ['UNKNOWN', 'CONFIGURED_READ_ONLY'].includes(this.vm.secondary_data_status || ''),
        pct: this.vm.secondary_data_status === 'CONFIGURED_READ_ONLY' ? 65 : 50,
      },
      {
        name: 'Candle Warmup',
        detail: candleRequiredCount
          ? `${candleActualCount} candles across ${Object.keys(candleCounts).length} timeframes`
          : 'No candle warmup data in latest response',
        value: candleWarmupStatus,
        ok: !candleFailed && candleWarmupStatus === 'READY',
        warn: candleWarmupStatus === 'NOT_RUN',
        pct: candleWarmupStatus === 'READY' ? 90
          : candleWarmupStatus === 'NOT_RUN' ? 45 : 20,
      },
      {
        name: 'Trend',
        detail: ms.vwap_above === true
          ? 'Price above VWAP - institutional bias'
          : ms.vwap_above === false
          ? 'Price below VWAP - caution'
          : 'VWAP unavailable',
        value: this.vm.trend_status || 'UNKNOWN',
        ok: (this.vm.trend_status || '').includes('BULL')
            || (this.vm.trend_status || '').includes('BEAR'),
        warn: false,
        pct: ms.vwap_above === true ? 85 : 30,
      },
      {
        name: 'Momentum (RSI)',
        detail: 'RSI ' + (rsi != null ? rsi.toFixed(1) : '-'),
        value: ms.rsi_confirms ? 'CONFIRMS' : 'WEAK',
        ok: ms.rsi_confirms === true,
        warn: rsi != null && (rsi > 70 || rsi < 30),
        pct: rsi != null ? Math.round(rsi) : 50,
      },
      {
        name: 'Chop (ADX)',
        detail: 'ADX ' + (adx != null ? adx.toFixed(1) : '-'),
        value: adx != null && adx >= 25 ? 'TRENDING'
          : adx != null && adx >= 20 ? 'WEAK TREND' : 'CHOPPY',
        ok: adx != null && adx >= 25,
        warn: adx != null && adx >= 20 && adx < 25,
        pct: Math.min(Number(adx || 0) * 2, 100),
      },
      {
        name: 'Volatility (BB)',
        detail: this.vm.volatility_status || 'UNKNOWN',
        value: this.vm.volatility_status || 'UNKNOWN',
        ok: !(this.vm.volatility_status || '').includes('SQUEEZE'),
        warn: (this.vm.volatility_status || '').includes('SQUEEZE'),
        pct: 60,
      },
      {
        name: 'Regime',
        detail: ms.regime || this.vm.regime || 'NEUTRAL',
        value: ms.regime || this.vm.regime || 'NEUTRAL',
        ok: ['TRENDING', 'BULLISH', 'BEARISH'].includes(ms.regime || this.vm.regime || ''),
        warn: ['NEUTRAL', 'RANGING'].includes(ms.regime || this.vm.regime || 'NEUTRAL'),
        pct: ['TRENDING', 'BULLISH', 'BEARISH'].includes(ms.regime || this.vm.regime || '')
          ? 80 : 55,
      },
      {
        name: 'Session / Time Gate',
        detail: ms.time_gate?.window_name || 'UNKNOWN',
        value: ms.time_gate?.allowed ? 'ALLOWED' : 'BLOCKED',
        ok: ms.time_gate?.allowed === true,
        warn: false,
        pct: ms.time_gate?.allowed ? 90 : 10,
      },
      {
        name: 'Option Chain',
        detail: this.vm.option_chain_status || 'UNKNOWN',
        value: optionChainFailed ? 'FAILED' : (this.vm.option_chain_status || 'UNKNOWN'),
        ok: !optionChainFailed && ['OK', 'CONNECTED', 'AVAILABLE'].includes(this.vm.option_chain_status || ''),
        warn: !optionChainFailed,
        pct: optionChainFailed ? 15 : 55,
      },
      {
        name: 'Option Candidate',
        detail: this.vm.selected_option_reason || 'No selected option context',
        value: optionCandidatePresent ? 'SELECTED' : 'NOT_SELECTED',
        ok: optionCandidatePresent,
        warn: !optionCandidatePresent && this.vm.decision === 'NO_TRADE',
        pct: optionCandidatePresent ? 90 : 35,
      },
      {
        name: 'Liquidity',
        detail: this.vm.liquidity_status || this.vm.selected_option?.liquidity_score || 'UNKNOWN',
        value: liquidityFailed ? 'FAILED' : (this.vm.liquidity_status || 'UNKNOWN'),
        ok: !liquidityFailed && ['OK', 'GOOD', 'LIQUID'].includes(this.vm.liquidity_status || ''),
        warn: !liquidityFailed,
        pct: this.num(this.vm.selected_option?.liquidity_score) ?? (liquidityFailed ? 15 : 50),
      },
      {
        name: 'Market Flow',
        detail: `Flow score ${flowScore} · ${this.vm.market_flow_bias || 'UNKNOWN'}`,
        value: flowStatus,
        ok: this.vm.market_flow_confirms_signal === true
          || flowStatus.includes('CONFIRM'),
        warn: !marketFlowFailed && !flowStatus.includes('CONFIRM'),
        pct: Math.min(flowScore, 100),
      },
      {
        name: 'Trap Risk',
        detail: this.vm.trap_type || 'No trap type confirmed',
        value: trapRisk,
        ok: ['LOW', 'NONE', 'NO_TRAP'].includes(trapRisk),
        warn: ['UNKNOWN', 'MEDIUM'].includes(trapRisk),
        pct: trapRisk === 'HIGH' ? 15 : trapRisk === 'MEDIUM' ? 45 : 65,
      },
      {
        name: 'OI Change',
        detail: this.vm.flow_change_bias || 'No OI-change edge',
        value: oiAvailable ? 'AVAILABLE' : 'UNAVAILABLE',
        ok: oiAvailable,
        warn: !oiAvailable,
        pct: oiAvailable ? 80 : 45,
      },
    ];
  }

  get diagnostics(): any[] {
    const ms = this.vm?.market_state || {};
    const rsi = this.num(ms.rsi);
    const adx = this.num(ms.adx);
    return [
      {
        label: 'RSI (14)',
        value: rsi != null ? rsi.toFixed(1) : 'N/A',
        color: rsi != null && rsi > 70 ? 'var(--nx-danger)'
          : rsi != null && rsi < 30 ? 'var(--nx-warning)'
          : 'var(--nx-success)',
        sub: rsi != null && rsi > 70 ? 'Overbought'
          : rsi != null && rsi < 30 ? 'Oversold' : 'Neutral zone',
      },
      {
        label: 'ADX',
        value: adx != null ? adx.toFixed(1) : 'N/A',
        color: adx != null && adx >= 25 ? 'var(--nx-success)'
          : adx != null && adx >= 20 ? 'var(--nx-warning)'
          : 'var(--nx-danger)',
        sub: adx != null && adx >= 25 ? 'Trending'
          : adx != null && adx >= 20 ? 'Weak' : 'Choppy',
      },
      {
        label: 'ATR',
        value: this.vm?.atr != null
          ? Number(this.vm.atr).toFixed(1) : 'N/A',
        color: 'var(--nx-cyan)',
        sub: 'SL / target range',
      },
      {
        label: 'VWAP',
        value: ms.vwap != null ? Number(ms.vwap).toFixed(0) : 'N/A',
        color: ms.vwap_above === true
          ? 'var(--nx-success)'
          : ms.vwap_above === false
          ? 'var(--nx-danger)'
          : 'var(--nx-text-3)',
        sub: ms.vwap_above === true ? 'Price above'
          : ms.vwap_above === false ? 'Price below' : 'Unavailable',
      },
      {
        label: 'Regime',
        value: ms.regime || 'NEUTRAL',
        color: ms.regime === 'TRENDING'
          ? 'var(--nx-success)'
          : ms.regime === 'RANGING'
          ? 'var(--nx-warning)'
          : 'var(--nx-text-2)',
        sub: 'Market regime',
      },
      {
        label: 'Time window',
        value: ms.time_gate?.quality || ms.time_gate?.window_name || '-',
        color: ms.time_gate?.allowed
          ? 'var(--nx-success)' : 'var(--nx-danger)',
        sub: '+' + (ms.time_gate?.bonus_score || 0) + ' score bonus',
      },
    ];
  }

  get optionDetails(): any[] {
    if (!this.vm?.selected_strike) return [];
    return [
      { label: 'Strike', value: this.vm.selected_strike },
      { label: 'Type', value: this.vm.option_type || '-' },
      {
        label: 'SL',
        value: this.vm.stop_loss ? Number(this.vm.stop_loss).toFixed(2) : '-',
      },
      {
        label: 'Target',
        value: this.vm.target ? Number(this.vm.target).toFixed(2) : '-',
      },
      {
        label: 'ATR SL',
        value: this.vm.invalidation_reference_method || '-',
      },
      {
        label: 'Liquidity',
        value: this.vm.liquidity_score || '-',
      },
    ];
  }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(30000).pipe(
      startWith(0),
      switchMap(() => this.loadSignal())
    ).subscribe((data) => this.applySignal(data));
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  refresh() {
    this.loadSignal().subscribe((data) => this.applySignal(data));
  }

  buildGauge(score: number) {
    this.scoreGauge = {
      backgroundColor: 'transparent',
      series: [{
        type: 'gauge',
        min: 0,
        max: 100,
        splitNumber: 5,
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.50, '#ef4444'],
              [0.70, '#f59e0b'],
              [1.00, '#10b981'],
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
        axisLabel: {
          color: '#64748b',
          fontSize: 9,
          formatter: (v: number) =>
            v === 0 ? '0' : v === 70 ? '70*'
            : v === 100 ? '100' : '',
        },
        detail: {
          valueAnimation: true,
          fontSize: 24,
          fontWeight: 700,
          color: 'inherit',
          offsetCenter: [0, '40%'],
          formatter: '{value}',
        },
        data: [{ value: score, name: '' }],
      }],
    };
  }

  private loadSignal() {
    return this.http.get<any>(this.signalEndpoint).pipe(
      catchError(() => of(null))
    );
  }

  private applySignal(data: any) {
    this.vm = this.normalizeSignal(data);
    this.loadError = !this.vm;
    this.lastUpdated = new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
    });
    this.buildGauge(this.num(this.vm?.score) || 0);
  }

  private normalizeSignal(payload: any): any {
    const signal = payload?.items?.[0] ?? payload?.signals?.[0] ?? payload;
    if (!signal || typeof signal !== 'object') return null;

    const marketState = signal.market_state || {};
    const sessionStatus = signal.session_status
      || marketState.session_status
      || marketState.session_gate?.session_status
      || 'UNKNOWN';
    const sessionAllowed = signal.session_allows_paper_entry === true
      || signal.session_allows_new_signal === true
      || marketState.time_gate?.allowed === true;

    const decision = signal.decision
      || signal.signal_type
      || signal.action
      || 'NO_TRADE';
    const selectedStrike = signal.selected_strike
      ?? signal.selected_option?.strike
      ?? signal.strike
      ?? null;
    const optionType = signal.option_type
      || signal.selected_option?.option_type
      || (decision === 'BUY_CALL' ? 'CE'
        : decision === 'BUY_PUT' ? 'PE' : '');

    return {
      ...signal,
      decision,
      option_type: optionType,
      selected_strike: selectedStrike,
      score: this.num(signal.score ?? signal.signal_score) ?? 0,
      required_score: this.num(signal.required_score) ?? 70,
      confidence: signal.confidence || signal.confidence_score || 'LOW',
      status: signal.status || 'PAPER',
      reasons: this.toStrings(
        signal.reasons
        ?? signal.rejection_reasons
        ?? signal.failed_checks
        ?? []
      ),
      supporting_checks: this.toStrings(
        signal.supporting_checks
        ?? signal.passed_checks
        ?? []
      ),
      trend_status: signal.trend_status || signal.trend || 'UNKNOWN',
      volatility_status: signal.volatility_status || 'UNKNOWN',
      market_flow_score: this.num(signal.market_flow_score) ?? 0,
      market_flow_status: signal.market_flow_status
        || signal.market_flow_bias
        || 'UNKNOWN',
      market_state: {
        ...marketState,
        time_gate: {
          ...(marketState.time_gate || {}),
          allowed: sessionAllowed,
          window_name: marketState.time_gate?.window_name || sessionStatus,
          quality: marketState.time_gate?.quality || sessionStatus,
          bonus_score: marketState.time_gate?.bonus_score || 0,
        },
        regime: marketState.regime || signal.regime || 'NEUTRAL',
      },
    };
  }

  private num(value: unknown): number | null {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  private toStrings(value: unknown): string[] {
    if (!value) return [];
    if (Array.isArray(value)) {
      return value
        .map((item) => typeof item === 'string'
          ? item
          : JSON.stringify(item))
        .filter(Boolean);
    }
    if (typeof value === 'object') {
      return Object.entries(value as Record<string, unknown>)
        .map(([key, item]) => `${key}: ${String(item)}`);
    }
    return [String(value)];
  }

  private hasFailed(prefixes: string[]): boolean {
    const checks = this.toStrings(this.vm?.failed_checks || []);
    return checks.some((check) =>
      prefixes.some((prefix) =>
        check === prefix || check.startsWith(prefix)
      )
    );
  }
}
