import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { NgxEchartsDirective } from 'ngx-echarts';
import {
  catchError,
  forkJoin,
  interval,
  of,
  retry,
  startWith,
  Subscription,
  switchMap,
  timeout,
} from 'rxjs';

interface NiftyConstituentRow {
  rank: number;
  companyName: string;
  symbol: string;
  industry: string;
  ltp: number | null;
  changePercent: number | null;
  changeValue: number | null;
  volume: number | null;
  dataStatus: string;
  chart: object;
}

type IndexSymbol = 'NIFTY' | 'BANKNIFTY';

@Component({
  selector: 'app-market-flow',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    NgxEchartsDirective,
  ],
  template: `
<div class="market-flow-page">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">MARKET FLOW</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Market Flow Analysis
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        OI change · Trap detection · Participant context ·
        Updated: {{lastUpdated}}
      </p>
    </div>
    <div class="top-actions">
      <div class="index-switch" aria-label="Index selector">
        <button *ngFor="let option of indexOptions"
                type="button"
                [class.active]="selectedIndex === option.symbol"
                (click)="setSelectedIndex(option.symbol)">
          {{option.label}}
        </button>
      </div>
      <button mat-stroked-button (click)="refresh()"
              style="color:var(--nx-text-2)">
        <mat-icon>refresh</mat-icon>
        Refresh
      </button>
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
              gap:10px;margin-bottom:16px">

    <mat-card class="nx-card">
      <span class="nx-label">FLOW BIAS</span>
      <div class="nx-value" [ngClass]="biasClass(flow?.bias)">
        {{flow?.bias || 'NO_DATA'}}
      </div>
      <div class="nx-sub">Score: {{flow?.flow_score ?? '-'}}</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">FLOW CONFIDENCE</span>
      <div class="nx-value"
           [ngClass]="flow?.confidence === 'HIGH'
             ? 'c-success'
             : flow?.confidence === 'MEDIUM'
             ? 'c-warning' : 'c-muted'">
        {{flow?.confidence || '-'}}
      </div>
      <div class="nx-sub">Market flow engine</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">TRAP RISK</span>
      <div class="nx-value"
           [ngClass]="flow?.trap_risk === 'HIGH'
             ? 'c-danger'
             : flow?.trap_risk === 'MEDIUM'
             ? 'c-warning' : 'c-success'">
        {{flow?.trap_risk || '-'}}
      </div>
      <div class="nx-sub">Bull/bear trap detection</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">SECTOR BIAS</span>
      <div class="nx-value" [ngClass]="biasClass(sector?.market_bias || sector?.breadth_bias)">
        {{sector?.market_bias || sector?.breadth_bias || '-'}}
      </div>
      <div class="nx-sub">
        {{sector?.sectors_bullish || 0}}B
        {{sector?.sectors_bearish || 0}}Be
        {{sector?.sectors_neutral || 0}}N
      </div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">PARTICIPANT FLOW</span>
      <div class="nx-value" [ngClass]="biasClass(participant?.bias)">
        {{participant?.bias || '-'}}
      </div>
      <div class="nx-sub">FII / DII context</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">OI CHANGE SIGNAL</span>
      <div class="nx-value" [ngClass]="biasClass(flow?.flow_change_bias)">
        {{flow?.flow_change_bias || '-'}}
      </div>
      <div class="nx-sub">Snapshot delta pattern</div>
    </mat-card>
  </div>

  <div class="flow-context-grid">
    <div class="nx-card flow-card">
      <div class="flow-card-head">
        <span class="nx-label">FII / DII FLOW</span>
        <span class="nx-chip" [ngClass]="biasClass(fiiDii?.cash_context_bias)">
          {{fiiDii?.cash_context_bias || participant?.bias || 'NO_DATA'}}
        </span>
      </div>

      <div class="flow-bars">
        <div class="flow-row">
          <div>
            <div class="flow-name">FII Cash Net</div>
            <div class="flow-value" [ngClass]="numberTone(fiiDii?.fii_cash_net)">
              {{signedNumber(fiiDii?.fii_cash_net)}}
            </div>
          </div>
          <div class="flow-track">
            <span class="flow-fill"
                  [ngClass]="numberTone(fiiDii?.fii_cash_net)"
                  [style.width.%]="flowWidth(fiiDii?.fii_cash_net)">
            </span>
          </div>
        </div>

        <div class="flow-row">
          <div>
            <div class="flow-name">DII Cash Net</div>
            <div class="flow-value" [ngClass]="numberTone(fiiDii?.dii_cash_net)">
              {{signedNumber(fiiDii?.dii_cash_net)}}
            </div>
          </div>
          <div class="flow-track">
            <span class="flow-fill"
                  [ngClass]="numberTone(fiiDii?.dii_cash_net)"
                  [style.width.%]="flowWidth(fiiDii?.dii_cash_net)">
            </span>
          </div>
        </div>
      </div>

      <div class="flow-meta">
        <span>{{fiiDii?.latest_record_date || 'No latest date'}}</span>
        <span>{{fiiDii?.data_freshness || 'NO_DATA'}}</span>
        <span *ngIf="fiiDii?.dii_supporting_fii_selling">DII absorbing FII selling</span>
        <span *ngIf="fiiDii?.import_required">{{fiiDii?.import_hint || 'Import FII/DII cash data'}}</span>
      </div>
    </div>

    <div class="nx-card flow-card">
      <div class="flow-card-head">
        <span class="nx-label">{{indexLabel}} IMPACT</span>
        <span class="nx-chip nx-chip-info">
          {{constituents.length}} STOCKS
        </span>
      </div>
      <div class="impact-grid">
        <div>
          <span class="impact-label">Gainers</span>
          <strong class="c-success">{{gainerCount}}</strong>
        </div>
        <div>
          <span class="impact-label">Losers</span>
          <strong class="c-danger">{{loserCount}}</strong>
        </div>
        <div>
          <span class="impact-label">Participant Score</span>
          <strong [ngClass]="biasClass(participant?.bias)">
            {{participant?.score ?? 0}}
          </strong>
        </div>
      </div>
      <div class="flow-meta">
        <span>{{participant?.context_status || 'PARTICIPANT_CONTEXT'}}</span>
        <span>{{constituentStatus}}</span>
      </div>
    </div>
  </div>

  <div class="nx-card nifty-matrix-card">
    <div class="matrix-header">
      <div>
        <span class="nx-label">{{indexLabel}} CONSTITUENT MATRIX</span>
        <h2>{{indexLabel}} companies ranked by today&apos;s gainers to losers</h2>
      </div>
      <div class="matrix-tabs" [attr.aria-label]="indexLabel + ' view filter'">
        <button type="button"
                [class.active]="constituentFilter === 'all'"
                (click)="setConstituentFilter('all')">All</button>
        <button type="button"
                [class.active]="constituentFilter === 'gainers'"
                (click)="setConstituentFilter('gainers')">Gainers</button>
        <button type="button"
                [class.active]="constituentFilter === 'losers'"
                (click)="setConstituentFilter('losers')">Losers</button>
        <button type="button"
                [class.active]="constituentFilter === 'impact'"
                (click)="setConstituentFilter('impact')">FII/DII Impact</button>
      </div>
    </div>

    <div *ngIf="!visibleConstituents.length" class="nx-empty">
      {{indexLabel}} quote data is not available yet. Refresh after Dhan or NSE market data is online.
    </div>

    <div *ngIf="visibleConstituents.length" class="nifty-matrix">
      <article *ngFor="let item of visibleConstituents" class="stock-cell">
        <div class="stock-topline">
          <span class="stock-rank">#{{item.rank}}</span>
          <span class="stock-change" [ngClass]="numberTone(item.changePercent)">
            {{percentText(item.changePercent)}}
          </span>
        </div>
        <div class="stock-name" [title]="item.companyName">
          {{item.companyName}}
        </div>
        <div class="stock-meta">
          <span>{{item.symbol}}</span>
          <span>{{item.industry}}</span>
        </div>
        <div echarts [options]="item.chart" class="stock-sparkline"></div>
        <div class="stock-bottom">
          <span>{{priceText(item.ltp)}}</span>
          <span [ngClass]="numberTone(item.changeValue)">
            {{signedNumber(item.changeValue)}}
          </span>
        </div>
      </article>
    </div>
  </div>

  <div class="sector-flow-grid">
    <div class="nx-card">
      <span class="nx-label">SECTOR BREADTH</span>
      <div *ngIf="hasSectorChart; else noSectorChart"
           echarts [options]="sectorChart"
           style="height:220px;width:100%"></div>
      <ng-template #noSectorChart>
        <div class="nx-empty">
          Sector breadth chart needs sector rows or breadth counts.
        </div>
      </ng-template>
    </div>

    <div class="nx-card">
      <span class="nx-label">FLOW SIGNALS</span>
      <div *ngIf="!flowReasons.length"
           style="padding:24px;text-align:center;
                  font-size:12px;color:var(--nx-text-3)">
        No flow signals available.
      </div>
      <div *ngFor="let r of flowReasons"
           style="display:flex;align-items:flex-start;
                  gap:10px;padding:8px 0;
                  border-bottom:0.5px solid var(--nx-border)">
        <mat-icon style="font-size:14px;width:14px;height:14px;
                         margin-top:2px"
                  [style.color]="r.tone === 'good'
                    ? 'var(--nx-success)'
                    : r.tone === 'bad'
                    ? 'var(--nx-danger)'
                    : 'var(--nx-warning)'">
          {{r.tone === 'good' ? 'trending_up'
            : r.tone === 'bad' ? 'trending_down' : 'remove'}}
        </mat-icon>
        <div>
          <div style="font-size:12px;color:var(--nx-text-2)">
            {{r.message}}
          </div>
          <div style="font-size:10px;
                      color:var(--nx-text-3);margin-top:2px">
            {{r.source}}
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="nx-card">
    <span class="nx-label">
      OI CHANGE BY STRIKE (latest snapshot delta)
    </span>
    <div *ngIf="!oiRows.length"
         style="text-align:center;padding:24px;
                font-size:12px;color:var(--nx-text-3)">
      No OI change data. It needs 2+ option-chain snapshots.
    </div>
    <div *ngIf="oiRows.length" class="oi-table-wrap">
      <table>
        <thead>
          <tr style="color:var(--nx-text-3);font-size:10px;
                     letter-spacing:.07em;
                     border-bottom:0.5px solid var(--nx-border)">
            <th style="text-align:left;padding:6px 8px">STRIKE</th>
            <th style="text-align:left;padding:6px 8px">TYPE</th>
            <th style="text-align:right;padding:6px 8px">OI CHANGE</th>
            <th style="text-align:right;padding:6px 8px">VOL CHANGE</th>
            <th style="text-align:right;padding:6px 8px">LTP CHANGE</th>
            <th style="text-align:left;padding:6px 8px">CLASS</th>
            <th style="text-align:left;padding:6px 8px">REASON</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of oiRows"
              style="border-bottom:0.5px solid var(--nx-border)">
            <td style="padding:7px 8px;color:var(--nx-text-1);
                       font-weight:600">
              {{row.strike}}
            </td>
            <td style="padding:7px 8px">
              <span class="nx-chip"
                    [ngClass]="row.type === 'CE'
                      ? 'nx-chip-ok' : 'nx-chip-fail'">
                {{row.type}}
              </span>
            </td>
            <td style="padding:7px 8px;text-align:right;
                       font-weight:500"
                [ngClass]="(row.oiChange || 0) > 0
                  ? 'c-success' : 'c-danger'">
              {{(row.oiChange || 0) > 0 ? '+' : ''}}
              {{row.oiChange | number:'1.0-0'}}
            </td>
            <td style="padding:7px 8px;text-align:right"
                [ngClass]="(row.volumeChange || 0) > 0
                  ? 'c-success' : 'c-danger'">
              {{(row.volumeChange || 0) > 0 ? '+' : ''}}
              {{row.volumeChange | number:'1.0-0'}}
            </td>
            <td style="padding:7px 8px;text-align:right;
                       color:var(--nx-text-2)">
              {{row.ltpChange | number:'1.0-2'}}
            </td>
            <td style="padding:7px 8px">
              <span style="font-size:11px;font-weight:500"
                    [style.color]="row.classification === 'BUILDUP'
                      ? 'var(--nx-success)'
                      : row.classification === 'UNWINDING'
                      ? 'var(--nx-danger)'
                      : 'var(--nx-text-3)'">
                {{row.classification || '-'}}
              </span>
            </td>
            <td style="padding:7px 8px;font-size:11px;
                       color:var(--nx-text-3)">
              {{row.reason || '-'}}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
  `,
  styles: [`
    .market-flow-page {
      width: 100%;
      max-width: min(1400px, 100%);
      min-width: 0;
      margin: 0 auto;
      overflow-x: hidden;
    }

    .market-flow-page :where(.nx-card, mat-card, [echarts]) {
      min-width: 0;
    }

    .top-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 8px;
    }

    .index-switch {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .index-switch button {
      min-height: 36px;
      border: .5px solid var(--nx-border);
      border-radius: 6px;
      background: var(--nx-bg-raised);
      color: var(--nx-text-2);
      cursor: pointer;
      font: inherit;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .03em;
      padding: 0 12px;
    }

    .index-switch button.active {
      border-color: rgba(99, 102, 241, .65);
      background: rgba(99, 102, 241, .16);
      color: #a5b4fc;
    }

    .flow-context-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(260px, .75fr);
      gap: 12px;
      margin-bottom: 16px;
    }

    .sector-flow-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }

    .flow-card {
      min-height: 178px;
    }

    .flow-card-head,
    .matrix-header,
    .stock-topline,
    .stock-bottom,
    .flow-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }

    .flow-bars {
      display: grid;
      gap: 14px;
      margin-top: 16px;
    }

    .flow-row {
      display: grid;
      grid-template-columns: minmax(112px, 160px) 1fr;
      gap: 14px;
      align-items: center;
    }

    .flow-name,
    .impact-label {
      color: var(--nx-text-3);
      font-size: 10px;
      letter-spacing: .07em;
      text-transform: uppercase;
    }

    .flow-value {
      margin-top: 4px;
      font-size: 20px;
      font-weight: 700;
      line-height: 1;
    }

    .flow-track {
      height: 9px;
      overflow: hidden;
      border-radius: 5px;
      background: rgba(148, 163, 184, .12);
    }

    .flow-fill {
      display: block;
      height: 100%;
      min-width: 4px;
      border-radius: inherit;
      background: currentColor;
    }

    .flow-meta {
      flex-wrap: wrap;
      justify-content: flex-start;
      margin-top: 16px;
      color: var(--nx-text-3);
      font-size: 11px;
    }

    .impact-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 18px;
    }

    .impact-grid > div {
      min-width: 0;
      border: .5px solid var(--nx-border);
      border-radius: 8px;
      padding: 10px;
      background: rgba(15, 23, 42, .28);
    }

    .impact-grid strong {
      display: block;
      margin-top: 4px;
      font-size: 22px;
      line-height: 1;
    }

    .nifty-matrix-card {
      margin-bottom: 16px;
    }

    .matrix-header {
      align-items: flex-start;
      margin-bottom: 14px;
    }

    .matrix-header h2 {
      margin: 0;
      color: var(--nx-text-1);
      font-size: 18px;
      font-weight: 600;
      line-height: 1.25;
    }

    .matrix-tabs {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
    }

    .matrix-tabs button {
      border: .5px solid var(--nx-border);
      border-radius: 6px;
      background: var(--nx-bg-raised);
      color: var(--nx-text-2);
      cursor: pointer;
      font: inherit;
      font-size: 11px;
      padding: 7px 10px;
    }

    .matrix-tabs button.active {
      border-color: rgba(6, 182, 212, .55);
      background: rgba(6, 182, 212, .12);
      color: var(--nx-cyan);
    }

    .nifty-matrix {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
      gap: 8px;
    }

    .stock-cell {
      min-width: 0;
      min-height: 148px;
      border: .5px solid var(--nx-border);
      border-radius: 8px;
      background: rgba(15, 23, 42, .35);
      padding: 10px;
    }

    .stock-rank {
      color: var(--nx-text-3);
      font-size: 10px;
      font-weight: 700;
    }

    .stock-change {
      font-size: 12px;
      font-weight: 700;
    }

    .stock-name {
      height: 34px;
      margin-top: 8px;
      color: var(--nx-text-1);
      font-size: 13px;
      font-weight: 650;
      line-height: 1.3;
      overflow: hidden;
    }

    .stock-meta,
    .stock-bottom {
      color: var(--nx-text-3);
      font-size: 10px;
      line-height: 1.25;
    }

    .stock-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin-top: 4px;
    }

    .stock-meta span:last-child {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .stock-sparkline {
      height: 46px;
      width: 100%;
      margin-top: 8px;
    }

    .oi-table-wrap {
      width: 100%;
      max-width: 100%;
      overflow-x: auto;
      margin-top: 8px;
    }

    .oi-table-wrap table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 12px;
    }

    .oi-table-wrap th,
    .oi-table-wrap td {
      overflow-wrap: anywhere;
    }

    @media (max-width: 900px) {
      .flow-context-grid,
      .sector-flow-grid,
      .matrix-header {
        grid-template-columns: 1fr;
        display: grid;
      }

      .matrix-tabs {
        justify-content: flex-start;
      }
    }

    @media (max-width: 560px) {
      .flow-row,
      .impact-grid {
        grid-template-columns: 1fr;
      }

      .nifty-matrix {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class MarketFlowComponent implements OnInit, OnDestroy {
  selectedIndex: IndexSymbol = 'NIFTY';
  indexOptions: { symbol: IndexSymbol; label: string }[] = [
    { symbol: 'NIFTY', label: 'NIFTY 50' },
    { symbol: 'BANKNIFTY', label: 'NIFTY BANK' },
  ];
  flow: any = null;
  sector: any = null;
  participant: any = null;
  fiiDii: any = null;
  constituents: NiftyConstituentRow[] = [];
  constituentFilter: 'all' | 'gainers' | 'losers' | 'impact' = 'all';
  constituentStatus = 'NO_DATA';
  oiRows: any[] = [];
  flowReasons: any[] = [];
  lastUpdated = 'never';
  sectorChart: object = {};
  hasSectorChart = false;
  private sub?: Subscription;

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(60000).pipe(
      startWith(0),
      switchMap(() => this.load())
    ).subscribe((data) => {
      this.applyData(data);
      this.loadSectorSlice(data?.requestIndex || this.selectedIndex);
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  refresh() {
    this.load().subscribe((data) => {
      this.applyData(data);
      this.loadSectorSlice(data?.requestIndex || this.selectedIndex);
    });
  }

  get indexLabel(): string {
    return this.indexOptions.find(option => option.symbol === this.selectedIndex)?.label || this.selectedIndex;
  }

  get verifiedEndpoints(): string[] {
    const symbol = this.selectedIndex;
    const index = encodeURIComponent(symbol);
    return [
      `/api/market-flow/summary?symbol=${symbol}`,
      `/api/market-flow/option-flow?symbol=${symbol}`,
      `/api/market-flow/trap-risk?symbol=${symbol}`,
      `/api/market-flow/smart-money-bias?symbol=${symbol}`,
      `/api/sector-breadth/summary?index=${index}`,
      `/api/sector-breadth/constituents?index=${index}`,
      `/api/participant-flow/context?symbol=${symbol}`,
      '/api/participant-flow/fii-dii',
      `/api/option-chain-snapshots/changes/latest?symbol=${symbol}`,
    ];
  }

  get gainerCount(): number {
    return this.constituents.filter(item => (item.changePercent ?? 0) > 0).length;
  }

  get loserCount(): number {
    return this.constituents.filter(item => (item.changePercent ?? 0) < 0).length;
  }

  get visibleConstituents(): NiftyConstituentRow[] {
    if (this.constituentFilter === 'gainers') {
      return this.constituents.filter(item => (item.changePercent ?? 0) > 0);
    }
    if (this.constituentFilter === 'losers') {
      return this.constituents.filter(item => (item.changePercent ?? 0) < 0);
    }
    if (this.constituentFilter === 'impact') {
      return this.constituents.filter(item =>
        ['Financial Services', 'Information Technology', 'Oil Gas & Consumable Fuels']
          .includes(item.industry)
      );
    }
    return this.constituents;
  }

  setConstituentFilter(filter: 'all' | 'gainers' | 'losers' | 'impact') {
    this.constituentFilter = filter;
  }

  setSelectedIndex(symbol: IndexSymbol) {
    if (this.selectedIndex === symbol) return;
    this.selectedIndex = symbol;
    this.constituentFilter = 'all';
    this.constituents = [];
    this.constituentStatus = 'LOADING';
    this.refresh();
  }

  biasClass(value: string): string {
    const text = String(value || '').toUpperCase();
    if (text.includes('BULL')) return 'c-success';
    if (text.includes('BEAR')) return 'c-danger';
    if (text.includes('HIGH') || text.includes('WAIT') || text.includes('MIXED')) {
      return 'c-warning';
    }
    return 'c-muted';
  }

  numberTone(value: unknown): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric === 0) return 'c-muted';
    return numeric > 0 ? 'c-success' : 'c-danger';
  }

  signedNumber(value: unknown): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '-';
    return `${numeric > 0 ? '+' : ''}${numeric.toFixed(Math.abs(numeric) >= 100 ? 0 : 2)}`;
  }

  percentText(value: unknown): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '-';
    return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`;
  }

  priceText(value: unknown): string {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(2) : '-';
  }

  flowWidth(value: unknown): number {
    const numeric = Math.abs(Number(value));
    const max = Math.max(
      Math.abs(Number(this.fiiDii?.fii_cash_net) || 0),
      Math.abs(Number(this.fiiDii?.dii_cash_net) || 0),
      1
    );
    return Math.max(6, Math.min(100, (numeric / max) * 100));
  }

  private load() {
    const symbol = this.selectedIndex;
    return forkJoin({
      requestIndex: of(symbol),
      summary: this.safeGet(`/api/market-flow/summary?symbol=${symbol}`),
      optionFlow: this.safeGet(`/api/market-flow/option-flow?symbol=${symbol}`),
      trap: this.safeGet(`/api/market-flow/trap-risk?symbol=${symbol}`),
      smart: this.safeGet(`/api/market-flow/smart-money-bias?symbol=${symbol}`),
      participant: this.safeGet(`/api/participant-flow/context?symbol=${symbol}`),
      fiiDii: this.safeGet('/api/participant-flow/fii-dii'),
      oi: this.safeGet(`/api/option-chain-snapshots/changes/latest?symbol=${symbol}`),
    });
  }

  private safeGet(path: string, timeoutMs = 8000, retryCount = 1) {
    return this.http.get<any>(path).pipe(
      timeout(timeoutMs),
      retry({ count: retryCount, delay: 750 }),
      catchError(() => of({ __error: true }))
    );
  }

  private loadSectorSlice(symbol: IndexSymbol) {
    const index = encodeURIComponent(symbol);
    forkJoin({
      requestIndex: of(symbol),
      sector: this.safeGet(`/api/sector-breadth/summary?index=${index}`, 25000, 0),
      constituents: this.safeGet(`/api/sector-breadth/constituents?index=${index}`, 25000, 0),
    }).subscribe((data) => this.applySectorData(data));
  }

  private applyData(data: any) {
    if (data?.requestIndex && data.requestIndex !== this.selectedIndex) {
      return;
    }
    const summary = data.summary || {};
    const optionFlow = data.optionFlow || {};
    const trap = data.trap || {};
    const smart = data.smart || {};
    this.flow = {
      bias: summary.market_flow_bias || summary.bias || smart.bias || 'NO_DATA',
      flow_score: summary.flow_score ?? smart.flow_score ?? '-',
      confidence: summary.confidence || smart.confidence || '-',
      trap_risk: trap.trap_risk || summary.trap_detection?.trap_risk || 'UNKNOWN',
      flow_change_bias: summary.flow_change_bias
        || data.oi?.summary?.flow_change_bias
        || 'NO_EDGE',
      oi_signal: optionFlow.option_flow_bias || summary.option_flow_bias || '-',
    };
    this.sector = this.normalizeSector(data.sector?.summary || data.sector || {});
    const participant = data.participant?.summary || data.participant || {};
    this.participant = {
      ...participant,
      bias: participant.bias || participant.participant_bias || 'NO_DATA',
      score: participant.score ?? participant.participant_score ?? 0,
      context_status: participant.context_status || participant.participant_context_status || participant.status || 'NO_DATA',
    };
    this.fiiDii = data.fiiDii?.__error ? null : data.fiiDii;
    this.oiRows = this.arrayFrom(data.oi, ['items']).slice(0, 16).map((row) => ({
      strike: this.num(row?.strike),
      type: String(row?.option_type || row?.type || '-').toUpperCase(),
      oiChange: this.num(row?.oi_change) || 0,
      volumeChange: this.num(row?.volume_change) || 0,
      ltpChange: this.num(row?.ltp_change) || 0,
      classification: row?.classification || 'UNKNOWN',
      reason: row?.reason || '-',
    }));
    this.flowReasons = this.reasonRows(summary, optionFlow, trap, smart);
    this.lastUpdated = new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
    });
  }

  private applySectorData(data: any) {
    if (data?.requestIndex && data.requestIndex !== this.selectedIndex) {
      return;
    }
    if (!data?.sector?.__error) {
      this.sector = this.normalizeSector(data.sector?.summary || data.sector || {});
      this.buildSectorChart(data.sector);
    }
    if (!data?.constituents?.__error) {
      this.constituentStatus = data.constituents?.quote_status || data.constituents?.status || 'NO_DATA';
      this.constituents = this.arrayFrom(data.constituents, ['items'])
        .map((row: any, index: number) => this.toConstituentRow(row, index + 1));
    }
  }

  private toConstituentRow(row: any, fallbackRank: number): NiftyConstituentRow {
    const changePercent = this.num(row?.change_percent);
    return {
      rank: Number(row?.rank) || fallbackRank,
      companyName: String(row?.company_name || row?.name || row?.symbol || '-'),
      symbol: String(row?.symbol || '-'),
      industry: String(row?.industry || this.indexLabel),
      ltp: this.num(row?.ltp),
      changePercent,
      changeValue: this.num(row?.change_value),
      volume: this.num(row?.volume),
      dataStatus: String(row?.data_status || 'NO_DATA'),
      chart: this.sparklineOption(changePercent),
    };
  }

  private sparklineOption(changePercent: number | null): object {
    const tone = (changePercent ?? 0) >= 0 ? '#10b981' : '#ef4444';
    const start = 100;
    const drift = Number.isFinite(changePercent ?? NaN) ? Number(changePercent) : 0;
    const points = Array.from({ length: 18 }, (_, index) => {
      const wave = Math.sin(index * 0.9) * 0.18 + Math.cos(index * 0.45) * 0.11;
      return Number((start + (drift * index / 17) + wave).toFixed(3));
    });
    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left: 2, right: 2, top: 4, bottom: 4 },
      xAxis: { type: 'category', show: false, data: points.map((_, i) => i) },
      yAxis: {
        type: 'value',
        show: false,
        min: (value: any) => value.min - 0.2,
        max: (value: any) => value.max + 0.2,
      },
      series: [{
        type: 'line',
        data: points,
        showSymbol: false,
        smooth: true,
        lineStyle: { color: tone, width: 2 },
        areaStyle: { color: `${tone}24` },
      }],
    };
  }

  private reasonRows(...sources: any[]): any[] {
    const messages = sources.flatMap((source) => [
      ...this.toStrings(source?.reasons),
      ...this.toStrings(source?.explanation),
      ...this.toStrings(source?.message),
      ...this.toStrings(source?.trap_reason),
    ]);
    return this.unique(messages).slice(0, 8).map((message) => ({
      message,
      source: 'MARKET_FLOW',
      tone: this.toneFor(message),
    }));
  }

  private buildSectorChart(payload: any) {
    const sectors = payload?.sectors || payload?.sector_data || payload?.items || [];
    if (!sectors.length) {
      const bullish = Number(this.sector?.sectors_bullish || 0);
      const bearish = Number(this.sector?.sectors_bearish || 0);
      const neutral = Number(this.sector?.sectors_neutral || 0);
      this.hasSectorChart = bullish + bearish + neutral > 0;
      this.sectorChart = this.simpleBreadthChart(bullish, bearish, neutral);
      return;
    }
    this.hasSectorChart = true;

    const names = sectors.map((sector: any) =>
      sector.sector || sector.name || '?'
    );
    const advances = sectors.map((sector: any) =>
      Number(sector.advancing ?? sector.advancing_count ?? sector.bullish_count ?? sector.gainers ?? 0)
    );
    const declines = sectors.map((sector: any) =>
      Number(sector.declining ?? sector.declining_count ?? sector.bearish_count ?? sector.losers ?? 0)
    );
    this.sectorChart = {
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
      grid: { left: 82, right: 12, top: 24, bottom: 8 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#64748b', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } },
      },
      yAxis: {
        type: 'category',
        data: names,
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisTick: { show: false },
      },
      series: [
        {
          name: 'Advancing',
          type: 'bar',
          data: advances,
          barMaxWidth: 14,
          itemStyle: { color: '#10b981', borderRadius: [0, 3, 3, 0] },
          stack: 'breadth',
        },
        {
          name: 'Declining',
          type: 'bar',
          data: declines,
          barMaxWidth: 14,
          itemStyle: { color: '#ef4444', borderRadius: [0, 3, 3, 0] },
          stack: 'breadth',
        },
      ],
    };
  }

  private normalizeSector(value: any): any {
    const sectors = this.arrayFrom(value, ['sectors', 'sector_data', 'items']);
    const bullish = sectors.filter((sector: any) =>
      String(sector?.sector_bias || sector?.bias || '').toUpperCase().includes('BULL')
    ).length;
    const bearish = sectors.filter((sector: any) =>
      String(sector?.sector_bias || sector?.bias || '').toUpperCase().includes('BEAR')
    ).length;
    const neutral = sectors.length ? Math.max(0, sectors.length - bullish - bearish) : 0;
    return {
      ...value,
      market_bias: value?.market_bias || value?.breadth_bias,
      sectors_bullish: value?.sectors_bullish ?? bullish,
      sectors_bearish: value?.sectors_bearish ?? bearish,
      sectors_neutral: value?.sectors_neutral ?? neutral,
    };
  }

  private simpleBreadthChart(bullish: number, bearish: number, neutral: number): object {
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        radius: ['44%', '70%'],
        data: [
          { value: bullish, name: 'Bullish', itemStyle: { color: '#10b981' } },
          { value: bearish, name: 'Bearish', itemStyle: { color: '#ef4444' } },
          { value: neutral, name: 'Neutral', itemStyle: { color: '#64748b' } },
        ],
      }],
    };
  }

  private arrayFrom(value: unknown, keys: string[]): any[] {
    if (Array.isArray(value)) return value;
    const found = this.findValue(value, keys);
    return Array.isArray(found) ? found : [];
  }

  private findValue(value: unknown, keys: string[]): unknown {
    if (!value || typeof value !== 'object') return undefined;
    const record = value as Record<string, unknown>;
    for (const key of keys) {
      if (record[key] !== undefined && record[key] !== null) return record[key];
    }
    for (const item of Object.values(record)) {
      const found = this.findValue(item, keys);
      if (found !== undefined) return found;
    }
    return undefined;
  }

  private num(value: unknown): number | null {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  private toStrings(value: unknown): string[] {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((item) => String(item));
    return [String(value)];
  }

  private toneFor(message: string): string {
    const text = String(message).toUpperCase();
    if (text.includes('BULL') || text.includes('SUPPORT') || text.includes('CONFIRM')) {
      return 'good';
    }
    if (text.includes('BEAR') || text.includes('RISK') || text.includes('TRAP')) {
      return 'bad';
    }
    return 'warn';
  }

  private unique(values: string[]): string[] {
    return Array.from(new Set(values.filter((value) =>
      value.trim().length > 0 && value !== '-'
    )));
  }
}
