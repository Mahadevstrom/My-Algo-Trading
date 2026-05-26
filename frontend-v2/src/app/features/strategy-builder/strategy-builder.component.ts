import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTabsModule } from '@angular/material/tabs';
import { catchError, of } from 'rxjs';

@Component({
  selector: 'app-strategy-builder',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatSelectModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatTabsModule
  ],
  template: `
<div style="max-width:1600px;margin:0 auto;display:flex;gap:20px;flex-wrap:wrap">

  <!-- Left Sidebar: Saved Strategies List -->
  <div style="flex: 0 0 350px; min-width:300px">
    <div class="nx-card" style="height: calc(100vh - 120px); display:flex; flex-direction:column">
      
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
        <span class="nx-label">MY CUSTOM ALGOS</span>
        <button mat-flat-button (click)="resetWizard()" style="background:var(--nx-accent); color:#fff; font-size:11px; height:28px; line-height:28px">
          <mat-icon style="font-size:14px; width:14px; height:14px">add</mat-icon> New
        </button>
      </div>

      <div style="margin-bottom:12px">
        <mat-form-field appearance="outline" style="width:100%" class="compact-form">
          <input matInput [(ngModel)]="searchQuery" placeholder="Search saved strategies..." (ngModelChange)="filterStrategies()">
          <mat-icon matSuffix style="color:var(--nx-text-3)">search</mat-icon>
        </mat-form-field>
      </div>

      <div style="flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:8px" class="custom-scroll">
        <div *ngFor="let strat of filteredStrategies" 
             (click)="loadStrategy(strat)"
             [style.background]="selectedStrategyId === strat.id ? 'var(--nx-accent-dim)' : 'var(--nx-bg-raised)'"
             [style.border-color]="selectedStrategyId === strat.id ? 'var(--nx-accent)' : 'var(--nx-border)'"
             style="border: 0.5px solid var(--nx-border); border-radius:8px; padding:12px; cursor:pointer; position:relative; transition:all .15s">
          
          <div style="display:flex; justify-content:space-between; align-items:flex-start">
            <span style="font-size:13px; font-weight:600; color:var(--nx-text-1)">{{strat.name}}</span>
            <button mat-icon-button (click)="deleteStrategy(strat.id); $event.stopPropagation()" style="width:24px; height:24px; color:var(--nx-text-3)" class="small-delete">
              <mat-icon style="font-size:14px; width:14px; height:14px">delete</mat-icon>
            </button>
          </div>
          
          <p style="font-size:11px; color:var(--nx-text-3); margin:4px 0 0; line-height:1.4">
            {{strat.description || 'No description provided.'}}
          </p>

          <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:8px">
            <span class="nx-chip nx-chip-neutral" style="font-size:9px; padding:2px 6px">
              LB: {{strat.config.momentum_lookback_candles}}c
            </span>
            <span *ngIf="strat.config.use_volume_threshold" class="nx-chip nx-chip-ok" style="font-size:9px; padding:2px 6px">
              Vol SMA
            </span>
            <span *ngIf="strat.config.use_pcr_bias" class="nx-chip nx-chip-warn" style="font-size:9px; padding:2px 6px">
              PCR Bias
            </span>
          </div>

        </div>

        <div *ngIf="filteredStrategies.length === 0" style="text-align:center; padding:32px 0; color:var(--nx-text-3); font-size:12px">
          <mat-icon style="font-size:24px; width:24px; height:24px; margin-bottom:6px">construction</mat-icon>
          <p>No algos found</p>
        </div>
      </div>

    </div>
  </div>

  <!-- Right Content Area: Wizard and Backtester tabs -->
  <div style="flex: 1 1 600px">
    
    <div style="margin-bottom:20px">
      <p class="nx-label">STRATEGY BUILDER</p>
      <h1 style="font-size:22px; font-weight:500; color:var(--nx-text-1); margin:0">
        MyAlgo Strategy Wizard
      </h1>
      <p style="font-size:12px; color:var(--nx-text-3); margin:4px 0 0">
        Define custom momentum breakout, volume sma, option PCR bias trigger criteria, and premium profit goals.
      </p>
    </div>

    <!-- Banner strip -->
    <div style="background:rgba(124,58,237,.06); border:0.5px solid rgba(124,58,237,.3); border-radius:8px; padding:10px 16px; font-size:11px; color:var(--nx-accent); margin-bottom:16px; display:flex; gap:16px; flex-wrap:wrap">
      <span>STRATEGY BUILDER COCKPIT</span>
      <span>AUTOMATED SCHEMAS EXPOSURE</span>
      <span>PAPER-REPLAY INTEGRATION</span>
    </div>

    <mat-tab-group color="accent" animationDuration="150ms">
      
      <!-- Wizard tab -->
      <mat-tab label="Builder Wizard">
        <div style="padding-top:16px; display:flex; flex-direction:column; gap:16px">
          
          <!-- Step 1: Meta -->
          <div class="nx-card">
            <span class="nx-label">STEP 1: ALGO DESCRIPTION</span>
            <div style="display:grid; grid-template-columns:1fr; gap:12px; margin-top:10px">
              <mat-form-field appearance="outline" style="width:100%">
                <mat-label>Strategy Name</mat-label>
                <input matInput [(ngModel)]="strategyName" placeholder="e.g. NIFTY OI Momentum Breakout">
              </mat-form-field>
              
              <mat-form-field appearance="outline" style="width:100%">
                <mat-label>Short Description</mat-label>
                <textarea matInput [(ngModel)]="strategyDesc" placeholder="e.g. Breaks spot lookback with momentum, filtered by volume and option Put-Call Ratio PCR."></textarea>
              </mat-form-field>
            </div>
          </div>

          <!-- Step 2: Breakout -->
          <div class="nx-card">
            <span class="nx-label">STEP 2: SPOT MOMENTUM CROSSOVER / BREAKOUT</span>
            <p style="font-size:11px; color:var(--nx-text-3); margin:4px 0 8px">
              Triggers a signal when spot close breaks lookback high/low with positive/negative momentum offset.
            </p>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:8px">
              <mat-form-field appearance="outline">
                <mat-label>Momentum Lookback Candles</mat-label>
                <input matInput type="number" [(ngModel)]="config.momentum_lookback_candles" min="1" max="20">
              </mat-form-field>
              
              <mat-form-field appearance="outline">
                <mat-label>Momentum Threshold (Offset)</mat-label>
                <input matInput type="number" [(ngModel)]="config.momentum_threshold" step="0.5">
              </mat-form-field>
            </div>
          </div>

          <!-- Step 3: Filters -->
          <div class="nx-card">
            <span class="nx-label">STEP 3: INTEL FILTERS (VOLUME & PCR)</span>
            
            <div style="border-bottom: 0.5px solid var(--nx-border); padding-bottom:12px; margin-bottom:12px; margin-top:10px">
              <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:var(--nx-text-1); cursor:pointer">
                <input type="checkbox" [(ngModel)]="config.use_volume_threshold">
                Enable Volume SMA Crossover Filter
              </label>
              <div *ngIf="config.use_volume_threshold" style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:10px">
                <mat-form-field appearance="outline">
                  <mat-label>Volume SMA Lookback</mat-label>
                  <input matInput type="number" [(ngModel)]="config.volume_sma_lookback" min="3" max="50">
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Volume Multiplier (x SMA)</mat-label>
                  <input matInput type="number" [(ngModel)]="config.volume_multiplier" step="0.1" min="1.0" max="5.0">
                </mat-form-field>
              </div>
            </div>

            <div>
              <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:var(--nx-text-1); cursor:pointer">
                <input type="checkbox" [(ngModel)]="config.use_pcr_bias">
                Enable Option Chain PCR Bias filter
              </label>
              <div *ngIf="config.use_pcr_bias" style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:10px">
                <mat-form-field appearance="outline">
                  <mat-label>Bullish PCR threshold (CE entry)</mat-label>
                  <input matInput type="number" [(ngModel)]="config.pcr_bullish_threshold" step="0.05">
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Bearish PCR threshold (PE entry)</mat-label>
                  <input matInput type="number" [(ngModel)]="config.pcr_bearish_threshold" step="0.05">
                </mat-form-field>
              </div>
            </div>

          </div>

          <!-- Step 4: Targets -->
          <div class="nx-card">
            <span class="nx-label">STEP 4: OPTION PREMIUM STOP LOSS & PROFIT GOALS</span>
            <p style="font-size:11px; color:var(--nx-text-3); margin:4px 0 10px">
              Configures custom percentage values applied directly to the option entry premium.
            </p>
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px">
              <mat-form-field appearance="outline">
                <mat-label>Stop Loss %</mat-label>
                <input matInput type="number" [(ngModel)]="config.stop_loss_pct" min="5" max="50">
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Target 1 %</mat-label>
                <input matInput type="number" [(ngModel)]="config.target_1_pct" min="10" max="150">
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Target 2 %</mat-label>
                <input matInput type="number" [(ngModel)]="config.target_2_pct" min="20" max="300">
              </mat-form-field>
            </div>
          </div>

          <!-- Buttons -->
          <div style="display:flex; gap:10px; margin-top:8px">
            <button mat-flat-button (click)="saveStrategy()" style="background:var(--nx-accent); color:#fff; flex:1">
              <mat-icon>save</mat-icon> Save Strategy
            </button>
            <button mat-stroked-button (click)="resetWizard()" style="color:var(--nx-text-2); width:120px">
              Reset
            </button>
          </div>

        </div>
      </mat-tab>

      <!-- Backtest tab -->
      <mat-tab label="Backtest & Research Lab">
        <div style="padding-top:16px; display:flex; flex-direction:column; gap:16px">
          
          <div class="nx-card">
            <span class="nx-label">BACKTEST PARAMETERS</span>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; margin-top:10px">
              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Underlying</mat-label>
                <mat-select [(ngModel)]="backtestParams.underlying">
                  <mat-option value="NIFTY">NIFTY</mat-option>
                  <mat-option value="BANKNIFTY">BANKNIFTY</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Expiry</mat-label>
                <input matInput [(ngModel)]="backtestParams.expiry" placeholder="YYYY-MM-DD">
              </mat-form-field>

              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Interval</mat-label>
                <mat-select [(ngModel)]="backtestParams.interval">
                  <mat-option value="5">5m</mat-option>
                  <mat-option value="15">15m</mat-option>
                  <mat-option value="60">60m</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>From Date</mat-label>
                <input matInput [(ngModel)]="backtestParams.from_date" placeholder="YYYY-MM-DD">
              </mat-form-field>

              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>To Date</mat-label>
                <input matInput [(ngModel)]="backtestParams.to_date" placeholder="YYYY-MM-DD">
              </mat-form-field>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:6px">
              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Lot Size</mat-label>
                <input matInput type="number" [(ngModel)]="backtestParams.lot_size">
              </mat-form-field>
              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Capital (INR)</mat-label>
                <input matInput type="number" [(ngModel)]="backtestParams.initial_capital">
              </mat-form-field>
            </div>

            <button mat-flat-button (click)="runBacktest()" 
                    [disabled]="backtesting"
                    style="background:var(--nx-success); color:#fff; width:100%; margin-top:8px; font-weight:600">
              <mat-icon>play_circle</mat-icon> RUN STRATEGY BACKTEST
            </button>
            <mat-progress-bar *ngIf="backtesting" mode="indeterminate" color="accent" style="margin-top:10px"></mat-progress-bar>
          </div>

          <!-- Alert message -->
          <div *ngIf="backtestError" class="nx-card" style="background:rgba(239,68,68,.06); border:0.5px solid rgba(239,68,68,.3); color:#ef4444; font-size:12px">
            <mat-icon style="font-size:16px; width:16px; height:16px; vertical-align:middle; margin-right:4px">error</mat-icon>
            {{backtestError}}
          </div>

          <!-- Backtest results -->
          <div *ngIf="backtestResult" class="nx-card">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:0.5px solid var(--nx-border); padding-bottom:8px; margin-bottom:12px">
              <span class="nx-label">BACKTEST PERFORMANCE REPORT</span>
              <span class="nx-chip nx-chip-ok" style="font-size:10px">
                MODE: {{backtestResult.metrics.option_chain_replay_mode || 'DISABLED'}}
              </span>
            </div>

            <div style="font-size:11px; color:var(--nx-text-3); background:var(--nx-bg-raised); border-radius:8px; padding:10px; margin-bottom:14px; line-height:1.4">
              <strong>Engine Note:</strong> {{backtestResult.metrics.replay_note || 'Standard execution.'}}
            </div>

            <!-- Stats row -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px">
              
              <div style="background:var(--nx-bg-raised); border-radius:8px; padding:12px; text-align:center">
                <div style="font-size:10px; color:var(--nx-text-3)">Net P&L (INR)</div>
                <div style="font-size:22px; font-weight:700; margin-top:4px" 
                     [style.color]="backtestResult.metrics.net_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                  {{backtestResult.metrics.net_pnl >= 0 ? '+' : ''}}{{backtestResult.metrics.net_pnl}}
                </div>
              </div>

              <div style="background:var(--nx-bg-raised); border-radius:8px; padding:12px; text-align:center">
                <div style="font-size:10px; color:var(--nx-text-3)">Win Rate %</div>
                <div style="font-size:22px; font-weight:700; color:var(--nx-text-1); margin-top:4px">
                  {{backtestResult.metrics.win_rate}}%
                </div>
              </div>

              <div style="background:var(--nx-bg-raised); border-radius:8px; padding:12px; text-align:center">
                <div style="font-size:10px; color:var(--nx-text-3)">Total Trades</div>
                <div style="font-size:22px; font-weight:700; color:var(--nx-text-1); margin-top:4px">
                  {{backtestResult.metrics.total_trades}}
                </div>
              </div>

              <div style="background:var(--nx-bg-raised); border-radius:8px; padding:12px; text-align:center">
                <div style="font-size:10px; color:var(--nx-text-3)">Max Drawdown</div>
                <div style="font-size:22px; font-weight:700; color:var(--nx-danger); margin-top:4px">
                  {{backtestResult.metrics.max_drawdown}}
                </div>
              </div>

            </div>

            <!-- List of Trades -->
            <div style="margin-top:16px">
              <span class="nx-label">TRADE LOG TIMELINE</span>
              <div style="margin-top:8px; max-height:220px; overflow-y:auto" class="custom-scroll">
                <table style="width:100%; border-collapse:collapse; font-size:12px">
                  <thead>
                    <tr style="text-align:left; border-bottom:0.5px solid var(--nx-border)">
                      <th style="padding:6px 0; color:var(--nx-text-3)">Type</th>
                      <th style="padding:6px 0; color:var(--nx-text-3)">Entry Time</th>
                      <th style="padding:6px 0; color:var(--nx-text-3)">Exit Reason</th>
                      <th style="padding:6px 0; color:var(--nx-text-3); text-align:right">Net P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr *ngFor="let trade of backtestResult.trades" style="border-bottom: 0.5px solid var(--nx-border)">
                      <td style="padding:8px 0; font-weight:600" [style.color]="trade.net_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                        {{trade.signal_type}}
                      </td>
                      <td style="padding:8px 0; color:var(--nx-text-2)">
                        {{trade.entry_time | date:'yyyy-MM-dd HH:mm'}}
                      </td>
                      <td style="padding:8px 0; color:var(--nx-text-3)">
                        {{trade.exit_reason || 'OPEN'}}
                      </td>
                      <td style="padding:8px 0; text-align:right; font-weight:600" [style.color]="trade.net_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                        INR {{trade.net_pnl | number:'1.0-2'}}
                      </td>
                    </tr>
                    <tr *ngIf="backtestResult.trades.length === 0">
                      <td colspan="4" style="text-align:center; padding:16px; color:var(--nx-text-3)">No signals generated in this period.</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

          </div>

          <!-- Empty state -->
          <div *ngIf="!backtestResult && !backtesting" class="nx-card" style="text-align:center; padding:48px 0">
            <mat-icon style="font-size:40px; width:40px; height:40px; color:var(--nx-text-3)">construction</mat-icon>
            <div style="font-size:13px; color:var(--nx-text-2); margin-top:12px">No Backtest Executed Yet</div>
            <div style="font-size:11px; color:var(--nx-text-3); margin-top:4px">
              Configure parameters above and click "Run Strategy Backtest" to evaluate.
            </div>
          </div>

        </div>
      </mat-tab>

    </mat-tab-group>

  </div>

</div>
  `,
  styles: [`
    .compact-form ::ng-deep .mat-mdc-text-field-wrapper {
      height: 38px !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
    }
    .compact-form ::ng-deep .mat-mdc-form-field-flex {
      height: 38px !important;
      align-items: center !important;
    }
    .compact-form ::ng-deep .mat-mdc-form-field-infix {
      padding-top: 8px !important;
      padding-bottom: 8px !important;
    }
    .custom-scroll::-webkit-scrollbar {
      width: 4px;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: var(--nx-border);
      border-radius: 4px;
    }
    .small-delete:hover {
      color: var(--nx-danger) !important;
    }
  `]
})
export class StrategyBuilderComponent implements OnInit {
  strategies: any[] = [];
  filteredStrategies: any[] = [];
  selectedStrategyId: number | null = null;
  searchQuery = '';

