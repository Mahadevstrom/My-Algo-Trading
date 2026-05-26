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
  map,
  of,
  startWith,
  Subscription,
  switchMap,
} from 'rxjs';

@Component({
  selector: 'app-option-chain',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">OPTION CHAIN</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        NIFTY Option Chain
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Read-only · OI snapshot analysis · Updated: {{lastUpdated}}
      </p>
    </div>
    <button mat-stroked-button (click)="refresh()"
            style="color:var(--nx-text-2)">
      <mat-icon>refresh</mat-icon>
      Refresh
    </button>
  </div>

  <div style="background:rgba(239,68,68,.06);
              border:0.5px solid rgba(239,68,68,.3);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#ef4444;
              margin-bottom:16px;display:flex;
              gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>NO PAPER TRADE CREATION</span>
    <span>NO SNAPSHOT TRIGGERS</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Display only
    </span>
  </div>

  <div *ngIf="loadError"
       class="nx-card"
       style="margin-bottom:16px;border-color:rgba(245,158,11,.35)">
    <span class="nx-label">OPTION CHAIN DATA</span>
    <div style="font-size:14px;color:var(--nx-warning);font-weight:600">
      Some option-chain data is unavailable.
    </div>
    <div style="font-size:12px;color:var(--nx-text-3);margin-top:5px">
      The page is showing the latest readable snapshot/context.
    </div>
  </div>

  <div style="display:grid;
              grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
              gap:10px;margin-bottom:16px">

    <mat-card class="nx-card">
      <span class="nx-label">SPOT / ATM</span>
      <div class="nx-value c-accent">
        {{summary?.spotPrice ?? '-'}}
      </div>
      <div class="nx-sub">ATM: {{summary?.atmStrike ?? '-'}}</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">CHAIN BIAS</span>
      <div class="nx-value"
           [ngClass]="summary?.chainBias === 'BULLISH'
             ? 'c-success'
             : summary?.chainBias === 'BEARISH'
             ? 'c-danger' : 'c-muted'">
        {{summary?.chainBias || 'NO DATA'}}
      </div>
      <div class="nx-sub">
        Expiry: {{summary?.expiry || 'NO_EXPIRY'}}
      </div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">PCR OI</span>
      <div class="nx-value"
           [ngClass]="(summary?.pcrOi || 0) > 1.2
             ? 'c-success'
             : (summary?.pcrOi || 0) < 0.8
             ? 'c-danger' : 'c-warning'">
        {{summary?.pcrOi != null
          ? (summary.pcrOi | number:'1.2-2') : '-'}}
      </div>
      <div class="nx-sub">
        PCR Vol: {{summary?.pcrVolume != null
          ? (summary.pcrVolume | number:'1.2-2') : '-'}}
      </div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">TOTAL CE OI</span>
      <div class="nx-value c-success">
        {{summary?.totalCeOi != null ? formatOI(summary.totalCeOi) : '-'}}
      </div>
      <div class="nx-sub">Call open interest</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">TOTAL PE OI</span>
      <div class="nx-value c-danger">
        {{summary?.totalPeOi != null ? formatOI(summary.totalPeOi) : '-'}}
      </div>
      <div class="nx-sub">Put open interest</div>
    </mat-card>

    <mat-card class="nx-card">
      <span class="nx-label">SUPPORT / RESIST</span>
      <div style="display:flex;gap:8px;align-items:baseline;
                  margin-top:4px">
        <span style="font-size:14px;font-weight:600;
                     color:var(--nx-success)">
          {{summary?.supportStrike ?? '-'}}
        </span>
        <span style="font-size:11px;color:var(--nx-text-3)">S</span>
        <span style="font-size:14px;font-weight:600;
                     color:var(--nx-danger)">
          {{summary?.resistanceStrike ?? '-'}}
        </span>
        <span style="font-size:11px;color:var(--nx-text-3)">R</span>
      </div>
      <div class="nx-sub">OI-derived levels</div>
    </mat-card>
  </div>

  <div style="display:grid;grid-template-columns:1fr 260px;
              gap:12px;margin-bottom:16px">
    <div class="nx-card">
      <span class="nx-label">OI INTENSITY BY STRIKE</span>
      <p style="font-size:11px;color:var(--nx-text-3);
                margin:2px 0 8px">
        Green = CE OI (resistance) · Red = PE OI (support) ·
        Blue label = ATM
      </p>
      <div echarts [options]="oiHeatmap"
           style="height:200px;width:100%"></div>
    </div>

    <div class="nx-card">
      <span class="nx-label">CE vs PE SPLIT</span>
      <div echarts [options]="cepeDonut"
           style="height:200px;width:100%"></div>
    </div>
  </div>

  <div class="nx-card" style="margin-bottom:16px">
    <span class="nx-label">NEARBY STRIKES</span>
    <div *ngIf="!strikes.length"
         style="text-align:center;padding:24px;
                color:var(--nx-text-3);font-size:13px">
      No strike data. Check backend market data and Dhan connection.
    </div>
    <div *ngIf="strikes.length" style="overflow-x:auto;margin-top:8px">
      <table style="width:100%;border-collapse:collapse;
                    font-size:12px;min-width:880px">
        <thead>
          <tr style="color:var(--nx-text-3);font-size:10px;
                     letter-spacing:.07em;
                     border-bottom:0.5px solid var(--nx-border)">
            <th style="text-align:right;padding:6px 8px">CE OI</th>
            <th style="text-align:right;padding:6px 8px">CE OI CHG</th>
            <th style="text-align:right;padding:6px 8px">CE LTP</th>
            <th style="text-align:center;padding:6px 12px;
                       font-size:12px;color:var(--nx-text-1)">
              STRIKE
            </th>
            <th style="text-align:left;padding:6px 8px">PE LTP</th>
            <th style="text-align:left;padding:6px 8px">PE OI CHG</th>
            <th style="text-align:left;padding:6px 8px">PE OI</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let s of strikes"
              [style.background]="isAtm(s.strike)
                ? 'rgba(99,102,241,.08)' : 'transparent'"
              style="border-bottom:0.5px solid var(--nx-border)">
            <td style="text-align:right;padding:7px 8px;
                       color:var(--nx-success);font-weight:500">
              {{formatOI(s.ceOi)}}
            </td>
            <td style="text-align:right;padding:7px 8px"
                [ngClass]="(s.ceOiChange || 0) > 0
                  ? 'c-success' : 'c-danger'">
              {{(s.ceOiChange || 0) > 0 ? '+' : ''}}
              {{formatOI(s.ceOiChange)}}
            </td>
            <td style="text-align:right;padding:7px 8px;
                       color:var(--nx-text-2)">
              {{s.ceLtp | number:'1.0-1'}}
            </td>
            <td style="text-align:center;padding:7px 12px;
                       font-weight:700;font-size:13px"
                [style.color]="isAtm(s.strike)
                  ? 'var(--nx-accent)' : 'var(--nx-text-1)'">
              {{s.strike}}
              <span *ngIf="isAtm(s.strike)"
                    style="font-size:9px;color:var(--nx-accent);
                           display:block;font-weight:400">
                ATM
              </span>
            </td>
            <td style="text-align:left;padding:7px 8px;
                       color:var(--nx-text-2)">
              {{s.peLtp | number:'1.0-1'}}
            </td>
            <td style="text-align:left;padding:7px 8px"
                [ngClass]="(s.peOiChange || 0) > 0
                  ? 'c-danger' : 'c-success'">
              {{(s.peOiChange || 0) > 0 ? '+' : ''}}
              {{formatOI(s.peOiChange)}}
            </td>
            <td style="text-align:left;padding:7px 8px;
                       color:var(--nx-danger);font-weight:500">
              {{formatOI(s.peOi)}}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div *ngIf="warnings.length" class="nx-card">
    <span class="nx-label">WARNINGS / MISSING DATA</span>
    <div *ngFor="let w of warnings"
         style="display:flex;align-items:flex-start;
                gap:8px;padding:6px 0;
                border-bottom:0.5px solid var(--nx-border)">
      <mat-icon style="font-size:14px;width:14px;height:14px;
                       color:var(--nx-warning);margin-top:2px">
        warning_amber
      </mat-icon>
      <span style="font-size:12px;color:var(--nx-text-2)">
        {{w}}
      </span>
    </div>
  </div>
</div>
  `,
})
export class OptionChainComponent implements OnInit, OnDestroy {
  summary: any = null;
  strikes: any[] = [];
  warnings: string[] = [];
  lastUpdated = 'never';
  loadError = false;
  oiHeatmap: object = {};
  cepeDonut: object = {};
  verifiedEndpoints = [
    '/api/market/option-expiries/NIFTY',
    '/api/option-chain/atm/NIFTY?expiry={expiry}',
    '/api/option-chain-snapshots/latest?symbol=NIFTY',
    '/api/option-chain-snapshots/changes/latest?symbol=NIFTY',
  ];
  private sub?: Subscription;

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(60000).pipe(
      startWith(0),
      switchMap(() => this.load())
    ).subscribe((data) => this.applyData(data));
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  refresh() {
    this.load().subscribe((data) => this.applyData(data));
  }

  isAtm(strike: number | string): boolean {
    return String(strike) === String(this.summary?.atmStrike);
  }

  formatOI(value: number | string | null): string {
    if (value === null || value === undefined || value === '') return '-';
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) return '-';
    const sign = numberValue < 0 ? '-' : '';
    const abs = Math.abs(numberValue);
    if (abs >= 1000000) return sign + (abs / 1000000).toFixed(1) + 'M';
    if (abs >= 1000) return sign + (abs / 1000).toFixed(0) + 'K';
    return sign + String(Math.round(abs));
  }

  private load() {
    return this.safeGet('/api/market/option-expiries/NIFTY').pipe(
      switchMap((expiriesPayload) => {
        const expiry = this.firstExpiry(expiriesPayload);
        const chainPath = expiry
          ? '/api/option-chain/atm/NIFTY?expiry=' + encodeURIComponent(expiry)
          : '';
        return forkJoin({
          expiries: of(expiriesPayload),
          chain: chainPath ? this.safeGet(chainPath) : of(null),
          latestSnapshot: this.safeGet('/api/option-chain-snapshots/latest?symbol=NIFTY'),
          changes: this.safeGet('/api/option-chain-snapshots/changes/latest?symbol=NIFTY'),
        }).pipe(map((result) => ({ ...result, expiry })));
      })
    );
  }

  private safeGet(path: string) {
    return this.http.get<any>(path).pipe(catchError(() => of({ __error: true })));
  }

  private applyData(data: any) {
    const chain = data?.chain;
    const chainSummary = chain?.summary || {};
    const latestSnapshot = data?.latestSnapshot?.snapshot || data?.latestSnapshot || {};
    const changes = data?.changes || {};
    const changeItems = this.arrayFrom(changes, ['items']);
    this.summary = this.normalizeSummary(chainSummary, latestSnapshot, data?.expiry);
    this.strikes = this.arrayFrom(chain, ['strikes']).map((row) =>
      this.normalizeStrike(row, changeItems)
    );
    this.warnings = this.unique([
      ...this.toStrings(chain?.warnings || chain?.missing_data || chain?.message),
      ...this.toStrings(changes?.warnings || changes?.missing_data || changes?.message),
      ...(!data?.expiry ? ['No valid NIFTY expiry was returned.'] : []),
      ...(chain?.__error ? ['Option-chain ATM endpoint failed.'] : []),
      ...(data?.latestSnapshot?.__error ? ['Latest option-chain snapshot endpoint failed.'] : []),
      ...(data?.changes?.__error ? ['OI change endpoint failed.'] : []),
    ]);
    this.loadError = Boolean(chain?.__error || data?.latestSnapshot?.__error || data?.changes?.__error);
    this.lastUpdated = new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
    });
    this.buildCharts();
  }

  private normalizeSummary(source: any, snapshot: any, expiry: string): any {
    return {
      underlying: source.underlying || snapshot.symbol || 'NIFTY',
      spotPrice: this.num(source.spot_price ?? source.spot ?? snapshot.spot_price),
      expiry: source.expiry || snapshot.expiry || expiry || 'NO_EXPIRY',
      atmStrike: this.num(source.atm_strike ?? snapshot.atm_strike),
      chainBias: source.chain_bias || source.bias || snapshot.chain_bias || 'NO_DATA',
      pcrOi: this.num(source.pcr_oi ?? snapshot.pcr_oi),
      pcrVolume: this.num(source.pcr_volume ?? snapshot.pcr_volume),
      totalCeOi: this.num(source.total_ce_oi ?? snapshot.total_ce_oi),
      totalPeOi: this.num(source.total_pe_oi ?? snapshot.total_pe_oi),
      supportStrike: this.num(source.support_strike ?? snapshot.support_strike),
      resistanceStrike: this.num(source.resistance_strike ?? snapshot.resistance_strike),
    };
  }

  private normalizeStrike(row: any, changes: any[]): any {
    const strike = this.num(row?.strike);
    const ceChange = this.findChange(changes, strike, 'CE');
    const peChange = this.findChange(changes, strike, 'PE');
    return {
      strike,
      ceOi: this.num(row?.ce_oi ?? row?.ceOi) || 0,
      peOi: this.num(row?.pe_oi ?? row?.peOi) || 0,
      ceOiChange: this.num(ceChange?.oi_change ?? row?.ce_oi_change ?? row?.ceOiChange) || 0,
      peOiChange: this.num(peChange?.oi_change ?? row?.pe_oi_change ?? row?.peOiChange) || 0,
      ceVolume: this.num(row?.ce_volume ?? row?.ceVolume) || 0,
      peVolume: this.num(row?.pe_volume ?? row?.peVolume) || 0,
      ceLtp: this.num(row?.ce_ltp ?? row?.ceLtp) || 0,
      peLtp: this.num(row?.pe_ltp ?? row?.peLtp) || 0,
    };
  }

  private findChange(changes: any[], strike: number | null, type: string): any {
    return changes.find((item) =>
      String(item?.strike) === String(strike)
      && String(item?.option_type || item?.type).toUpperCase() === type
    );
  }

  private buildCharts() {
    const atm = Number(this.summary?.atmStrike || 0);
    const sorted = [...this.strikes].sort((a, b) =>
      Number(a.strike) - Number(b.strike)
    );
    const labels = sorted.map((strike) => String(strike.strike));
    const ceVals = sorted.map((strike) => Number(strike.ceOi) || 0);
    const peVals = sorted.map((strike) => Number(strike.peOi) || 0);
    const maxOI = Math.max(...ceVals, ...peVals, 1);

    this.oiHeatmap = {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 48, right: 12, top: 24, bottom: 52 },
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
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: {
          color: '#64748b',
          fontSize: 9,
          rotate: 35,
          interval: 0,
          formatter: (value: string) => Number(value) === atm
            ? `{atm|${value}}` : value,
          rich: {
            atm: { color: '#6366f1', fontWeight: 'bold', fontSize: 9 },
          },
        },
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        max: maxOI,
        axisLabel: {
          color: '#64748b',
          fontSize: 9,
          formatter: (value: number) => this.formatOI(value),
        },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } },
        axisLine: { show: false },
      },
      series: [
        {
          name: 'CE OI',
          type: 'bar',
          data: ceVals,
          barMaxWidth: 16,
          itemStyle: {
            color: (params: any) =>
              `rgba(16,185,129,${0.35 + (params.value / maxOI) * 0.65})`,
            borderRadius: [3, 3, 0, 0],
          },
        },
        {
          name: 'PE OI',
          type: 'bar',
          data: peVals,
          barMaxWidth: 16,
          itemStyle: {
            color: (params: any) =>
              `rgba(239,68,68,${0.35 + (params.value / maxOI) * 0.65})`,
            borderRadius: [3, 3, 0, 0],
          },
        },
      ],
    };

    const ceOI = Number(this.summary?.totalCeOi || 0);
    const peOI = Number(this.summary?.totalPeOi || 0);
    const pcr = ceOI > 0 ? (peOI / ceOI).toFixed(2) : 'N/A';
    this.cepeDonut = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: any) =>
          `${params.name}: ${this.formatOI(params.value)} (${params.percent}%)`,
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
        label: {
          show: true,
          position: 'center',
          formatter: () => `PCR\n${pcr}`,
          color: '#f1f5f9',
          fontSize: 13,
          fontWeight: 600,
          lineHeight: 20,
        },
        data: [
          { value: ceOI, name: 'CE OI', itemStyle: { color: '#10b981' } },
          { value: peOI, name: 'PE OI', itemStyle: { color: '#ef4444' } },
        ],
      }],
    };
  }

  private firstExpiry(payload: any): string {
    const data = payload?.data?.data || payload?.data || payload?.expiries || payload?.items;
    return Array.isArray(data) ? String(data[0] || '') : '';
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

  private unique(values: string[]): string[] {
    return Array.from(new Set(values.filter((value) =>
      value.trim().length > 0 && value !== '-'
    )));
  }
}
