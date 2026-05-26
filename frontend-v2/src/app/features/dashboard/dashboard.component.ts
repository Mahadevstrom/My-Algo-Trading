import {
  Component,
  OnDestroy,
  OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NgxEchartsDirective } from 'ngx-echarts';
import {
  BehaviorSubject,
  catchError,
  combineLatest,
  forkJoin,
  interval,
  of,
  retry,
  startWith,
  Subscription,
  switchMap,
  timeout,
} from 'rxjs';

type Tf = '1m' | '3m' | '5m' | '15m';



interface TimelineStep {
  label: string;
  time: string;
  status: 'past' | 'active' | 'future';
}

interface KVItem {
  label: string;
  value: string;
  tone: 'good' | 'bad' | 'warn' | 'neutral' | 'info';
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    NgxEchartsDirective,
    MatButtonModule,
    MatButtonToggleModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule,
  ],
  template: `
<div class="td-root">

  <!-- ─── HEADER ─── -->
  <header class="td-header">
    <div class="td-header-left">
      <span class="td-eyebrow">TRADING DESK</span>
      <h1 class="td-title">NIFTY Paper Cockpit</h1>
      <p class="td-subtitle">
        Signal v2, chart, option chain, market flow, paper P&L — one screen.
      </p>
    </div>
    <div class="td-header-right">
      <span class="nx-chip" [ngClass]="safetyOk ? 'nx-chip-ok' : 'nx-chip-fail'">
        {{tradingMode || 'PAPER'}}
      </span>
      <span class="nx-chip nx-chip-fail">ORDERS BLOCKED</span>
      <span class="nx-chip nx-chip-warn">BROKER DISABLED</span>

      <button mat-stroked-button class="td-refresh-btn" (click)="refresh()">
        <mat-icon style="font-size:16px;width:16px;height:16px">refresh</mat-icon>
        Refresh
      </button>
    </div>
  </header>

  <!-- ─── LOADING ─── -->
  <div *ngIf="loading && !vm" class="nx-card td-loading">
    <span class="nx-label">LOADING TRADING DESK</span>
    <div class="nx-loading-line" style="margin-top:10px"></div>
    <div class="nx-loading-line" style="width:74%;margin-top:10px"></div>
    <div class="nx-loading-line" style="width:50%;margin-top:10px"></div>
  </div>

  <!-- ─── TRADING DESK ─── -->
  <ng-container *ngIf="vm">

    <!-- ─── HERO: CHART + SIGNAL COCKPIT ─── -->
    <div class="td-hero">

      <!-- CHART PANEL -->
      <div class="nx-card td-chart-card">
        <div class="td-chart-toolbar">
          <div class="td-tf-group">
            <mat-button-toggle-group [(ngModel)]="selectedTf"
                                     (change)="onTfChange($event.value)"
                                     style="border-color:var(--nx-border)">
              <mat-button-toggle *ngFor="let tf of timeframes" [value]="tf"
                                 style="font-size:11px;color:var(--nx-text-2)">
                {{tf}}
              </mat-button-toggle>
            </mat-button-toggle-group>
          </div>
          <div class="td-overlay-group">
            <button mat-stroked-button
                    [class.td-overlay-active]="showMarkers"
                    (click)="showMarkers=!showMarkers;buildChart()">
              Trades
            </button>
            <button mat-stroked-button
                    [class.td-overlay-active]="showLevels"
                    (click)="showLevels=!showLevels;buildChart()">
              S/R
            </button>
            <button mat-stroked-button
                    [class.td-overlay-active]="showSignals"
                    (click)="showSignals=!showSignals;buildChart()">
              Signals
            </button>
            <button mat-stroked-button
                    [class.td-overlay-active]="showVolume"
                    (click)="showVolume=!showVolume;buildChart()">
              Volume
            </button>
          </div>
        </div>

        <div class="td-chart-info">
          <div class="td-chart-symbol">
            <span>NIFTY</span>
            <strong>{{latestPrice || '-'}}</strong>
          </div>
          <div class="td-chart-ohlc" *ngIf="latestCandle">
            <span>O <strong>{{fmtNum(latestCandle.open)}}</strong></span>
            <span>H <strong class="c-success">{{fmtNum(latestCandle.high)}}</strong></span>
            <span>L <strong class="c-danger">{{fmtNum(latestCandle.low)}}</strong></span>
            <span>C <strong>{{fmtNum(latestCandle.close)}}</strong></span>
          </div>
        </div>

        <div class="td-chart-canvas">
          <div echarts [options]="chartOptions" [merge]="chartMerge"
               class="td-echart-host"
               (chartInit)="onChartInit($event)">
          </div>
          <div *ngIf="!candles.length" class="td-chart-empty">
            <mat-icon style="font-size:32px;width:32px;height:32px;color:var(--nx-text-3)">
              show_chart
            </mat-icon>
            <div>Waiting for NIFTY candle data</div>
          </div>
        </div>
      </div>

      <!-- SIGNAL COCKPIT SIDE -->
      <div class="td-cockpit-stack">

        <!-- SIGNAL COCKPIT -->
        <div class="nx-card td-cockpit">
          <span class="nx-label">SIGNAL COCKPIT</span>
          <div class="td-verdict"
               [class.can]="cockpitStatus === 'CAN_TRADE'">
            <span>{{cockpitStatus === 'CAN_TRADE' ? 'Can Trade' : 'Cannot Trade'}}</span>
            <strong [style.color]="decisionColor">{{vm.decision || 'NO_TRADE'}}</strong>
            <small>{{vm.score || 0}} / {{vm.required_score || 70}}</small>
          </div>

          <div class="td-cockpit-grid">
            <div *ngFor="let item of cockpitItems" class="td-kv-row">
              <span class="td-kv-label">{{item.label}}</span>
              <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
            </div>
          </div>
        </div>

        <!-- NO-TRADE SUMMARY -->
        <div class="nx-card">
          <span class="nx-label">NO-TRADE SUMMARY</span>
          <div class="td-cockpit-grid">
            <div *ngFor="let item of noTradeItems" class="td-kv-row">
              <span class="td-kv-label">{{item.label}}</span>
              <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
            </div>
          </div>
        </div>

        <!-- SIGNAL GAUGE -->
        <div class="nx-card" style="display:flex;flex-direction:column;align-items:center">
          <span class="nx-label" style="align-self:flex-start">SIGNAL GAUGE</span>
          <div echarts [options]="scoreGauge"
               style="height:150px;width:100%"></div>
        </div>
      </div>
    </div>

    <!-- ─── MARKET TIMELINE ─── -->
    <div class="nx-card td-timeline-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span class="nx-label" style="margin:0">MARKET HOURS</span>
        <span style="font-size:11px;color:var(--nx-text-3)">{{currentTimeLabel}}</span>
      </div>
      <div class="td-timeline-track">
        <div class="td-timeline-progress" [style.width.%]="timelineProgress"></div>
      </div>
      <div class="td-timeline-steps">
        <div *ngFor="let step of timeline" [class]="step.status">
          <strong>{{step.time}}</strong>
          <span>{{step.label}}</span>
        </div>
      </div>
    </div>

    <!-- ─── SNAPSHOT ROW ─── -->
    <div class="td-snapshot-row">
      <div class="nx-card">
        <span class="nx-label">DESK SNAPSHOT</span>
        <div class="td-cockpit-grid">
          <div *ngFor="let item of snapshotItems" class="td-kv-row">
            <span class="td-kv-label">{{item.label}}</span>
            <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
          </div>
        </div>
      </div>

      <div class="nx-card">
        <span class="nx-label">LIVE PAPER</span>
        <div class="td-cockpit-grid">
          <div *ngFor="let item of paperItems" class="td-kv-row">
            <span class="td-kv-label">{{item.label}}</span>
            <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
          </div>
        </div>
      </div>

      <div class="nx-card">
        <span class="nx-label">OPTION CHAIN</span>
        <div class="td-cockpit-grid">
          <div *ngFor="let item of chainSummaryItems" class="td-kv-row">
            <span class="td-kv-label">{{item.label}}</span>
            <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
          </div>
        </div>
      </div>

      <div class="nx-card">
        <span class="nx-label">MARKET FLOW</span>
        <div class="td-cockpit-grid">
          <div *ngFor="let item of flowItems" class="td-kv-row">
            <span class="td-kv-label">{{item.label}}</span>
            <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ─── PAPER TIMELINE TABLE ─── -->
    <div class="nx-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="nx-label" style="margin:0">PAPER TIMELINE</span>
        <span class="nx-chip nx-chip-paper">PAPER ONLY</span>
      </div>

      <div *ngIf="!closedTrades?.length && !openTrades?.length"
           style="text-align:center;padding:20px;color:var(--nx-text-3);font-size:13px">
        No paper trade events yet today
      </div>

      <table *ngIf="allTrades.length" class="nx-table" style="text-align:left">
        <thead>
          <tr>
            <th>SYMBOL</th>
            <th>TYPE</th>
            <th style="text-align:right">ENTRY</th>
            <th style="text-align:right">EXIT</th>
            <th style="text-align:right">P&L ₹</th>
            <th>REASON</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let t of allTrades.slice(0, 8)">
            <td style="font-weight:500;color:var(--nx-text-1)">
              {{t.symbol}}
            </td>
            <td>
              <span class="nx-chip"
                    [ngClass]="t.type?.includes('CALL') ? 'nx-chip-ok' : 'nx-chip-fail'">
                {{t.type || '—'}}
              </span>
            </td>
            <td style="text-align:right;color:var(--nx-text-2)">
              {{t.entry | number:'1.0-2'}}
            </td>
            <td style="text-align:right;color:var(--nx-text-2)">
              {{t.exit ? (t.exit | number:'1.0-2') : '—'}}
            </td>
            <td style="text-align:right;font-weight:600"
                [class]="(t.pnl || 0) >= 0 ? 'c-success' : 'c-danger'">
              {{(t.pnl||0) >= 0 ? '+' : ''}}{{t.pnl | number:'1.0-2'}}
            </td>
            <td style="color:var(--nx-text-3)">{{t.reason || '—'}}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ─── OPTION CHAIN TABLE ─── -->
    <div class="nx-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="nx-label" style="margin:0">NEARBY OPTION STRIKES</span>
        <span class="nx-chip nx-chip-info">
          {{nearbyStrikes.length ? nearbyStrikes.length + ' strikes' : 'NO DATA'}}
        </span>
      </div>

      <div *ngIf="!nearbyStrikes.length"
           style="text-align:center;padding:20px;color:var(--nx-text-3);font-size:13px">
        No nearby option strikes available
      </div>

      <div *ngIf="nearbyStrikes.length" class="td-chain-wrap">
        <table class="td-chain-table">
          <thead>
            <tr>
              <th colspan="3" class="td-chain-header-call">CALLS</th>
              <th>STRIKE</th>
              <th colspan="3" class="td-chain-header-put">PUTS</th>
            </tr>
            <tr>
              <th>OI</th><th>LTP</th><th>Vol</th>
              <th></th>
              <th>LTP</th><th>OI</th><th>Vol</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let row of nearbyStrikes.slice(0, 10)"
                [class.td-atm]="row.atm">
              <td [style.background]="heatColor(row.ceOi, maxCeOi, 'call')">
                {{row.ceOi || '-'}}
              </td>
              <td class="td-chain-ltp call">{{row.ceLtp || '-'}}</td>
              <td [style.background]="heatColor(row.ceVol, maxCeVol, 'call')">
                {{row.ceVol || '-'}}
              </td>
              <td class="td-chain-strike">
                {{row.strike}}
                <small *ngIf="row.atm" class="td-atm-badge">ATM</small>
              </td>
              <td class="td-chain-ltp put">{{row.peLtp || '-'}}</td>
              <td [style.background]="heatColor(row.peOi, maxPeOi, 'put')">
                {{row.peOi || '-'}}
              </td>
              <td [style.background]="heatColor(row.peVol, maxPeVol, 'put')">
                {{row.peVol || '-'}}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ─── SAFETY + WARNINGS ─── -->
    <div class="td-footer-row">
      <div class="nx-card">
        <span class="nx-label">SAFETY</span>
        <div class="td-cockpit-grid">
          <div *ngFor="let item of safetyItems" class="td-kv-row">
            <span class="td-kv-label">{{item.label}}</span>
            <span class="td-kv-value" [ngClass]="'c-' + item.tone">{{item.value}}</span>
          </div>
        </div>
        <p class="td-panel-note">
          This page has no execution controls. It only reads backend paper-analysis endpoints.
        </p>
      </div>

      <div class="nx-card" style="grid-column: span 2">
        <span class="nx-label">DESK WARNINGS</span>
        <div *ngIf="!allWarnings.length"
             style="font-size:12px;color:var(--nx-text-3);padding:8px 0">
          No desk warnings reported
        </div>
        <div *ngFor="let w of allWarnings.slice(0, 8)"
             style="display:flex;align-items:flex-start;gap:8px;padding:5px 0;
                    border-bottom:0.5px solid var(--nx-border)">
          <mat-icon style="font-size:14px;width:14px;height:14px;color:var(--nx-warning);margin-top:2px">
            warning
          </mat-icon>
          <span style="font-size:12px;color:var(--nx-text-2)">{{w}}</span>
        </div>
        <p class="td-panel-note">
          Updated <strong style="font-family:monospace">{{lastUpdated}}</strong>
        </p>
      </div>
    </div>

  </ng-container>

</div>
  `,
  styles: [`
    /* ─── ROOT ─── */
    .td-root {
      max-width: 1500px;
      margin: 0 auto;
      display: grid;
      gap: 12px;
    }

    /* ─── HEADER ─── */
    .td-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .td-eyebrow {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: .1em;
      color: var(--nx-accent);
    }
    .td-title {
      font-size: 20px;
      font-weight: 600;
      color: var(--nx-text-1);
      margin: 2px 0 0;
    }
    .td-subtitle {
      font-size: 12px;
      color: var(--nx-text-3);
      margin: 2px 0 0;
    }
    .td-header-right {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .td-refresh-btn {
      font-size: 12px;
      color: var(--nx-text-2);
    }
    .td-loading {
      text-align: center;
      padding: 40px !important;
    }

    /* ─── PRO: HERO ─── */
    .td-hero {
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(300px, 0.4fr);
      gap: 12px;
      align-items: stretch;
    }

    /* Chart card */
    .td-chart-card { padding: 12px !important; }
    .td-chart-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .td-overlay-group {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .td-overlay-group button {
      font-size: 11px;
      color: var(--nx-text-3);
      border-color: var(--nx-border);
      min-height: 28px;
      padding: 2px 8px;
    }
    .td-overlay-active {
      color: var(--nx-accent) !important;
      border-color: var(--nx-accent) !important;
    }
    .td-chart-info {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 6px 8px;
      background: var(--nx-bg-raised);
      border-radius: 6px;
      margin-bottom: 8px;
    }
    .td-chart-symbol {
      display: flex;
      align-items: baseline;
      gap: 8px;
    }
    .td-chart-symbol span {
      font-size: 13px;
      font-weight: 700;
      color: var(--nx-accent);
      letter-spacing: .06em;
    }
    .td-chart-symbol strong {
      font-size: 18px;
      font-weight: 700;
      color: var(--nx-text-1);
      font-family: monospace;
    }
    .td-chart-ohlc {
      display: flex;
      gap: 12px;
      font-size: 11px;
      color: var(--nx-text-3);
      font-weight: 600;
      text-transform: uppercase;
    }
    .td-chart-ohlc strong { font-family: monospace; }
    .td-chart-canvas {
      position: relative;
      border-radius: 8px;
      overflow: hidden;
      background: #0b1220;
    }
    .td-echart-host {
      width: 100%;
      height: clamp(380px, 42vh, 540px);
    }
    .td-chart-empty {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      color: var(--nx-text-3);
      font-size: 13px;
      pointer-events: none;
    }

    /* Cockpit side */
    .td-cockpit-stack {
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .td-cockpit { overflow: hidden; }
    .td-verdict {
      display: grid;
      gap: 4px;
      margin-top: 8px;
      padding: 12px;
      border-radius: 8px;
      border: 0.5px solid rgba(245, 158, 11, .5);
      background: rgba(245, 158, 11, .05);
      margin-bottom: 10px;
    }
    .td-verdict.can {
      border-color: rgba(16, 185, 129, .5);
      background: rgba(16, 185, 129, .06);
    }
    .td-verdict span,
    .td-verdict small {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: var(--nx-text-3);
    }
    .td-verdict strong {
      font-size: 22px;
      font-weight: 800;
      font-family: monospace;
    }
    .td-cockpit-grid {
      display: grid;
      gap: 0;
    }
    .td-kv-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 0;
      border-bottom: 0.5px solid var(--nx-border);
    }
    .td-kv-row:last-child { border-bottom: none; }
    .td-kv-label {
      font-size: 11px;
      color: var(--nx-text-3);
      font-weight: 500;
    }
    .td-kv-value {
      font-size: 12px;
      font-weight: 600;
      font-family: monospace;
      text-align: right;
    }
    .c-good, .c-success { color: var(--nx-success); }
    .c-bad, .c-danger   { color: var(--nx-danger);  }
    .c-warn, .c-warning { color: var(--nx-warning); }
    .c-info     { color: var(--nx-cyan);    }
    .c-neutral  { color: var(--nx-text-2);  }

    /* ─── TIMELINE ─── */
    .td-timeline-card { padding: 12px 16px !important; }
    .td-timeline-track {
      height: 5px;
      background: var(--nx-border);
      border-radius: 3px;
      overflow: hidden;
      margin-bottom: 10px;
    }
    .td-timeline-progress {
      height: 100%;
      border-radius: 3px;
      background: linear-gradient(90deg, var(--nx-success), var(--nx-warning));
      transition: width .4s ease;
    }
    .td-timeline-steps {
      display: grid;
      grid-template-columns: repeat(6, minmax(60px, 1fr));
      gap: 6px;
    }
    .td-timeline-steps div {
      padding: 6px;
      background: var(--nx-bg-raised);
      border-radius: 6px;
      border: 0.5px solid var(--nx-border);
    }
    .td-timeline-steps .past { opacity: .55; }
    .td-timeline-steps .active {
      border-color: var(--nx-accent);
      background: rgba(99, 102, 241, .08);
      box-shadow: inset 0 2px 0 var(--nx-accent);
    }
    .td-timeline-steps strong {
      display: block;
      font-size: 12px;
      color: var(--nx-text-1);
      font-family: monospace;
    }
    .td-timeline-steps span {
      display: block;
      font-size: 9px;
      font-weight: 600;
      text-transform: uppercase;
      color: var(--nx-text-3);
      margin-top: 2px;
    }

    /* ─── SNAPSHOT ROW ─── */
    .td-snapshot-row {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    /* ─── CHAIN TABLE ─── */
    .td-chain-wrap {
      overflow-x: auto;
      border-radius: 8px;
      border: 0.5px solid var(--nx-border);
    }
    .td-chain-table {
      width: 100%;
      min-width: 600px;
      border-collapse: collapse;
      font-size: 11px;
      font-family: monospace;
    }
    .td-chain-table th,
    .td-chain-table td {
      padding: 5px 8px;
      border-bottom: 0.5px solid var(--nx-border);
      text-align: right;
      white-space: nowrap;
    }
    .td-chain-table th {
      font-size: 10px;
      font-weight: 600;
      color: var(--nx-text-3);
      letter-spacing: .06em;
      background: var(--nx-bg-raised);
    }
    .td-chain-header-call { text-align: center; color: var(--nx-success) !important; }
    .td-chain-header-put  { text-align: center; color: var(--nx-danger) !important;  }
    .td-chain-ltp {
      font-weight: 700;
      text-align: center;
    }
    .td-chain-ltp.call { color: var(--nx-success); }
    .td-chain-ltp.put  { color: var(--nx-danger);  }
    .td-chain-strike {
      text-align: center !important;
      font-weight: 700;
      color: var(--nx-text-1);
      border-left: 0.5px solid var(--nx-border);
      border-right: 0.5px solid var(--nx-border);
      background: var(--nx-bg-raised) !important;
    }
    .td-atm td {
      box-shadow: inset 0 1px 0 var(--nx-accent), inset 0 -1px 0 var(--nx-accent);
    }
    .td-atm-badge {
      display: block;
      font-size: 8px;
      color: var(--nx-accent);
      font-weight: 700;
      letter-spacing: .08em;
    }

    /* ─── FOOTER ROW ─── */
    .td-footer-row {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) 1fr 1fr;
      gap: 12px;
    }
    .td-panel-note {
      margin-top: 10px;
      padding-top: 8px;
      border-top: 0.5px solid var(--nx-border);
      font-size: 11px;
      color: var(--nx-text-3);
    }

    /* ─── RESPONSIVE ─── */
    @media (max-width: 1200px) {
      .td-hero { grid-template-columns: 1fr; }
      .td-snapshot-row { grid-template-columns: repeat(2, 1fr); }
      .td-footer-row { grid-template-columns: 1fr; }
      .td-footer-row .nx-card { grid-column: auto !important; }
    }
    @media (max-width: 760px) {
      .td-header { display: grid; }
      .td-snapshot-row { grid-template-columns: 1fr; }
      .td-timeline-steps { grid-template-columns: repeat(3, 1fr); }
    }
  `],
})
export class DashboardComponent implements OnInit, OnDestroy {