  // Form Fields
  strategyName = '';
  strategyDesc = '';
  config = {
    momentum_lookback_candles: 3,
    momentum_threshold: 0.0,
    use_volume_threshold: false,
    volume_sma_lookback: 10,
    volume_multiplier: 1.2,
    use_pcr_bias: false,
    pcr_bullish_threshold: 0.9,
    pcr_bearish_threshold: 0.7,
    stop_loss_pct: 20,
    target_1_pct: 30,
    target_2_pct: 40
  };

  // Backtester Parameters
  backtestParams = {
    underlying: 'NIFTY',
    expiry: '2026-05-28',
    interval: '5',
    from_date: '2026-05-01',
    to_date: '2026-05-23',
    initial_capital: 100000,
    max_risk_per_trade: 5.0,
    lot_size: 50
  };

  backtesting = false;
  backtestResult: any = null;
  backtestError: string | null = null;

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.loadStrategies();
  }

  loadStrategies() {
    this.http.get<any[]>('/api/strategies')
      .pipe(catchError(() => of([])))
      .subscribe(res => {
        this.strategies = res;
        this.filterStrategies();
      });
  }

  filterStrategies() {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) {
      this.filteredStrategies = this.strategies;
    } else {
      this.filteredStrategies = this.strategies.filter(s => 
        s.name.toLowerCase().includes(q) || 
        (s.description && s.description.toLowerCase().includes(q))
      );
    }
  }

  loadStrategy(strat: any) {
    this.selectedStrategyId = strat.id;
    this.strategyName = strat.name;
    this.strategyDesc = strat.description || '';
    this.config = { ...strat.config };
  }

  resetWizard() {
    this.selectedStrategyId = null;
    this.strategyName = '';
    this.strategyDesc = '';
    this.config = {
      momentum_lookback_candles: 3,
      momentum_threshold: 0.0,
      use_volume_threshold: false,
      volume_sma_lookback: 10,
      volume_multiplier: 1.2,
      use_pcr_bias: false,
      pcr_bullish_threshold: 0.9,
      pcr_bearish_threshold: 0.7,
      stop_loss_pct: 20,
      target_1_pct: 30,
      target_2_pct: 40
    };
    this.backtestResult = null;
    this.backtestError = null;
  }

  saveStrategy() {
    if (!this.strategyName.trim()) {
      alert('Strategy name is required!');
      return;
    }
    const payload = {
      name: this.strategyName,
      description: this.strategyDesc,
      config: this.config
    };

    if (this.selectedStrategyId) {
      // Edit
      this.http.put<any>(`/api/strategies/${this.selectedStrategyId}`, payload)
        .subscribe(res => {
          this.loadStrategies();
          alert('Strategy updated successfully!');
        });
    } else {
      // Create
      this.http.post<any>('/api/strategies', payload)
        .subscribe(res => {
          this.loadStrategies();
          this.selectedStrategyId = res.id;
          alert('Strategy created successfully!');
        });
    }
  }

  deleteStrategy(id: number) {
    if (!confirm('Are you sure you want to delete this custom algo?')) return;
    this.http.delete<any>(`/api/strategies/${id}`)
      .subscribe(() => {
        if (this.selectedStrategyId === id) {
          this.resetWizard();
        }
        this.loadStrategies();
      });
  }

  runBacktest() {
    this.backtesting = true;
    this.backtestResult = null;
    this.backtestError = null;

    const payload = {
      name: this.strategyName || 'Ad-Hoc Backtest',
      ...this.backtestParams,
      strategy_config: this.config
    };

    this.http.post<any>('/api/backtest/run', payload)
      .pipe(catchError((err) => {
        this.backtestError = err?.error?.detail || 'Could not complete backtest run. Check parameters.';
        this.backtesting = false;
        return of(null);
      }))
      .subscribe(res => {
        this.backtesting = false;
        if (!res) return;
        if (!res.ok) {
          this.backtestError = res.message || 'Backtest failed.';
          return;
        }
        // Load the backtest metrics and trades!
        this.http.get<any>(`/api/backtest/runs/${res.run_id}/metrics`)
          .subscribe(metricsRes => {
            this.http.get<any>(`/api/backtest/runs/${res.run_id}/trades`)
              .subscribe(tradesRes => {
                this.backtestResult = {
                  metrics: metricsRes?.metrics || {},
                  trades: tradesRes?.items || []
                };
              });
          });
      });
  }
}
