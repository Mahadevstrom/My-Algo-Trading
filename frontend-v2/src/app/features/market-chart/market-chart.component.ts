import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { forkJoin, interval, of, Subscription } from 'rxjs';
import { catchError, startWith, switchMap } from 'rxjs';
import {
  CandlestickData,
  createChart,
  HistogramData,
  IChartApi,
  ISeriesApi,
  LineStyle,
} from 'lightweight-charts';

type Tf = '1m' | '3m' | '5m' | '15m';

interface ParsedCandle extends CandlestickData {
  volume?: number;
  tickCount?: number;
}

@Component({
  selector: 'app-market-chart',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatButtonToggleModule,
  ],
  template: `
<div style="max-width:1400px;margin:0 auto">

  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">MARKET CHART</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        NIFTY Live Chart
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);
                margin:4px 0 0">
        Broker-style candles · pivot levels · paper markers ·
        Updated: {{lastUpdated}}
      </p>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <mat-button-toggle-group
        [(ngModel)]="selectedTf"
        (change)="onTfChange($event.value)"
        style="border-color:var(--nx-border)">
        <mat-button-toggle *ngFor="let tf of timeframes"
                           [value]="tf"
                           style="font-size:11px;
                                  color:var(--nx-text-2)">
          {{tf}}
        </mat-button-toggle>
      </mat-button-toggle-group>
      <button mat-stroked-button (click)="refresh()"
              style="color:var(--nx-text-2)">
        <mat-icon>refresh</mat-icon>
      </button>
    </div>
  </div>

  <div style="background:rgba(239,68,68,.06);
              border:0.5px solid rgba(239,68,68,.3);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#ef4444;
              margin-bottom:16px;display:flex;
              gap:16px;flex-wrap:wrap">
    <span>READ ONLY</span>
    <span>NO ORDER PLACEMENT</span>
    <span>PAPER MARKERS ONLY</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Candle endpoint: /api/live-monitor/candles/NIFTY
    </span>
  </div>

  <div class="nx-card" style="margin-bottom:12px;
                               padding:12px 16px">
    <div style="display:flex;gap:24px;
                align-items:center;flex-wrap:wrap">
      <div>
        <span class="nx-label">LTP</span>
        <div style="font-size:24px;font-weight:700;
                    color:var(--nx-text-1)">
          {{latestCandle?.close
            ? (latestCandle.close | number:'1.2-2')
            : '-'}}
        </div>
      </div>
      <div>
        <span class="nx-label">OPEN</span>
        <div style="font-size:15px;font-weight:500;
                    color:var(--nx-text-2)">
          {{latestCandle?.open
            ? (latestCandle.open | number:'1.2-2')
            : '-'}}
        </div>
      </div>
      <div>
        <span class="nx-label">HIGH</span>
        <div style="font-size:15px;font-weight:500;
                    color:var(--nx-success)">
          {{latestCandle?.high
            ? (latestCandle.high | number:'1.2-2')
            : '-'}}
        </div>
      </div>
      <div>
        <span class="nx-label">LOW</span>
        <div style="font-size:15px;font-weight:500;
                    color:var(--nx-danger)">
          {{latestCandle?.low
            ? (latestCandle.low | number:'1.2-2')
            : '-'}}
        </div>
      </div>
      <div>
        <span class="nx-label">CANDLES</span>
        <div style="font-size:15px;font-weight:500;
                    color:var(--nx-text-2)">
          {{candles.length}}
        </div>
      </div>
      <div>
        <span class="nx-label">TIMEFRAME</span>
        <div style="font-size:15px;font-weight:500;
                    color:var(--nx-accent)">
          {{selectedTf}}
        </div>
      </div>
    </div>
  </div>

  <div class="nx-card" style="padding:12px;margin-bottom:12px">
    <div style="display:flex;gap:8px;align-items:center;
                justify-content:space-between;margin-bottom:10px;
                flex-wrap:wrap">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="nx-chip nx-chip-info">
          P {{pivotLevels.p || '-'}}
        </span>
        <span class="nx-chip nx-chip-ok">
          S1 {{pivotLevels.s1 || '-'}}
        </span>
        <span class="nx-chip nx-chip-fail">
          R1 {{pivotLevels.r1 || '-'}}
        </span>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button mat-stroked-button
                [style.color]="showPaperMarkers
                  ? 'var(--nx-accent)' : 'var(--nx-text-3)'"
                [style.border-color]="showPaperMarkers
                  ? 'var(--nx-accent)' : 'var(--nx-border)'"
                (click)="toggleMarkers()">
          <mat-icon style="font-size:14px;width:14px;
                           height:14px">push_pin</mat-icon>
          Markers
        </button>
        <button mat-stroked-button
                [style.color]="showSR
                  ? 'var(--nx-accent)' : 'var(--nx-text-3)'"
                [style.border-color]="showSR
                  ? 'var(--nx-accent)' : 'var(--nx-border)'"
                (click)="toggleSR()">
          <mat-icon style="font-size:14px;width:14px;
                           height:14px">horizontal_rule</mat-icon>
          Pivot S/R
        </button>
        <button mat-stroked-button
                [style.color]="showVolume
                  ? 'var(--nx-accent)' : 'var(--nx-text-3)'"
                [style.border-color]="showVolume
                  ? 'var(--nx-accent)' : 'var(--nx-border)'"
                (click)="toggleVolume()">
          <mat-icon style="font-size:14px;width:14px;
                           height:14px">bar_chart</mat-icon>
          Volume
        </button>
      </div>
    </div>

    <div style="position:relative">
      <div #chartHost
           style="width:100%;height:430px;
                  background:#0b1220;border-radius:8px;
                  overflow:hidden">
      </div>
      <div *ngIf="!candles.length"
           style="position:absolute;top:50%;left:50%;
                  transform:translate(-50%,-50%);
                  text-align:center;pointer-events:none">
        <mat-icon style="font-size:32px;width:32px;height:32px;
                         color:var(--nx-text-3)">
          show_chart
        </mat-icon>
        <div style="font-size:13px;color:var(--nx-text-3);
                    margin-top:8px">
          Waiting for candle data from live feed
        </div>
      </div>
    </div>
  </div>

  <div class="nx-card">
    <span class="nx-label">PIVOT LEVEL TABLE</span>
    <div style="display:grid;
                grid-template-columns:repeat(auto-fit,
                minmax(110px,1fr));
                gap:8px;margin-top:8px">
      <div *ngFor="let level of pivotRows"
           style="background:var(--nx-bg-raised);
                  border-radius:8px;padding:10px;
                  border:0.5px solid"
           [style.border-color]="level.nearest
             ? 'var(--nx-accent)' : 'var(--nx-border)'">
        <div style="font-size:10px;color:var(--nx-text-3);
                    letter-spacing:.08em">
          {{level.label}}
        </div>
        <div style="font-size:16px;font-weight:600;
                    margin-top:4px"
             [style.color]="level.color">
          {{level.value || '-'}}
        </div>
      </div>
    </div>
  </div>

</div>
  `,
})
export class MarketChartComponent
  implements OnInit, AfterViewInit, OnDestroy {

  @ViewChild('chartHost')
  chartHostRef!: ElementRef<HTMLDivElement>;

  candles: ParsedCandle[] = [];
  latestCandle: ParsedCandle | null = null;
  selectedTf: Tf = '5m';
  timeframes: Tf[] = ['1m', '3m', '5m', '15m'];
  lastUpdated = 'never';
  showPaperMarkers = true;
  showSR = true;
  showVolume = true;
  pivotLevels: any = {};
  paperTrades: any[] = [];

  private chartApi: IChartApi | null = null;
  private candleSeries: ISeriesApi<'Candlestick'> | null = null;
  private volumeSeries: ISeriesApi<'Histogram'> | null = null;
  private priceLineRefs: any[] = [];
  private sub?: Subscription;
  private resizeObs?: ResizeObserver;

  get pivotRows(): any[] {
    const close = Number(this.latestCandle?.close || 0);
    const rows = [
      ['R3', this.pivotLevels.r3, 'var(--nx-danger)'],
      ['R2', this.pivotLevels.r2, 'var(--nx-danger)'],
      ['R1', this.pivotLevels.r1, 'var(--nx-danger)'],
      ['P', this.pivotLevels.p, 'var(--nx-cyan)'],
      ['S1', this.pivotLevels.s1, 'var(--nx-success)'],
      ['S2', this.pivotLevels.s2, 'var(--nx-success)'],
      ['S3', this.pivotLevels.s3, 'var(--nx-success)'],
    ];
    const nearest = rows.reduce((best, row) => {
      const value = Number(row[1]);
      if (!close || !value) return best;
      const dist = Math.abs(close - value);
      return !best || dist < best.dist
        ? { label: row[0], dist }
        : best;
    }, null as any);
    return rows.map(([label, value, color]) => ({
      label,
      value,
      color,
      nearest: nearest?.label === label,
    }));
  }

  constructor(private http: HttpClient) {}

  ngAfterViewInit() { this.initChart(); }

  ngOnInit() {
    this.sub = interval(15000).pipe(
      startWith(0),
      switchMap(() => this.loadChartData())
    ).subscribe(({ candleData, openTrades, closedTrades }) => {
      const raw = candleData?.candles
        || candleData?.items
        || candleData
        || [];
      this.candles = this.parseCandles(raw);
      this.latestCandle = this.candles.at(-1) ?? null;
      this.paperTrades = [
        ...(openTrades?.items || openTrades?.trades || []),
        ...(closedTrades?.items || closedTrades?.trades || []),
      ];
      this.pivotLevels = this.calculatePivots(this.candles);
      this.renderCandles();
      this.lastUpdated = new Date().toLocaleTimeString(
        'en-IN', { timeZone: 'Asia/Kolkata' });
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
    this.resizeObs?.disconnect();
    this.chartApi?.remove();
  }

  initChart() {
    if (!this.chartHostRef?.nativeElement || this.chartApi) return;
    const el = this.chartHostRef.nativeElement;

    this.chartApi = createChart(el, {
      width: el.clientWidth || 800,
      height: 430,
      layout: {
        background: { color: '#0b1220' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30,41,59,.75)' },
        horzLines: { color: 'rgba(30,41,59,.75)' },
      },
      crosshair: {
        vertLine: {
          color: '#475569',
          labelBackgroundColor: '#1e293b',
        },
        horzLine: {
          color: '#475569',
          labelBackgroundColor: '#1e293b',
        },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
    });

    this.candleSeries =
      this.chartApi.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      });

    this.volumeSeries = this.chartApi.addHistogramSeries({
      color: 'rgba(99,102,241,.35)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    this.volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    this.resizeObs = new ResizeObserver(() => {
      if (this.chartApi && el.clientWidth > 0) {
        this.chartApi.applyOptions({ width: el.clientWidth });
      }
    });
    this.resizeObs.observe(el);
  }

  loadChartData() {
    return forkJoin({
      candleData: this.http.get<any>(
        `/api/live-monitor/candles/NIFTY` +
        `?timeframe=${this.selectedTf}&limit=200`
      ).pipe(catchError(() => of(null))),
      openTrades: this.http.get<any>('/api/live-paper/open-trades')
        .pipe(catchError(() => of(null))),
      closedTrades: this.http.get<any>('/api/live-paper/closed-trades')
        .pipe(catchError(() => of(null))),
    });
  }

  parseCandles(raw: any[]): ParsedCandle[] {
    return (Array.isArray(raw) ? raw : [])
      .filter(c => c && (c.time || c.timestamp || c.open_time || c.start_time))
      .map(c => {
        let time = c.time || c.timestamp || c.open_time || c.start_time;
        if (typeof time === 'string') {
          time = Math.floor(new Date(time).getTime() / 1000);
        }
        return {
          time: time as any,
          open: Number(c.open ?? c.o ?? 0),
          high: Number(c.high ?? c.h ?? 0),
          low: Number(c.low ?? c.l ?? 0),
          close: Number(c.close ?? c.c ?? 0),
          volume: Number(c.volume ?? c.v ?? 0),
          tickCount: Number(c.tick_count ?? c.tickCount ?? 0),
        };
      })
      .filter(c =>
        Number(c.time) > 0 &&
        Number.isFinite(c.open) &&
        Number.isFinite(c.high) &&
        Number.isFinite(c.low) &&
        Number.isFinite(c.close) &&
        c.open > 0 &&
        c.high > 0 &&
        c.low > 0 &&
        c.close > 0)
      .sort((a, b) => Number(a.time) - Number(b.time));
  }

  renderCandles() {
    if (!this.candleSeries || !this.volumeSeries) return;
    this.candleSeries.setData(this.candles);
    const volumeData: HistogramData[] = this.candles.map(c => {
      const value = Number(c.volume || c.tickCount || 0);
      return {
        time: c.time,
        value: this.showVolume ? value : 0,
        color: c.close >= c.open
          ? 'rgba(16,185,129,.35)'
          : 'rgba(239,68,68,.35)',
      };
    });
    this.volumeSeries.setData(volumeData);
    this.applyPriceLines();
    this.applyMarkers();
    this.chartApi?.timeScale().fitContent();
  }

  applyPriceLines() {
    if (!this.candleSeries) return;
    for (const line of this.priceLineRefs) {
      this.candleSeries.removePriceLine(line);
    }
    this.priceLineRefs = [];
    if (!this.showSR) return;
    const lines = [
      { price: this.pivotLevels.p, title: 'P', color: '#06b6d4' },
      { price: this.pivotLevels.s1, title: 'S1', color: '#10b981' },
      { price: this.pivotLevels.s2, title: 'S2', color: '#10b981' },
      { price: this.pivotLevels.r1, title: 'R1', color: '#ef4444' },
      { price: this.pivotLevels.r2, title: 'R2', color: '#ef4444' },
    ];
    for (const line of lines) {
      if (!line.price) continue;
      this.priceLineRefs.push(
        this.candleSeries.createPriceLine({
          price: Number(line.price),
          color: line.color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: line.title,
        })
      );
    }
  }

  applyMarkers() {
    if (!this.candleSeries) return;
    if (!this.showPaperMarkers || !this.paperTrades.length) {
      this.candleSeries.setMarkers([]);
      return;
    }
    const times = this.candles.map(c => Number(c.time));
    const markers = this.paperTrades
      .map((trade: any) => {
        const rawTime = trade.entryTime || trade.entry_time ||
          trade.exitTime || trade.exit_time;
        const chartTime = this.nearestTime(rawTime, times);
        if (!chartTime) return null;
        const isExit = Boolean(trade.exitTime || trade.exit_time);
        const isPut = String(
          trade.signalType || trade.signal_type || ''
        ).includes('PUT');
        const pnl = Number(
          trade.realizedPnl ?? trade.net_pnl ?? trade.pnl ?? 0
        );
        return {
          time: chartTime as any,
          position: isExit ? 'aboveBar' : 'belowBar',
          color: isExit
            ? (pnl >= 0 ? '#10b981' : '#ef4444')
            : (isPut ? '#ef4444' : '#10b981'),
          shape: isExit ? 'arrowDown' : 'arrowUp',
          text: isExit
            ? (pnl >= 0 ? 'TARGET' : 'SL')
            : (isPut ? 'PE' : 'CE'),
        };
      })
      .filter(Boolean) as any[];
    this.candleSeries.setMarkers(
      markers.sort((a, b) => Number(a.time) - Number(b.time))
    );
  }

  calculatePivots(candles: ParsedCandle[]) {
    if (!candles.length) return {};
    const last = candles.at(-2) || candles.at(-1)!;
    const high = Number(last.high);
    const low = Number(last.low);
    const close = Number(last.close);
    const p = (high + low + close) / 3;
    const r1 = 2 * p - low;
    const s1 = 2 * p - high;
    const r2 = p + (high - low);
    const s2 = p - (high - low);
    const r3 = high + 2 * (p - low);
    const s3 = low - 2 * (high - p);
    const round = (v: number) => Math.round(v * 100) / 100;
    return {
      p: round(p),
      r1: round(r1),
      r2: round(r2),
      r3: round(r3),
      s1: round(s1),
      s2: round(s2),
      s3: round(s3),
    };
  }

  nearestTime(raw: string | undefined, times: number[]): number | null {
    if (!raw || !times.length) return null;
    const target = Math.floor(new Date(raw).getTime() / 1000);
    if (!Number.isFinite(target)) return null;
    return times.reduce((best, time) =>
      Math.abs(time - target) < Math.abs(best - target)
        ? time
        : best,
      times[0]);
  }

  onTfChange(tf: Tf) {
    this.selectedTf = tf;
    this.candles = [];
    this.refresh();
  }

  refresh() {
    this.loadChartData().subscribe(data => {
      const raw = data.candleData?.candles
        || data.candleData?.items
        || data.candleData
        || [];
      this.candles = this.parseCandles(raw);
      this.latestCandle = this.candles.at(-1) ?? null;
      this.paperTrades = [
        ...(data.openTrades?.items || data.openTrades?.trades || []),
        ...(data.closedTrades?.items || data.closedTrades?.trades || []),
      ];
      this.pivotLevels = this.calculatePivots(this.candles);
      this.renderCandles();
      this.lastUpdated = new Date().toLocaleTimeString(
        'en-IN', { timeZone: 'Asia/Kolkata' });
    });
  }

  toggleMarkers() {
    this.showPaperMarkers = !this.showPaperMarkers;
    this.applyMarkers();
  }

  toggleSR() {
    this.showSR = !this.showSR;
    this.applyPriceLines();
  }

  toggleVolume() {
    this.showVolume = !this.showVolume;
    this.renderCandles();
  }
}