  /* ─── State ─── */
  vm: any = null;
  perf: any = null;
  closedTrades: any[] = [];
  openTrades: any[] = [];
  candles: any[] = [];
  latestCandle: any = null;
  nearbyStrikes: any[] = [];
  flowData: any = null;
  strategyData: any = null;
  sessionData: any = null;
  pivotLevels: any = {};
  allWarnings: string[] = [];

  /* ─── UI ─── */
  loading = true;
  loadError = false;

  selectedTf: Tf = '5m';
  timeframes: Tf[] = ['1m', '3m', '5m', '15m'];
  lastUpdated = 'never';
  showMarkers = true;
  showLevels = true;
  showSignals = true;
  showVolume = true;

  /* ─── ECharts ─── */
  chartOptions: any = {};
  chartMerge: any = {};
  scoreGauge: any = {};
  private echartInstance: any = null;

  private sub?: Subscription;
  private tfSubject = new BehaviorSubject<Tf>('5m');
  private refreshSubject = new BehaviorSubject<void>(undefined);

  constructor(private http: HttpClient) {}

  /* ─── Lifecycle ─── */
  ngOnInit() {
    this.sub = combineLatest([
      this.tfSubject,
      this.refreshSubject.pipe(
        switchMap(() => interval(45000).pipe(startWith(0)))
      ),
    ]).pipe(
      switchMap(([tf]) => this.loadAll(tf)),
    ).subscribe(data => this.apply(data));
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  /* ─── Actions ─── */
  refresh() { this.refreshSubject.next(); }

  onTfChange(tf: Tf) {
    this.selectedTf = tf;
    this.tfSubject.next(tf);
  }

  onChartInit(ec: any) {
    this.echartInstance = ec;
  }

  /* ─── Data loading ─── */
  private loadAll(tf: Tf) {
    return forkJoin({
      signal: this.safeGet('/api/signals-v2/latest', this.emptySignal()),
      perf: this.safeGet('/api/live-paper/performance', {}),
      open: this.safeGet('/api/live-paper/open-trades', []),
      closed: this.safeGet('/api/live-paper/closed-trades', []),
      candles: this.safeGet(
        `/api/live-monitor/candles/NIFTY?timeframe=${tf}&limit=200`,
        { ok: false, status: 'NO_CANDLE', items: [] }
      ),
      chain: this.safeGet('/api/option-chain/nearby', []),
      flow: this.safeGet('/api/market-flow/summary', {}),
      strategy: this.safeGet('/api/strategy-evaluation/health-score', {}),
      session: this.safeGet('/api/session-gate/status', {}),
    });
  }

  private safeGet<T>(path: string, fallback: T) {
    return this.http.get<T>(path).pipe(
      timeout(8000),
      retry({ count: 1, delay: 750 }),
      catchError(() => of(fallback))
    );
  }

  private emptySignal() {
    return {
      decision: 'NO_TRADE',
      score: 0,
      required_score: 70,
      confidence: 'LOW',
      trend_status: 'UNKNOWN',
      market_flow_bias: 'UNKNOWN',
      chain_bias: 'UNKNOWN',
      warnings: ['Signal endpoint unavailable. Showing partial desk data.'],
      trading_mode: 'PAPER',
      live_order_status: 'BLOCKED',
    };
  }

  private apply(data: any) {
    this.loading = false;
    this.loadError = !data.signal;

    // Signal
    const raw = data.signal?.items?.[0] ?? data.signal?.signals?.[0] ?? data.signal;
    this.vm = this.normalizeSignal(raw);

    // Performance
    this.perf = data.perf ?? {};

    // Trades
    this.openTrades = this.normalizeTrades(data.open);
    this.closedTrades = this.normalizeTrades(data.closed);

    // Candles
    const rawCandles = data.candles?.candles ?? data.candles?.items ?? data.candles ?? [];
    this.candles = this.parseCandles(rawCandles);
    this.latestCandle = this.candles.at(-1) ?? null;
    this.pivotLevels = this.calculatePivots(this.candles);

    // Chain
    this.nearbyStrikes = this.normalizeChain(data.chain);

    // Flow
    this.flowData = data.flow ?? {};

    // Strategy
    this.strategyData = data.strategy ?? {};

    // Session
    this.sessionData = data.session ?? {};

    // Warnings
    this.allWarnings = [
      ...(this.vm?.warnings ?? []),
      ...(this.flowData?.warnings ?? []),
      ...(this.strategyData?.warnings ?? []),
    ].filter(Boolean).map((w: any) => typeof w === 'string' ? w : JSON.stringify(w));

    // Charts
    this.buildChart();
    this.buildGauge(this.num(this.vm?.score) ?? 0);

    this.lastUpdated = new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }

  /* ─── Normalize helpers ─── */
  private normalizeSignal(s: any): any {
    if (!s || typeof s !== 'object') return null;
    const ms = s.market_state ?? {};
    return {
      ...s,
      decision: s.decision ?? s.signal_type ?? s.action ?? 'NO_TRADE',
      score: this.num(s.score ?? s.signal_score) ?? 0,
      required_score: this.num(s.required_score) ?? 70,
      confidence: s.confidence ?? 'LOW',
      selected_strike: s.selected_strike ?? s.selected_option?.strike ?? s.strike ?? null,
      option_type: s.option_type ?? (s.decision === 'BUY_CALL' ? 'CE' : s.decision === 'BUY_PUT' ? 'PE' : ''),
      trend_status: s.trend_status ?? s.trend ?? 'UNKNOWN',
      market_flow_bias: s.market_flow_bias ?? s.market_flow_status ?? 'UNKNOWN',
      chain_bias: s.chain_bias ?? 'UNKNOWN',
      reasons: this.toStrArr(s.reasons ?? s.rejection_reasons ?? s.failed_checks),
      warnings: this.toStrArr(s.warnings),
      market_state: {
        ...ms,
        time_gate: {
          ...(ms.time_gate ?? {}),
          allowed: s.session_allows_paper_entry === true
            || s.session_allows_new_signal === true
            || ms.time_gate?.allowed === true,
          window_name: ms.time_gate?.window_name ?? ms.session_status ?? 'UNKNOWN',
        },
      },
      trading_mode: s.trading_mode ?? 'PAPER',
      live_order_status: s.live_order_status ?? 'BLOCKED',
      broker_execution_disabled: s.broker_execution_disabled !== false,
      safety_ok: s.safety_ok !== false,
      data_quality: s.data_quality_status ?? ms.data_quality ?? 'UNKNOWN',
    };
  }

  private normalizeTrades(data: any): any[] {
    const arr = data?.items ?? data?.trades ?? [];
    return (Array.isArray(arr) ? arr : []).map((t: any) => ({
      symbol: t.optionSymbol ?? t.option_symbol ?? t.symbol ?? '-',
      type: t.signalType ?? t.signal_type ?? t.side ?? '-',
      entry: Number(t.entryPrice ?? t.entry_price ?? 0),
      exit: t.exitPrice != null || t.exit_price != null
        ? Number(t.exitPrice ?? t.exit_price ?? 0) : null,
      pnl: Number(t.realizedPnl ?? t.realized_pnl ?? t.pnl ?? 0),
      reason: t.exitReason ?? t.exit_reason ?? t.reason ?? '',
      time: t.entryTime ?? t.entry_time ?? t.time ?? '',
    })).slice(0, 10);
  }

  private normalizeChain(data: any): any[] {
    const arr = data?.items ?? data?.strikes ?? data?.nearby_strikes ?? data ?? [];
    return (Array.isArray(arr) ? arr : []).map((r: any) => ({
      strike: r.strike ?? r.strike_price ?? '-',
      ceLtp: r.ce_ltp ?? r.ceLtp ?? r.call_ltp ?? '',
      ceOi: r.ce_oi ?? r.ceOi ?? r.call_oi ?? '',
      ceVol: r.ce_volume ?? r.ceVolume ?? r.call_volume ?? '',
      peLtp: r.pe_ltp ?? r.peLtp ?? r.put_ltp ?? '',
      peOi: r.pe_oi ?? r.peOi ?? r.put_oi ?? '',
      peVol: r.pe_volume ?? r.peVolume ?? r.put_volume ?? '',
      atm: r.atm_marker === 'ATM' || r.atmMarker === 'ATM' || r.is_atm === true,
    }));
  }

  /* ─── Candle parsing ─── */
  private parseCandles(raw: any[]): any[] {
    return (Array.isArray(raw) ? raw : [])
      .filter((c: any) => c && (c.time || c.timestamp || c.open_time || c.start_time))
      .map((c: any) => {
        let time = c.time ?? c.timestamp ?? c.open_time ?? c.start_time;
        if (typeof time === 'string') {
          time = new Date(time).toLocaleTimeString('en-IN', {
            timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false,
          });
        }
        return {
          time,
          open: Number(c.open ?? c.o ?? 0),
          high: Number(c.high ?? c.h ?? 0),
          low: Number(c.low ?? c.l ?? 0),
          close: Number(c.close ?? c.c ?? 0),
          volume: Number(c.volume ?? c.v ?? 0),
          tickCount: Number(c.tick_count ?? c.tickCount ?? 0),
        };
      })
      .filter((c: any) => c.open > 0 && c.high > 0 && c.low > 0 && c.close > 0);
  }

  private calculatePivots(candles: any[]) {
    if (!candles.length) return {};
    const last = candles.at(-2) ?? candles.at(-1)!;
    const h = Number(last.high), l = Number(last.low), c = Number(last.close);
    const p = (h + l + c) / 3;
    const round = (v: number) => Math.round(v * 100) / 100;
    return {
      p: round(p), r1: round(2 * p - l), s1: round(2 * p - h),
      r2: round(p + (h - l)), s2: round(p - (h - l)),
    };
  }

  /* ─── ECharts builders ─── */
  buildChart() {
    if (!this.candles.length) {
      this.chartOptions = { backgroundColor: 'transparent' };
      return;
    }

    const labels = this.candles.map((c: any) => c.time);
    const ohlc = this.candles.map((c: any) => [c.open, c.close, c.low, c.high]);
    const volumes = this.candles.map((c: any) => ({
      value: this.showVolume ? Math.round(c.volume || c.tickCount || 0) : 0,
      itemStyle: {
        color: c.close >= c.open ? 'rgba(16,185,129,.4)' : 'rgba(239,68,68,.4)',
      },
    }));

    const markLineData: any[] = [];
    if (this.showLevels && this.pivotLevels.p) {
      const lines = [
        { price: this.pivotLevels.p, label: 'P', color: '#06b6d4' },
        { price: this.pivotLevels.s1, label: 'S1', color: '#10b981' },
        { price: this.pivotLevels.r1, label: 'R1', color: '#ef4444' },
        { price: this.pivotLevels.s2, label: 'S2', color: '#10b981' },
        { price: this.pivotLevels.r2, label: 'R2', color: '#ef4444' },
      ];
      for (const line of lines) {
        if (!line.price) continue;
        markLineData.push({
          yAxis: line.price, name: line.label,
          lineStyle: { color: line.color, width: 1, type: 'dashed' },
          label: { show: true, position: 'end', color: line.color, fontSize: 10,
                   formatter: `${line.label} ${line.price}` },
        });
      }
    }

    const markPointData: any[] = [];
    if (this.showSignals && this.vm && labels.length) {
      const decision = this.vm.decision || 'NO_TRADE';
      const isPut = decision.includes('PUT');
      const isNo = decision.includes('NO');
      const idx = labels.length - 1;
      markPointData.push({
        coord: [labels[idx], ohlc[idx]?.[isPut ? 3 : 2] ?? 0],
        value: decision.includes('CALL') ? 'BUY CE' : isPut ? 'BUY PE' : 'NO TRADE',
        symbol: isPut ? 'pin' : 'triangle',
        symbolRotate: isPut ? 180 : 0,
        symbolSize: 28,
        itemStyle: { color: isNo ? '#f59e0b' : isPut ? '#ef4444' : '#10b981' },
        label: { color: '#0b1220', fontSize: 9, fontWeight: 900 },
      });
    }

    if (this.showMarkers) {
      for (const t of this.allTrades.slice(-12)) {
        const isEntry = !t.exit;
        const isLoss = String(t.reason).toUpperCase().includes('LOSS');
        const idx = Math.max(0, labels.length - 1);
        markPointData.push({
          coord: [labels[idx], ohlc[idx]?.[isEntry ? 2 : 3] ?? 0],
          value: isEntry ? 'E' : isLoss ? 'SL' : 'T',
          symbol: isEntry ? 'triangle' : 'pin',
          symbolRotate: isEntry ? 0 : 180,
          symbolSize: 24,
          itemStyle: { color: isEntry ? '#10b981' : isLoss ? '#ef4444' : '#f59e0b' },
          label: { color: '#0b1220', fontSize: 8, fontWeight: 900 },
        });
      }
    }

    this.chartOptions = {
      backgroundColor: 'transparent',
      animation: false,
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 58, right: 78, top: 42, height: '62%' },
        { left: 58, right: 78, top: '76%', height: '14%' },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(10,15,30,.94)',
        borderColor: '#1e293b',
        borderWidth: 1,
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        formatter: (params: any[]) => {
          const c = params.find((p: any) => p.seriesName === 'NIFTY');
          if (!c) return '';
          const [o, cl, l, h] = c.value ?? [];
          const change = Number(cl ?? 0) - Number(o ?? 0);
          const color = change >= 0 ? '#10b981' : '#ef4444';
          return [
            `<b>${c.axisValue}</b>`,
            `O ${this.fmtNum(o)} H ${this.fmtNum(h)}`,
            `L ${this.fmtNum(l)} C <b>${this.fmtNum(cl)}</b>`,
            `<span style="color:${color}">${change >= 0 ? '+' : ''}${change.toFixed(2)}</span>`,
          ].join('<br/>');
        },
      },
      xAxis: [
        { type: 'category', data: labels, gridIndex: 0, boundaryGap: true,
          axisLabel: { show: false }, axisLine: { lineStyle: { color: '#1e293b' } },
          axisTick: { show: false } },
        { type: 'category', data: labels, gridIndex: 1, boundaryGap: true,
          axisLabel: { color: '#64748b', fontSize: 10,
                       interval: Math.max(1, Math.floor(labels.length / 8)) },
          axisLine: { lineStyle: { color: '#1e293b' } },
          axisTick: { show: false } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, position: 'right',
          axisLabel: { color: '#64748b', fontSize: 10,
                       formatter: (v: number) => v.toFixed(0) },
          splitLine: { lineStyle: { color: 'rgba(30,41,59,.6)' } },
          axisLine: { show: false } },
        { scale: true, gridIndex: 1, position: 'right',
          axisLabel: { color: '#475569', fontSize: 9,
                       formatter: (v: number) => this.fmtVol(v) },
          splitLine: { show: false },
          axisLine: { show: false } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1],
          start: Math.max(0, 100 - (70 / Math.max(labels.length, 1)) * 100), end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 16,
          borderColor: '#1e293b', fillerColor: 'rgba(99,102,241,.12)',
          handleStyle: { color: '#6366f1' },
          textStyle: { color: '#64748b', fontSize: 9 } },
      ],
      series: [
        {
          name: 'NIFTY', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
          data: ohlc,
          itemStyle: {
            color: '#10b981', color0: '#ef4444',
            borderColor: '#10b981', borderColor0: '#ef4444',
          },
          markLine: markLineData.length ? { symbol: 'none', data: markLineData, silent: true } : undefined,
          markPoint: markPointData.length ? { data: markPointData } : undefined,
        },
        {
          name: 'Volume', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
          data: volumes, barMaxWidth: 9,
        },
      ],
    };
  }

  private buildGauge(score: number) {
    this.scoreGauge = {
      backgroundColor: 'transparent',
      series: [{
        type: 'gauge', min: 0, max: 100, splitNumber: 5,
        axisLine: {
          lineStyle: {
            width: 14,
            color: [[0.50, '#ef4444'], [0.70, '#f59e0b'], [1.00, '#10b981']],
          },
        },
        pointer: { itemStyle: { color: 'inherit' }, length: '55%', width: 4 },
        axisTick: { show: false },
        splitLine: { length: 8, lineStyle: { color: 'inherit', width: 2 } },
        axisLabel: {
          color: '#64748b', fontSize: 9,
          formatter: (v: number) => v === 0 ? '0' : v === 70 ? '70*' : v === 100 ? '100' : '',
        },
        detail: {
          valueAnimation: true, fontSize: 22, fontWeight: 700, color: 'inherit',
          offsetCenter: [0, '40%'], formatter: '{value}',
        },
        data: [{ value: score, name: '' }],
      }],
    };
  }

  /* ─── Computed getters ─── */
  get tradingMode(): string { return this.vm?.trading_mode ?? 'PAPER'; }
  get safetyOk(): boolean { return this.vm?.safety_ok !== false; }
  get latestPrice(): string {
    return this.latestCandle?.close ? Number(this.latestCandle.close).toFixed(2) : '';
  }

  get allTrades(): any[] {
    return [...this.openTrades, ...this.closedTrades].slice(0, 10);
  }

  get decisionColor(): string {
    const d = this.vm?.decision ?? '';
    if (d.includes('CALL')) return 'var(--nx-success)';
    if (d.includes('PUT')) return 'var(--nx-danger)';
    return 'var(--nx-text-3)';
  }

  get cockpitStatus(): string {
    if (!this.vm) return 'CANNOT_TRADE';
    const d = this.vm.decision ?? '';
    const score = this.num(this.vm.score) ?? 0;
    const req = this.num(this.vm.required_score) ?? 70;
    const hasOpt = this.vm.selected_strike && this.vm.selected_strike !== '-';
    const noReject = !(this.vm.reasons?.length);
    return (d.includes('CALL') || d.includes('PUT'))
      && score >= req && hasOpt && noReject
      ? 'CAN_TRADE' : 'CANNOT_TRADE';
  }

  get cockpitItems(): KVItem[] {
    if (!this.vm) return [];
    const ms = this.vm.market_state ?? {};
    return [
      { label: 'Direction', value: this.vm.decision ?? 'NO_TRADE', tone: this.vm.decision?.includes('NO') ? 'warn' : 'info' },
      { label: 'Score', value: `${this.vm.score ?? 0} / ${this.vm.required_score ?? 70}`, tone: 'info' },
      { label: 'Confidence', value: this.vm.confidence ?? '-', tone: this.vm.confidence === 'HIGH' ? 'good' : 'neutral' },
      { label: 'Selected Option', value: this.vm.selected_strike ?? '-', tone: this.vm.selected_strike ? 'good' : 'warn' },
      { label: 'Trend', value: this.vm.trend_status ?? 'UNKNOWN', tone: this.toneOf(this.vm.trend_status) },
      { label: 'Time Window', value: ms.time_gate?.window_name ?? 'UNKNOWN', tone: ms.time_gate?.allowed ? 'good' : 'warn' },
    ];
  }

  get noTradeItems(): KVItem[] {
    if (!this.vm) return [];
    const reasons = this.vm.reasons ?? [];
    return [
      { label: 'Blocked by', value: reasons[0] ?? 'None', tone: reasons.length ? 'bad' : 'good' },
      { label: 'Signal score', value: `${this.vm.score ?? 0} / ${this.vm.required_score ?? 70}`,
        tone: (this.num(this.vm.score) ?? 0) >= (this.num(this.vm.required_score) ?? 70) ? 'good' : 'warn' },
      { label: 'Data quality', value: this.vm.data_quality ?? 'UNKNOWN', tone: this.toneOf(this.vm.data_quality) },
    ];
  }

  get snapshotItems(): KVItem[] {
    return [
      { label: 'Live Paper', value: this.perf?.status ?? 'UNKNOWN', tone: this.toneOf(this.perf?.status) },
      { label: 'Open Trades', value: String(this.openTrades.length), tone: this.openTrades.length ? 'warn' : 'good' },
      { label: 'Total P&L', value: `₹${(this.num(this.perf?.total_pnl) ?? 0).toFixed(0)}`,
        tone: (this.num(this.perf?.total_pnl) ?? 0) >= 0 ? 'good' : 'bad' },
      { label: 'Strategy Health', value: this.strategyData?.health?.label ?? this.strategyData?.status ?? 'UNKNOWN',
        tone: this.toneOf(this.strategyData?.health?.label ?? this.strategyData?.status) },
      { label: 'Flow Bias', value: this.flowData?.bias ?? this.flowData?.market_flow_bias ?? 'UNKNOWN',
        tone: this.biasTone(this.flowData?.bias ?? this.flowData?.market_flow_bias) },
      { label: 'Chain Bias', value: this.vm?.chain_bias ?? 'UNKNOWN',
        tone: this.biasTone(this.vm?.chain_bias) },
    ];
  }

  get paperItems(): KVItem[] {
    const w = this.num(this.perf?.winning_trades ?? this.perf?.wins) ?? 0;
    const l = this.num(this.perf?.losing_trades ?? this.perf?.losses) ?? 0;
    const wr = w + l > 0 ? Math.round(w / (w + l) * 100) : 0;
    return [
      { label: 'Total P&L', value: `₹${(this.num(this.perf?.total_pnl) ?? 0).toFixed(0)}`,
        tone: (this.num(this.perf?.total_pnl) ?? 0) >= 0 ? 'good' : 'bad' },
      { label: 'Win Rate', value: `${wr}%`, tone: wr >= 50 ? 'good' : 'warn' },
      { label: 'Wins / Losses', value: `${w}W ${l}L`, tone: 'neutral' },
      { label: 'Total Trades', value: String(this.num(this.perf?.total_trades) ?? w + l), tone: 'info' },
    ];
  }

  get chainSummaryItems(): KVItem[] {
    return [
      { label: 'Chain Bias', value: this.vm?.chain_bias ?? 'NO DATA',
        tone: this.biasTone(this.vm?.chain_bias) },
      { label: 'PCR', value: String(this.vm?.pcr ?? this.vm?.pcr_oi ?? '-'), tone: 'info' },
      { label: 'Nearby Strikes', value: String(this.nearbyStrikes.length), tone: this.nearbyStrikes.length ? 'good' : 'warn' },
    ];
  }

  get flowItems(): KVItem[] {
    return [
      { label: 'Flow Bias', value: this.flowData?.bias ?? this.flowData?.market_flow_bias ?? 'UNKNOWN',
        tone: this.biasTone(this.flowData?.bias ?? this.flowData?.market_flow_bias) },
      { label: 'Trap Risk', value: this.flowData?.trap_risk ?? 'UNKNOWN', tone: this.riskTone(this.flowData?.trap_risk) },
      { label: 'Strength', value: this.flowData?.strength ?? '-', tone: 'neutral' },
    ];
  }

  get safetyItems(): KVItem[] {
    return [
      { label: 'PAPER MODE', value: this.tradingMode, tone: this.tradingMode === 'PAPER' ? 'good' : 'bad' },
      { label: 'LIVE ORDERS', value: this.vm?.live_order_status ?? 'BLOCKED', tone: 'good' },
      { label: 'BROKER EXEC', value: this.vm?.broker_execution_disabled ? 'DISABLED' : 'CHECK',
        tone: this.vm?.broker_execution_disabled ? 'good' : 'bad' },
    ];
  }

  /* ─── Option chain max values for heatmap ─── */
  get maxCeOi(): number { return this.maxVal(this.nearbyStrikes, 'ceOi'); }
  get maxPeOi(): number { return this.maxVal(this.nearbyStrikes, 'peOi'); }
  get maxCeVol(): number { return this.maxVal(this.nearbyStrikes, 'ceVol'); }
  get maxPeVol(): number { return this.maxVal(this.nearbyStrikes, 'peVol'); }

  heatColor(value: any, max: number, side: 'call' | 'put'): string {
    const n = Number(String(value).replace(/,/g, ''));
    if (!n || !max) return 'transparent';
    const strength = Math.max(0.08, Math.min(1, n / max));
    const alpha = 0.06 + strength * 0.22;
    return side === 'call'
      ? `rgba(16, 185, 129, ${alpha})`
      : `rgba(239, 68, 68, ${alpha})`;
  }

  /* ─── Market timeline ─── */
  get timeline(): TimelineStep[] {
    const nowStr = this.sessionNowTime();
    const now = this.minutesFromTime(nowStr);
    const items = [
      { label: 'Open', time: '09:15' },
      { label: 'First trade', time: '09:20' },
      { label: 'Late session', time: '14:45' },
      { label: 'No new trades', time: '15:05' },
      { label: 'Square-off', time: '15:20' },
      { label: 'Close', time: '15:30' },
    ];
    return items.map((item, i) => {
      const current = this.minutesFromTime(item.time);
      const next = i < items.length - 1 ? this.minutesFromTime(items[i + 1].time) : Infinity;
      const status: TimelineStep['status'] =
        now >= current && now < next ? 'active' : now >= next ? 'past' : 'future';
      return { ...item, status };
    });
  }

  get timelineProgress(): number {
    const now = this.minutesFromTime(this.sessionNowTime());
    return Math.max(0, Math.min(100, (now - 555) / (930 - 555) * 100));
  }

  get currentTimeLabel(): string {
    const active = this.timeline.find(s => s.status === 'active');
    return active ? `${active.time} ${active.label}` : this.sessionNowTime();
  }

  /* ─── Utilities ─── */
  fmtNum(v: any): string {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : '-';
  }

  private fmtVol(v: number): string {
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
    return String(Math.round(v));
  }

  private num(v: unknown): number | null {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  private maxVal(arr: any[], key: string): number {
    return Math.max(
      ...arr.map((r: any) => Number(String(r[key] ?? '0').replace(/,/g, ''))).filter(v => v > 0),
      1,
    );
  }

  private toneOf(value: string | undefined): KVItem['tone'] {
    const t = (value ?? '').toUpperCase();
    if (t.includes('OK') || t.includes('RUNNING') || t.includes('GOOD') || t.includes('FRESH')) return 'good';
    if (t.includes('ERROR') || t.includes('FAIL') || t.includes('OFFLINE')) return 'bad';
    if (t.includes('STALE') || t.includes('UNKNOWN') || t.includes('NO_DATA')) return 'warn';
    return 'neutral';
  }

  private biasTone(value: string | undefined): KVItem['tone'] {
    const t = (value ?? '').toUpperCase();
    if (t.includes('BULL')) return 'good';
    if (t.includes('BEAR')) return 'bad';
    if (t.includes('NO') || t.includes('UNKNOWN')) return 'warn';
    return 'neutral';
  }

  private riskTone(value: string | undefined): KVItem['tone'] {
    const t = (value ?? '').toUpperCase();
    if (t.includes('HIGH')) return 'bad';
    if (t.includes('LOW')) return 'good';
    return 'warn';
  }

  private toStrArr(value: unknown): string[] {
    if (!value) return [];
    if (Array.isArray(value)) {
      return value.map(v => typeof v === 'string' ? v : JSON.stringify(v)).filter(Boolean);
    }
    return [];
  }

  private sessionNowTime(): string {
    return new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  private minutesFromTime(value: string): number {
    const match = /^(\d{1,2}):(\d{2})/.exec(value);
    if (!match) return 0;
    return Number(match[1]) * 60 + Number(match[2]);
  }
}
