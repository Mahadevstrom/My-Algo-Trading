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
import { NgxEchartsDirective } from 'ngx-echarts';
import { catchError, of } from 'rxjs';

@Component({
  selector: 'app-research-lab',
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
    MatTabsModule,
    NgxEchartsDirective
  ],
  template: `
<div style="max-width:1600px;margin:0 auto">

  <!-- Header Section -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">QUANT RESEARCH LAB</p>
      <h1 style="font-size:22px;font-weight:500;color:var(--nx-text-1);margin:0">
        Advanced Backtesting & Research Center
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);margin:4px 0 0">
        Perform grid search parameter optimizations and multi-window walk-forward out-of-sample validation.
      </p>
    </div>
    <div style="display:flex;gap:8px">
      <span class="nx-chip nx-chip-fail">READ ONLY</span>
      <span class="nx-chip nx-chip-paper">PAPER MODE ONLY</span>
    </div>
  </div>

  <div style="display:flex;gap:20px;flex-wrap:wrap">

    <!-- Left Controls Panel -->
    <div style="flex:1 1 450px;min-width:350px;display:flex;flex-direction:column;gap:16px">
      
      <!-- Base Parameters Card -->
      <div class="nx-card">
        <span class="nx-label">BASE BACKTEST CONFIGURATION</span>
        
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>Underlying Symbol</mat-label>
            <mat-select [(ngModel)]="baseParams.underlying">
              <mat-option value="NIFTY">NIFTY</mat-option>
              <mat-option value="BANKNIFTY">BANKNIFTY</mat-option>
            </mat-select>
          </mat-form-field>

          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>Expiry Date</mat-label>
            <input matInput [(ngModel)]="baseParams.expiry" placeholder="YYYY-MM-DD">
          </mat-form-field>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:4px">
          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>Interval</mat-label>
            <mat-select [(ngModel)]="baseParams.interval">
              <mat-option value="5">5m</mat-option>
              <mat-option value="15">15m</mat-option>
              <mat-option value="60">60m</mat-option>
            </mat-select>
          </mat-form-field>

          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>From Date</mat-label>
            <input matInput [(ngModel)]="baseParams.from_date" placeholder="YYYY-MM-DD">
          </mat-form-field>

          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>To Date</mat-label>
            <input matInput [(ngModel)]="baseParams.to_date" placeholder="YYYY-MM-DD">
          </mat-form-field>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:4px">
          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>Initial Capital (INR)</mat-label>
            <input matInput type="number" [(ngModel)]="baseParams.initial_capital">
          </mat-form-field>

          <mat-form-field appearance="outline" class="compact-form">
            <mat-label>Lot Size</mat-label>
            <input matInput type="number" [(ngModel)]="baseParams.lot_size">
          </mat-form-field>
        </div>

        <!-- Strategy Selection -->
        <div style="margin-top:4px">
          <mat-form-field appearance="outline" style="width:100%" class="compact-form">
            <mat-label>Base Custom Strategy Algo (Optional)</mat-label>
            <mat-select [(ngModel)]="selectedStrategyId" (selectionChange)="onStrategySelect()">
              <mat-option [value]="null">-- None (Use Hardcoded Breakouts) --</mat-option>
              <mat-option *ngFor="let strat of strategies" [value]="strat.id">
                {{strat.name}}
              </mat-option>
            </mat-select>
          </mat-form-field>
        </div>
      </div>

      <!-- Action Tabs (Optimizer vs Walk-Forward) -->
      <div class="nx-card">
        <mat-tab-group color="accent" animationDuration="150ms" (selectedTabChange)="onTabChange($event)">
          
          <!-- Optimizer Tab -->
          <mat-tab label="Grid Optimizer">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Executes in-memory cartesian grid searches to discover the optimal Stop-Loss and Target premium combination.
              </p>

              <div>
                <span class="nx-label" style="font-size:10px">STOP LOSS % RANGE (MIN / MAX / STEP)</span>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:6px">
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.slMin" placeholder="Min %">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.slMax" placeholder="Max %">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.slStep" placeholder="Step %">
                  </mat-form-field>
                </div>
              </div>

              <div>
                <span class="nx-label" style="font-size:10px">TARGET 1 % RANGE (MIN / MAX / STEP)</span>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:6px">
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.tgtMin" placeholder="Min %">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.tgtMax" placeholder="Max %">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <input matInput type="number" [(ngModel)]="optRanges.tgtStep" placeholder="Step %">
                  </mat-form-field>
                </div>
              </div>

              <div style="background:rgba(124,58,237,.06);border:0.5px solid rgba(124,58,237,.3);border-radius:6px;padding:8px 12px;font-size:11px;color:var(--nx-accent)">
                <strong>Grid combinations count:</strong> {{calculateCombinations()}} (Max: 100)
              </div>

              <button mat-flat-button (click)="runOptimization()" 
                      [disabled]="loading || calculateCombinations() > 100" 
                      style="background:var(--nx-success);color:#fff;font-weight:600">
                <mat-icon>science</mat-icon> RUN PARAMETER OPTIMIZATION
              </button>
            </div>
          </mat-tab>

          <!-- Walk-Forward Tab -->
          <mat-tab label="Walk-Forward Validation">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Validates strategy consistency by rolling sequential In-Sample (IS) and Out-of-Sample (OOS) windows to combat curve-fitting.
              </p>

              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>In-Sample Days (IS)</mat-label>
                  <input matInput type="number" [(ngModel)]="wfParams.in_sample_days" min="10" max="150">
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Out-of-Sample Days (OOS)</mat-label>
                  <input matInput type="number" [(ngModel)]="wfParams.out_of_sample_days" min="5" max="90">
                </mat-form-field>
              </div>

              <button mat-flat-button (click)="runWalkForward()" 
                      [disabled]="loading" 
                      style="background:var(--nx-accent);color:#fff;font-weight:600">
                <mat-icon>analytics</mat-icon> EXECUTE WALK-FORWARD RUN
              </button>
            </div>
          </mat-tab>
          <!-- Data Analytics & Distributions Tab -->
          <mat-tab label="Data Analytics & Distributions">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Calculate historical trade distributions and advanced quantitative metrics (Sharpe, Max Drawdown).
              </p>

              <button mat-flat-button (click)="runAnalytics()" 
                      [disabled]="loadingAnalytics" 
                      style="background:var(--nx-success);color:#fff;font-weight:600">
                <mat-icon>insights</mat-icon> RUN QUANTITATIVE ANALYTICS
              </button>
            </div>
          </mat-tab>

          <!-- Market Regimes (ML) Tab -->
          <mat-tab label="Market Regimes (ML)">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Ingest historical database candles and execute an unsupervised K-Means clustering algorithm to classify current volatility regimes (Bullish, Bearish, or Chop).
              </p>

              <button mat-flat-button (click)="runRegimeAnalysis()" 
                      [disabled]="loadingRegime" 
                      style="background:var(--nx-accent);color:#fff;font-weight:600">
                <mat-icon>psychology</mat-icon> TRAIN & CLASSIFY REGIMES
              </button>
            </div>
          </mat-tab>

          <!-- Monte Carlo Tab -->
          <mat-tab label="Monte Carlo Stress-Testing">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Run randomized simulations (Historical Bootstrapping or Parametric Win/Loss) to measure system robustness, probability of ruin, and worst-case drawdown distributions.
              </p>

              <mat-form-field appearance="outline" class="compact-form">
                <mat-label>Simulation Source</mat-label>
                <mat-select [(ngModel)]="mcParams.source">
                  <mat-option value="custom">Custom Parameters (Parametric)</mat-option>
                  <mat-option value="historical">Historical Paper Trades (Bootstrap)</mat-option>
                </mat-select>
              </mat-form-field>

              <div *ngIf="mcParams.source === 'custom'" style="display:flex;flex-direction:column;gap:10px">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Expected Win Rate %</mat-label>
                    <input matInput type="number" [(ngModel)]="mcParams.win_rate">
                  </mat-form-field>

                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Avg Win (INR)</mat-label>
                    <input matInput type="number" [(ngModel)]="mcParams.avg_win">
                  </mat-form-field>
                </div>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Avg Loss (INR)</mat-label>
                  <input matInput type="number" [(ngModel)]="mcParams.avg_loss">
                </mat-form-field>
              </div>

              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Capital (INR)</mat-label>
                  <input matInput type="number" [(ngModel)]="mcParams.initial_capital">
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Ruin Threshold (% Drawdown)</mat-label>
                  <input matInput type="number" [(ngModel)]="mcParams.ruin_threshold_pct">
                </mat-form-field>
              </div>

              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Num Simulations</mat-label>
                  <mat-select [(ngModel)]="mcParams.num_simulations">
                    <mat-option [value]="1000">1,000 runs</mat-option>
                    <mat-option [value]="2000">2,000 runs</mat-option>
                    <mat-option [value]="5000">5,000 runs</mat-option>
                  </mat-select>
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Trades per Simulation</mat-label>
                  <input matInput type="number" [(ngModel)]="mcParams.num_trades_per_run">
                </mat-form-field>
              </div>

              <button mat-flat-button (click)="runMonteCarlo()" 
                      [disabled]="loadingMC" 
                      style="background:var(--nx-success);color:#fff;font-weight:600">
                <mat-icon>casino</mat-icon> RUN MONTE CARLO STRESS-TEST
              </button>
            </div>
          </mat-tab>


          <!-- Historical Downloader Tab -->
          <mat-tab label="Historical Downloader">
            <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
              <p style="font-size:11px;color:var(--nx-text-3);margin:0;line-height:1.4">
                Fetch and store historical daily or intraday OHLC candles directly from Dhan API servers into your local database.
              </p>

              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Download Mode</mat-label>
                  <mat-select [(ngModel)]="downloadMode" (selectionChange)="onDownloadModeChange()">
                    <mat-option value="intraday">Intraday</mat-option>
                    <mat-option value="daily">Daily</mat-option>
                  </mat-select>
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>Symbol</mat-label>
                  <input matInput [(ngModel)]="downloadParams.symbol" placeholder="e.g. NIFTY">
                </mat-form-field>
              </div>

              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
                <mat-form-field appearance="outline" class="compact-form" [style.opacity]="downloadMode === 'daily' ? 0.5 : 1">
                  <mat-label>Interval</mat-label>
                  <mat-select [(ngModel)]="downloadParams.interval" [disabled]="downloadMode === 'daily'">
                    <mat-option value="1">1m</mat-option>
                    <mat-option value="5">5m</mat-option>
                    <mat-option value="15">15m</mat-option>
                    <mat-option value="25">25m</mat-option>
                    <mat-option value="60">60m</mat-option>
                  </mat-select>
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>From Date</mat-label>
                  <input matInput [(ngModel)]="downloadParams.from_date" placeholder="YYYY-MM-DD">
                </mat-form-field>

                <mat-form-field appearance="outline" class="compact-form">
                  <mat-label>To Date</mat-label>
                  <input matInput [(ngModel)]="downloadParams.to_date" placeholder="YYYY-MM-DD">
                </mat-form-field>
              </div>

                  <button mat-flat-button (click)="runDownload()" 
                      [disabled]="downloading || !downloadParams.symbol" 
                      style="background:var(--nx-accent);color:#fff;font-weight:600">
                <mat-icon>cloud_download</mat-icon> TRIGGER HISTORICAL DATA INGESTION
              </button>

              <!-- Gap Diagnostic Trigger -->
              <div style="border-top:1px solid var(--nx-border);padding-top:14px;margin-top:10px;display:flex;flex-direction:column;gap:10px">
                <span class="nx-label" style="font-size:10px">DATA QUALITY & GAP DIAGNOSTICS</span>
                <button mat-stroked-button (click)="scanDataGaps()" [disabled]="scanningGaps || !downloadParams.symbol" style="color:var(--nx-accent)">
                  <mat-icon *ngIf="!scanningGaps">radar</mat-icon>
                  <mat-icon *ngIf="scanningGaps" class="spin">sync</mat-icon>
                  SCAN FOR DATABASE DATA GAPS
                </button>
              </div>
            </div>
          </mat-tab>
        </mat-tab-group>

        <!-- Progress Indicator -->
        <mat-progress-bar *ngIf="loading" mode="indeterminate" color="accent" style="margin-top:16px"></mat-progress-bar>
      </div>

      <!-- Error Alert -->
      <div *ngIf="errorMsg" class="nx-card" style="background:rgba(239,68,68,.06);border:0.5px solid rgba(239,68,68,.3);color:#ef4444;font-size:12px">
        <mat-icon style="font-size:16px;width:16px;height:16px;vertical-align:middle;margin-right:4px">error</mat-icon>
        {{errorMsg}}
      </div>
    </div>

    <!-- Right Results Panel -->
    <div style="flex:1.5 1 600px;min-width:400px">
      
      <!-- EMPTY STATE -->
      <div *ngIf="!loading && !loadingAnalytics && !optimizationResult && !walkForwardResult && !analyticsResult && activeTab !== 'Historical Downloader' && activeTab !== 'Market Regimes (ML)' && activeTab !== 'Monte Carlo Stress-Testing'" class="nx-card" style="height:100%;min-height:450px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:48px 0">
        <mat-icon style="font-size:48px;width:48px;height:48px;color:var(--nx-text-3);margin-bottom:16px">radar</mat-icon>
        <div style="font-size:14px;color:var(--nx-text-2);font-weight:600">Quant Research Engine Idle</div>
        <div style="font-size:12px;color:var(--nx-text-3);margin-top:4px;max-width:320px;line-height:1.4">
          Configure underlying variables and trigger a multi-grid parameter optimization or walk-forward validation on the left.
        </div>
      </div>

      <!-- OPTIMIZATION RESULTS VIEW -->
      <div *ngIf="optimizationResult as res" style="display:flex;flex-direction:column;gap:16px">
        
        <!-- Optimal Parameters Trophy Card -->
        <div class="nx-card" style="background:linear-gradient(135deg, rgba(16,185,129,0.06), rgba(245,158,11,0.04));border-left:4px solid #f59e0b">
          <div style="display:flex;align-items:center;gap:12px">
            <mat-icon style="font-size:32px;width:32px;height:32px;color:#f59e0b">emoji_events</mat-icon>
            <div>
              <span class="nx-label" style="color:#f59e0b;font-weight:600">OPTIMAL PERFORMANCE RECOMMENDATION</span>
              <h2 style="font-size:18px;font-weight:700;color:var(--nx-text-1);margin:4px 0 0">
                Stop-Loss: {{res.optimal?.stop_loss_pct}}% &nbsp;·&nbsp; Target: {{res.optimal?.target_1_pct}}%
              </h2>
            </div>
            <div style="margin-left:auto;text-align:right">
              <span class="nx-label">NET PROFIT</span>
              <div style="font-size:20px;font-weight:700;color:var(--nx-success)">
                +INR {{res.optimal?.net_pnl | number:'1.0-0'}}
              </div>
            </div>
          </div>
          
          <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:10px;margin-top:14px;border-top:0.5px solid var(--nx-border);padding-top:12px">
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">WIN RATE</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.optimal?.win_rate | number:'1.0-1'}}%</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">PROFIT FACTOR</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.optimal?.profit_factor | number:'1.2-2'}}</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">MAX DRAWDOWN</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-danger)">{{res.optimal?.max_drawdown | number:'1.0-1'}}%</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">SHARPE RATIO</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.optimal?.sharpe_ratio | number:'1.2-2'}}</div>
            </div>
          </div>
        </div>

        <!-- Matrix High Density Table -->
        <div class="nx-card">
          <span class="nx-label">MULTI-PARAMETER GRID RESULTS MATRIX</span>
          <div style="margin-top:10px;max-height:350px;overflow-y:auto" class="custom-scroll">
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>
                <tr style="text-align:left;border-bottom:0.5px solid var(--nx-border);font-size:10px;color:var(--nx-text-3)">
                  <th style="padding:6px 4px">STOP LOSS</th>
                  <th style="padding:6px 4px">TARGET 1</th>
                  <th style="padding:6px 4px;text-align:right">TRADES</th>
                  <th style="padding:6px 4px;text-align:right">WIN RATE</th>
                  <th style="padding:6px 4px;text-align:right">PROFIT FACTOR</th>
                  <th style="padding:6px 4px;text-align:right">MAX DD</th>
                  <th style="padding:6px 4px;text-align:right">NET P&L</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let combo of res.combinations" 
                    [style.background]="isOptimalCombo(combo, res.optimal) ? 'rgba(245,158,11,0.06)' : ''"
                    style="border-bottom:0.5px solid var(--nx-border);transition:background .15s">
                  <td style="padding:8px 4px;font-weight:600;color:var(--nx-text-2)">
                    {{combo.stop_loss_pct}}%
                  </td>
                  <td style="padding:8px 4px;font-weight:600;color:var(--nx-text-2)">
                    {{combo.target_1_pct}}%
                  </td>
                  <td style="padding:8px 4px;text-align:right">{{combo.total_trades}}</td>
                  <td style="padding:8px 4px;text-align:right">{{combo.win_rate | number:'1.0-1'}}%</td>
                  <td style="padding:8px 4px;text-align:right">{{combo.profit_factor | number:'1.2-2'}}</td>
                  <td style="padding:8px 4px;text-align:right;color:var(--nx-danger)">{{combo.max_drawdown | number:'1.0-1'}}%</td>
                  <td style="padding:8px 4px;text-align:right;font-weight:600" 
                      [style.color]="combo.net_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                    {{combo.net_pnl >= 0 ? '+' : ''}}INR {{combo.net_pnl | number:'1.0-0'}}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- WALK-FORWARD RESULTS VIEW -->
      <div *ngIf="walkForwardResult as res" style="display:flex;flex-direction:column;gap:16px">
        
        <!-- Robustness Dashboard -->
        <div class="nx-card" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
          <div style="width:110px;height:110px;border-radius:50%;border:6px solid;display:flex;flex-direction:column;justify-content:center;align-items:center;flex-shrink:0"
               [style.border-color]="res.summary.consistency_score >= 60 ? 'var(--nx-success)' : 'var(--nx-danger)'"
               [style.box-shadow]="res.summary.consistency_score >= 60 ? '0 0 12px rgba(16,185,129,0.2)' : '0 0 12px rgba(239,68,68,0.2)'">
            <span style="font-size:24px;font-weight:700;color:var(--nx-text-1)">{{res.summary.consistency_score}}%</span>
            <span style="font-size:8px;color:var(--nx-text-3);letter-spacing:.05em">CONSISTENCY</span>
          </div>

          <div style="flex:1">
            <span class="nx-label">WALK-FORWARD ROBUSTNESS RATING</span>
            <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
              <span style="font-size:20px;font-weight:700;color:var(--nx-text-1)">
                Strategy is {{res.summary.walk_forward_robustness === 'ROBUST' ? 'ROBUST' : 'NOT ROBUST'}}
              </span>
              <span class="nx-chip" 
                    [ngClass]="res.summary.walk_forward_robustness === 'ROBUST' ? 'nx-chip-ok' : 'nx-chip-fail'">
                {{res.summary.walk_forward_robustness}}
              </span>
            </div>
            <p style="font-size:11px;color:var(--nx-text-3);margin:6px 0 0;line-height:1.4">
              Passing criteria requires a consistency score >= 60.00% across sequential out-of-sample segments.
            </p>

            <div style="display:flex;gap:8px;margin-top:10px">
              <span class="nx-chip nx-chip-neutral" style="font-size:10px">
                OOS WIN RATE: {{res.summary.avg_out_of_sample_win_rate}}%
              </span>
              <span class="nx-chip nx-chip-neutral" style="font-size:10px">
                OOS AVG PF: {{res.summary.avg_profit_factor}}
              </span>
            </div>
          </div>
        </div>

        <!-- ECharts OOS Segment performance timeline -->
        <div class="nx-card">
          <span class="nx-label">OUT-OF-SAMPLE PERFORMANCE SEGMENTS</span>
          <div echarts [options]="oosChartOptions" style="height:260px;width:100%;margin-top:10px"></div>
        </div>

        <!-- Segments Table -->
        <div class="nx-card">
          <span class="nx-label">WALK-FORWARD SEGMENTS DETAIL</span>
          <div style="margin-top:10px;max-height:220px;overflow-y:auto" class="custom-scroll">
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <thead>
                <tr style="text-align:left;border-bottom:0.5px solid var(--nx-border);font-size:10px;color:var(--nx-text-3)">
                  <th style="padding:6px 4px">WINDOW</th>
                  <th style="padding:6px 4px">IN-SAMPLE (IS) DATES</th>
                  <th style="padding:6px 4px">OUT-OF-SAMPLE (OOS) DATES</th>
                  <th style="padding:6px 4px;text-align:right">OOS WIN RATE</th>
                  <th style="padding:6px 4px;text-align:right">OOS PF</th>
                  <th style="padding:6px 4px;text-align:right">OOS NET P&L</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let win of res.windows" style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:8px 4px;font-weight:600;color:var(--nx-text-2)">
                    Segment #{{win.window}}
                  </td>
                  <td style="padding:8px 4px;color:var(--nx-text-3);font-size:11px">
                    {{formatDate(win.in_sample_start)}} - {{formatDate(win.in_sample_end)}}
                  </td>
                  <td style="padding:8px 4px;color:var(--nx-text-2);font-size:11px;font-weight:500">
                    {{formatDate(win.out_of_sample_start)}} - {{formatDate(win.out_of_sample_end)}}
                  </td>
                  <td style="padding:8px 4px;text-align:right">{{win.out_of_sample_win_rate | number:'1.0-1'}}%</td>
                  <td style="padding:8px 4px;text-align:right">{{win.out_of_sample_profit_factor | number:'1.2-2'}}</td>
                  <td style="padding:8px 4px;text-align:right;font-weight:600"
                      [style.color]="win.out_of_sample_net_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                    {{win.out_of_sample_net_pnl >= 0 ? '+' : ''}}INR {{win.out_of_sample_net_pnl | number:'1.0-0'}}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      <!-- HISTORICAL DOWNLOADER RESULTS & STATUS VIEW -->
      <div *ngIf="activeTab === 'Historical Downloader'" style="display:flex;flex-direction:column;gap:16px">
        
        <!-- Database Summary Card -->
        <div class="nx-card" style="border-left:4px solid var(--nx-accent)">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;align-items:center;gap:10px">
              <mat-icon style="color:var(--nx-accent)">storage</mat-icon>
              <div>
                <span class="nx-label">DATABASE STORAGE SUMMARY</span>
                <h3 style="font-size:16px;font-weight:600;color:var(--nx-text-1);margin:2px 0 0">
                  {{downloadParams.symbol}} · {{downloadMode === 'daily' ? '1day' : downloadParams.interval + 'm'}}
                </h3>
              </div>
            </div>
            <button mat-stroked-button (click)="fetchDbSummary()" [disabled]="loadingDbSummary" style="color:var(--nx-text-2)">
              <mat-icon *ngIf="!loadingDbSummary">refresh</mat-icon>
              <mat-icon *ngIf="loadingDbSummary" class="spin">sync</mat-icon>
              Sync Summary
            </button>
          </div>

          <mat-progress-bar *ngIf="loadingDbSummary" mode="indeterminate" color="accent" style="margin-top:12px"></mat-progress-bar>

          <div *ngIf="dbSummary" style="display:grid;grid-template-columns:repeat(3, 1fr);gap:12px;margin-top:14px;border-top:0.5px solid var(--nx-border);padding-top:12px">
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">TOTAL CANDLES</span>
              <div style="font-size:15px;font-weight:700;color:var(--nx-text-1)">{{dbSummary.total_candles | number}}</div>
            </div>
            <div style="grid-column: span 2">
              <span style="font-size:9px;color:var(--nx-text-3)">STORED DATE RANGE</span>
              <div style="font-size:12px;font-weight:600;color:var(--nx-text-1);margin-top:2px">
                {{dbSummary.first_timestamp ? formatDate(dbSummary.first_timestamp) : 'N/A'}} to {{dbSummary.last_timestamp ? formatDate(dbSummary.last_timestamp) : 'N/A'}}
              </div>
            </div>
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">LATEST CLOSE</span>
              <div style="font-size:15px;font-weight:700;color:var(--nx-success)">{{dbSummary.latest_close ? ('INR ' + (dbSummary.latest_close | number:'1.2-2')) : 'N/A'}}</div>
            </div>
            <div style="grid-column: span 2">
              <span style="font-size:9px;color:var(--nx-text-3)">TOTAL VOLUME TRADED</span>
              <div style="font-size:15px;font-weight:700;color:var(--nx-text-1)">{{dbSummary.total_volume ? (dbSummary.total_volume | number) : 'N/A'}}</div>
            </div>
          </div>

          <div *ngIf="!loadingDbSummary && !dbSummary" style="margin-top:14px;font-size:12px;color:var(--nx-text-3);text-align:center;padding:12px 0">
            No summary data loaded. Tap 'Sync Summary' or select another symbol/interval.
          </div>
        </div>

        <!-- Download Result Card -->
        <div class="nx-card" *ngIf="downloading || downloadResult">
          <span class="nx-label">DATA INGESTION PIPELINE STATUS</span>
          
          <div *ngIf="downloading" style="padding:24px 0;text-align:center">
            <mat-progress-bar mode="indeterminate" color="accent" style="margin-bottom:12px"></mat-progress-bar>
            <div style="font-size:12px;color:var(--nx-text-2)">Downloading historical chunks from Dhan...</div>
            <div style="font-size:10px;color:var(--nx-text-3);margin-top:4px">Please wait, splitting into 90-day intervals to avoid rate limits.</div>
          </div>

          <div *ngIf="downloadResult as res" style="margin-top:10px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
              <div style="display:flex;align-items:center;gap:6px">
                <mat-icon [style.color]="res.ok ? 'var(--nx-success)' : 'var(--nx-danger)'">
                  {{res.ok ? 'check_circle' : 'error'}}
                </mat-icon>
                <span style="font-size:13px;font-weight:600;color:var(--nx-text-1)">
                  {{res.status || 'FINISHED'}}
                </span>
              </div>
              <span class="nx-chip" [ngClass]="res.ok ? 'nx-chip-ok' : 'nx-chip-fail'">
                {{res.total_candles_saved ?? res.candles_received ?? 0}} SAVED
              </span>
            </div>

            <p style="font-size:12px;color:var(--nx-text-2);margin:0 0 14px;line-height:1.4">
              {{res.message}}
            </p>

            <!-- Detailed Chunks Table -->
            <div *ngIf="res.chunks && res.chunks.length" style="border-top:0.5px solid var(--nx-border);padding-top:12px">
              <span class="nx-label" style="font-size:9px;margin-bottom:6px;display:block">DETAILED CHUNK METRICS</span>
              <div style="max-height:200px;overflow-y:auto" class="custom-scroll">
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                  <thead>
                    <tr style="text-align:left;color:var(--nx-text-3);border-bottom:0.5px solid var(--nx-border)">
                      <th style="padding:4px">CHUNK</th>
                      <th style="padding:4px">RANGE</th>
                      <th style="padding:4px;text-align:right">SAVED</th>
                      <th style="padding:4px;text-align:right">STATUS</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr *ngFor="let chunk of res.chunks" style="border-bottom:0.5px solid var(--nx-border)">
                      <td style="padding:6px 4px;font-weight:600">#{{chunk.chunk}}</td>
                      <td style="padding:6px 4px;color:var(--nx-text-2)">{{formatChunkDates(chunk.from_date, chunk.to_date)}}</td>
                      <td style="padding:6px 4px;text-align:right">{{chunk.saved_count ?? chunk.candles_received ?? 0}}</td>
                      <td style="padding:6px 4px;text-align:right">
                        <span [style.color]="chunk.ok ? 'var(--nx-success)' : 'var(--nx-danger)'" style="font-weight:600">
                          {{chunk.ok ? 'OK' : (chunk.status || 'FAIL')}}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <!-- Gap Diagnostic Results Card -->
        <div class="nx-card" *ngIf="gapScanResult || scanningGaps">
          <span class="nx-label">DATABASE GAP DIAGNOSTIC PANEL</span>
          
          <div *ngIf="scanningGaps" style="padding:20px 0;text-align:center">
            <mat-progress-bar mode="indeterminate" color="accent" style="margin-bottom:12px"></mat-progress-bar>
            <div style="font-size:12px;color:var(--nx-text-2)">Scanning database tables for weekday gaps...</div>
          </div>

          <div *ngIf="gapScanResult as res" style="margin-top:10px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
              <span style="font-size:13px;font-weight:600;color:var(--nx-text-1)">
                {{res.total_gaps_found}} Gaps Identified
              </span>
              <span class="nx-chip" [ngClass]="res.total_gaps_found === 0 ? 'nx-chip-ok' : 'nx-chip-fail'">
                {{res.total_gaps_found === 0 ? 'HEALTHY' : 'GAPS FOUND'}}
              </span>
            </div>

            <p style="font-size:12px;color:var(--nx-text-2);margin:0 0 12px;line-height:1.4">
              Scanned {{res.total_days_scanned}} trading days between {{downloadParams.from_date}} and {{downloadParams.to_date}}.
            </p>

            <!-- Gaps list table -->
            <div *ngIf="res.gaps && res.gaps.length" style="max-height:220px;overflow-y:auto;border:1px solid var(--nx-border);border-radius:6px;padding:6px;margin-bottom:12px" class="custom-scroll">
              <table style="width:100%;border-collapse:collapse;font-size:11px">
                <thead>
                  <tr style="text-align:left;color:var(--nx-text-3);border-bottom:0.5px solid var(--nx-border)">
                    <th style="padding:4px">DATE</th>
                    <th style="padding:4px">SEVERITY</th>
                    <th style="padding:4px">CANDLES</th>
                    <th style="padding:4px">REASON</th>
                  </tr>
                </thead>
                <tbody>
                  <tr *ngFor="let gap of res.gaps" style="border-bottom:0.5px solid var(--nx-border)">
                    <td style="padding:6px 4px;font-weight:600">{{gap.date}}</td>
                    <td style="padding:6px 4px">
                      <span class="nx-chip" [ngClass]="gap.severity === 'HIGH' ? 'nx-chip-fail' : 'nx-chip-neutral' " style="font-size:8px;padding:2px 4px">
                        {{gap.severity}}
                      </span>
                    </td>
                    <td style="padding:6px 4px">{{gap.count}} / {{gap.expected}}</td>
                    <td style="padding:6px 4px;color:var(--nx-text-3)">{{gap.reason}}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div *ngIf="res.total_gaps_found > 0" style="margin-top:14px;display:flex;flex-direction:column;gap:10px">
              <button mat-flat-button (click)="patchDataGaps()" [disabled]="patchingGaps" style="background:var(--nx-accent);color:#fff;font-weight:600">
                <mat-icon *ngIf="!patchingGaps">healing</mat-icon>
                <mat-icon *ngIf="patchingGaps" class="spin">sync</mat-icon>
                TRIGGER TARGETED AUTOPATCH PIPELINE
              </button>
            </div>

            <!-- Patch Results Summary -->
            <div *ngIf="gapPatchResult as patchRes" style="margin-top:14px;padding:12px;background:rgba(16,185,129,0.06);border:0.5px solid rgba(16,185,129,0.3);border-radius:6px">
              <div style="font-size:12px;font-weight:600;color:var(--nx-success)">Gap Autopatch Complete!</div>
              <div style="font-size:11px;color:var(--nx-text-2);margin-top:4px">
                Successfully patched {{patchRes.success_count}} of {{patchRes.patched_count}} gaps. Stored {{patchRes.total_candles_saved}} historical candles in the database.
              </div>
            </div>
          </div>
        </div>

      </div>


      <!-- ANALYTICS RESULTS VIEW -->
      <div *ngIf="analyticsResult as res" style="display:flex;flex-direction:column;gap:16px">
        
        <div class="nx-card" style="background:linear-gradient(135deg, rgba(139,92,246,0.06), rgba(139,92,246,0.02));border-left:4px solid #8b5cf6">
          <div style="display:flex;align-items:center;gap:12px">
            <mat-icon style="font-size:32px;width:32px;height:32px;color:#8b5cf6">insights</mat-icon>
            <div>
              <span class="nx-label" style="color:#8b5cf6;font-weight:600">QUANTITATIVE DATA SCIENCE METRICS</span>
              <h2 style="font-size:18px;font-weight:700;color:var(--nx-text-1);margin:4px 0 0">
                Data Science Engine
              </h2>
            </div>
          </div>
          
          <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:10px;margin-top:14px;border-top:0.5px solid var(--nx-border);padding-top:12px">
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">WIN RATE</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{(res.win_rate * 100) | number:'1.0-1'}}%</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">MEAN PNL</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.mean | number:'1.0-0'}}</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">STD DEV</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.std_dev | number:'1.0-0'}}</div>
            </div>
            <div style="text-align:center">
              <span style="font-size:9px;color:var(--nx-text-3)">TOTAL TRADES</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.total_trades}}</div>
            </div>
          </div>
        </div>

        <div class="nx-card" *ngIf="advancedMetricsResult as metrics">
          <span class="nx-label">ADVANCED RISK METRICS</span>
          <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:10px;margin-top:14px">
            <div style="text-align:center;padding:12px;background:rgba(255,255,255,0.02);border-radius:6px;border:1px solid var(--nx-border)">
              <span style="font-size:9px;color:var(--nx-text-3)">SHARPE RATIO</span>
              <div style="font-size:18px;font-weight:700;color:var(--nx-text-1)">{{metrics.sharpe_ratio | number:'1.2-2'}}</div>
            </div>
            <div style="text-align:center;padding:12px;background:rgba(255,255,255,0.02);border-radius:6px;border:1px solid var(--nx-border)">
              <span style="font-size:9px;color:var(--nx-text-3)">PROFIT FACTOR</span>
              <div style="font-size:18px;font-weight:700;color:var(--nx-text-1)">{{metrics.profit_factor | number:'1.2-2'}}</div>
            </div>
            <div style="text-align:center;padding:12px;background:rgba(255,255,255,0.02);border-radius:6px;border:1px solid var(--nx-border)">
              <span style="font-size:9px;color:var(--nx-text-3)">MAX DRAWDOWN</span>
              <div style="font-size:18px;font-weight:700;color:var(--nx-danger)">-{{metrics.max_drawdown | number:'1.0-0'}}</div>
            </div>
          </div>
        </div>

        <!-- ECharts Distribution Histogram -->
        <div class="nx-card">
          <span class="nx-label">TRADE PNL PROBABILITY DISTRIBUTION (BELL CURVE)</span>
          <div echarts [options]="distributionChartOptions" style="height:300px;width:100%;margin-top:10px"></div>
        </div>
      </div>

      <!-- MARKET REGIMES (ML) RESULTS VIEW -->
      <div *ngIf="activeTab === 'Market Regimes (ML)' && regimeResult as res" style="display:flex;flex-direction:column;gap:16px">
        
        <!-- Active Regime Banner -->
        <div class="nx-card" 
             style="border-left:4px solid"
             [style.border-left-color]="res.current_regime === 'BULLISH TREND' ? '#10b981' : (res.current_regime === 'BEARISH / VOLATILE' ? '#ef4444' : '#f59e0b')">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;align-items:center;gap:12px">
              <mat-icon [style.color]="res.current_regime === 'BULLISH TREND' ? '#10b981' : (res.current_regime === 'BEARISH / VOLATILE' ? '#ef4444' : '#f59e0b')">
                psychology
              </mat-icon>
              <div>
                <span class="nx-label">ACTIVE MARKET REGIME (K-MEANS ML MODEL)</span>
                <h2 style="font-size:20px;font-weight:700;color:var(--nx-text-1);margin:2px 0 0">
                  {{res.current_regime}}
                </h2>
              </div>
            </div>
            <div style="text-align:right">
              <span class="nx-label">CONFIDENCE</span>
              <div style="font-size:20px;font-weight:700;color:var(--nx-text-1)">{{res.confidence_score}}%</div>
            </div>
          </div>
          
          <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:10px;margin-top:14px;border-top:0.5px solid var(--nx-border);padding-top:12px">
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">HISTORICAL CHOP</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.distribution['CHOP / RANGE-BOUND'] || 0}} bars</div>
            </div>
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">BULLISH BARS</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.distribution['BULLISH TREND'] || 0}} bars</div>
            </div>
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">BEARISH BARS</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-text-1)">{{res.distribution['BEARISH / VOLATILE'] || 0}} bars</div>
            </div>
          </div>
        </div>

        <!-- Recommended Playbook Card -->
        <div class="nx-card">
          <span class="nx-label">ML PLAYBOOK RECOMMENDATIONS</span>
          <div style="display:flex;align-items:flex-start;gap:12px;margin-top:10px">
            <mat-icon style="color:var(--nx-accent)">assignment</mat-icon>
            <div>
              <h4 style="font-size:13px;font-weight:600;color:var(--nx-text-1);margin:0">
                Recommended Actions for {{res.current_regime}}
              </h4>
              <p style="font-size:12px;color:var(--nx-text-3);line-height:1.4;margin:4px 0 0" *ngIf="res.current_regime === 'CHOP / RANGE-BOUND'">
                Market is in a highly compressed range-bound consolidation state. Short-side option writing strategies (short straddles, iron condors) are highly favored due to rapid theta decay. Avoid directional breakouts as false breakouts are statistically common under this cluster.
              </p>
              <p style="font-size:12px;color:var(--nx-text-3);line-height:1.4;margin:4px 0 0" *ngIf="res.current_regime === 'BULLISH TREND'">
                High-confidence upward structural trend. Long-side momentum strategies, trend following, and pullback buying (long calls, bull call spreads) are highly favored. Support zones are reliable and should be used to accumulate long exposure.
              </p>
              <p style="font-size:12px;color:var(--nx-text-3);line-height:1.4;margin:4px 0 0" *ngIf="res.current_regime === 'BEARISH / VOLATILE'">
                High volatility downward distribution state. Short-side strategies, protective hedges, or long put options/bear call spreads are highly favored. Volatility expansion is expected; widen stop-loss boundaries and reduce position sizes.
              </p>
            </div>
          </div>
        </div>

        <!-- ECharts 3D-effect Scatter Plot -->
        <div class="nx-card">
          <span class="nx-label">REGIME CLUSTER MAP (SCATTER INDICATOR)</span>
          <div echarts [options]="regimeChartOptions" style="height:320px;width:100%;margin-top:10px"></div>
        </div>

      </div>

      <!-- MONTE CARLO RESULTS VIEW -->
      <div *ngIf="activeTab === 'Monte Carlo Stress-Testing' && mcResult as res" style="display:flex;flex-direction:column;gap:16px">
        
        <!-- Ruin and Risk Banner -->
        <div class="nx-card" 
             style="border-left:4px solid"
             [style.border-left-color]="res.ruin_probability > 5.0 ? '#ef4444' : '#10b981'"
             [style.background]="res.ruin_probability > 5.0 ? 'linear-gradient(135deg, rgba(239,68,68,0.06), rgba(15,23,42,0.02))' : 'linear-gradient(135deg, rgba(16,185,129,0.06), rgba(15,23,42,0.02))'">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;align-items:center;gap:12px">
              <mat-icon [style.color]="res.ruin_probability > 5.0 ? '#ef4444' : '#10b981'">
                shield_alert
              </mat-icon>
              <div>
                <span class="nx-label">PROBABILITY OF RUIN (CAPITAL STRESS-TEST)</span>
                <h2 style="font-size:22px;font-weight:700;color:var(--nx-text-1);margin:2px 0 0">
                  {{res.ruin_probability}}%
                </h2>
              </div>
            </div>
            <div style="text-align:right">
              <span class="nx-label">SIMULATION SUCCESS RATE</span>
              <div style="font-size:22px;font-weight:700;color:var(--nx-success)">{{res.simulation_win_rate}}%</div>
            </div>
          </div>
          
          <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:10px;margin-top:14px;border-top:0.5px solid var(--nx-border);padding-top:12px">
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">EXPECTED MEAN PNL</span>
              <div style="font-size:14px;font-weight:600;" [style.color]="res.expected_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                INR {{res.expected_pnl | number:'1.0-0'}}
              </div>
            </div>
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">MEDIAN MAX DRAWDOWN</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-danger)">{{res.drawdown_stats.p50 | number:'1.1-1'}}%</div>
            </div>
            <div>
              <span style="font-size:9px;color:var(--nx-text-3)">WORST 5% MAX DRAWDOWN</span>
              <div style="font-size:14px;font-weight:600;color:var(--nx-danger)">{{res.drawdown_stats.p95 | number:'1.1-1'}}%</div>
            </div>
          </div>
        </div>

        <!-- Terminal Capital distribution and drawdown percentiles -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
          
          <!-- Terminal Capital Card -->
          <div class="nx-card">
            <span class="nx-label">TERMINAL CAPITAL EXPECTANCY</span>
            <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px">
              <tbody>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Best 5% Outcome (P95)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:600;color:var(--nx-success)">INR {{res.terminal_stats.p95 | number:'1.0-0'}}</td>
                </tr>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Above Median (P75)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:500">INR {{res.terminal_stats.p75 | number:'1.0-0'}}</td>
                </tr>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-2);font-weight:600">Expected Median (P50)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:700;color:var(--nx-text-1)">INR {{res.terminal_stats.p50 | number:'1.0-0'}}</td>
                </tr>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Below Median (P25)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:500">INR {{res.terminal_stats.p25 | number:'1.0-0'}}</td>
                </tr>
                <tr style="border-bottom:none">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Worst 5% Outcome (P5)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:600;color:var(--nx-danger)">INR {{res.terminal_stats.p5 | number:'1.0-0'}}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Worst drawdowns -->
          <div class="nx-card">
            <span class="nx-label">MAX DRAWDOWN PERCENTILES</span>
            <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px">
              <tbody>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Average Max Drawdown (P50)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:600;color:var(--nx-danger)">{{res.drawdown_stats.p50 | number:'1.1-1'}}%</td>
                </tr>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Extreme DD Risk (P90)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:500;color:var(--nx-danger)">{{res.drawdown_stats.p90 | number:'1.1-1'}}%</td>
                </tr>
                <tr style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:6px 0;color:var(--nx-text-2);font-weight:600">Critical DD Risk (P95)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:700;color:var(--nx-danger)">{{res.drawdown_stats.p95 | number:'1.1-1'}}%</td>
                </tr>
                <tr style="border-bottom:none">
                  <td style="padding:6px 0;color:var(--nx-text-3)">Black-Swan DD Risk (P99)</td>
                  <td style="padding:6px 0;text-align:right;font-weight:600;color:var(--nx-danger)">{{res.drawdown_stats.p99 | number:'1.1-1'}}%</td>
                </tr>
              </tbody>
            </table>
          </div>

        </div>

        <!-- Cascading Multi-path Equity chart -->
        <div class="nx-card">
          <span class="nx-label">MONTE CARLO CASCADING EQUITY PATHS (50 RUNS)</span>
          <div echarts [options]="mcChartOptions" style="height:320px;width:100%;margin-top:10px"></div>
        </div>

      </div>

    </div>


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
  `]
})
export class ResearchLabComponent implements OnInit {
  strategies: any[] = [];
  selectedStrategyId: number | null = null;
  loading = false;
  errorMsg: string | null = null;

  // Tabs tracking
  activeTab = 'Grid Optimizer';

  // Base parameters
  baseParams = {
    underlying: 'NIFTY',
    expiry: '2026-05-28',
    interval: '5',
    from_date: '2026-05-01',
    to_date: '2026-05-23',
    initial_capital: 100000,
    max_risk_per_trade: 5.0,
    lot_size: 50,
    entry_model: 'NEXT_CANDLE_OPEN',
    same_candle_priority: 'SL_FIRST'
  };

  // Optimization step configurations
  optRanges = {
    slMin: 10.0,
    slMax: 20.0,
    slStep: 5.0,
    tgtMin: 15.0,
    tgtMax: 25.0,
    tgtStep: 5.0
  };

  // Walk-forward window specifications
  wfParams = {
    in_sample_days: 60,
    out_of_sample_days: 20
  };

  // Result payloads
  optimizationResult: any = null;
  walkForwardResult: any = null;
  analyticsResult: any = null;
  advancedMetricsResult: any = null;

  loadingAnalytics = false;

  // Downloader state
  downloadMode: 'intraday' | 'daily' = 'intraday';
  downloadParams = {
    symbol: 'NIFTY',
    interval: '5',
    from_date: '2026-05-01',
    to_date: '2026-05-23'
  };
  downloading = false;
  downloadResult: any = null;
  dbSummary: any = null;
  loadingDbSummary = false;

  // ML Regime state
  regimeResult: any = null;
  loadingRegime = false;
  regimeChartOptions: any = {};

  // Monte Carlo parameters
  mcParams = {
    source: 'custom',
    initial_capital: 100000.0,
    risk_per_trade_pct: 5.0,
    num_simulations: 2000,
    num_trades_per_run: 100,
    ruin_threshold_pct: 50.0,
    win_rate: 55.0,
    avg_win: 5000.0,
    avg_loss: 3000.0
  };
  mcResult: any = null;
  loadingMC = false;
  mcChartOptions: any = {};

  // Gap scanner state
  scanningGaps = false;
  gapScanResult: any = null;
  patchingGaps = false;
  gapPatchResult: any = null;

  // Chart configuration
  oosChartOptions: any = {};
  distributionChartOptions: any = {};

  constructor(private http: HttpClient) {}


  ngOnInit() {
    this.loadStrategies();
  }

  runAnalytics() {
    this.loadingAnalytics = true;
    this.analyticsResult = null;
    this.advancedMetricsResult = null;
    this.errorMsg = null;

    // Fetch trade distribution
    this.http.get<any>('/api/analytics/trade-distribution')
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Failed to fetch trade distribution.';
        return of(null);
      }))
      .subscribe(res => {
        if (res && res.status === 'OK') {
          this.analyticsResult = res;
          this.buildDistributionChart(res.histogram);
        } else if (res && res.status !== 'OK') {
          this.errorMsg = `Distribution Data Error: ${res.status}`;
        }
        
        // Fetch advanced metrics after distribution
        this.http.get<any>('/api/analytics/advanced-metrics')
          .pipe(catchError(() => of(null)))
          .subscribe(metricsRes => {
            if (metricsRes && metricsRes.status === 'OK') {
              this.advancedMetricsResult = metricsRes;
            }
            this.loadingAnalytics = false;
          });
      });
  }

  buildDistributionChart(histogram: any) {
    if (!histogram || !histogram.counts || !histogram.bin_edges) return;
    
    // Bin edges are N+1, counts are N
    const categories = [];
    for (let i = 0; i < histogram.counts.length; i++) {
      const start = histogram.bin_edges[i].toFixed(0);
      const end = histogram.bin_edges[i+1].toFixed(0);
      categories.push(`${start} to ${end}`);
    }

    this.distributionChartOptions = {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: [
        {
          type: 'category',
          data: categories,
          axisTick: { alignWithLabel: true },
          axisLabel: { color: '#64748b', fontSize: 10 }
        }
      ],
      yAxis: [
        {
          type: 'value',
          name: 'Number of Trades',
          axisLabel: { color: '#64748b', fontSize: 10 },
          splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } }
        }
      ],
      series: [
        {
          name: 'Trades',
          type: 'bar',
          barWidth: '60%',
          data: histogram.counts,
          itemStyle: {
            color: '#8b5cf6',
            borderRadius: [4, 4, 0, 0]
          }
        }
      ]
    };
  }

  loadStrategies() {
    this.http.get<any[]>('/api/strategies')
      .pipe(catchError(() => of([])))
      .subscribe(res => this.strategies = res);
  }

  onStrategySelect() {
    // Strategy selection is stored, we will pass its config in the payload during execution
  }

  onTabChange(event: any) {
    this.activeTab = event.tab.textLabel;
    this.errorMsg = null;
    if (this.activeTab === 'Historical Downloader') {
      this.fetchDbSummary();
    } else if (this.activeTab === 'Market Regimes (ML)') {
      this.runRegimeAnalysis();
    } else if (this.activeTab === 'Monte Carlo Stress-Testing') {
      this.runMonteCarlo();
    }
  }


  runRegimeAnalysis() {
    this.loadingRegime = true;
    this.regimeResult = null;
    this.errorMsg = null;

    const symbol = this.baseParams.underlying;
    const interval = this.baseParams.interval;

    this.http.get<any>(`/api/analytics/market-regime?symbol=${symbol}&interval=${interval}`)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Regime analysis failed. Verify historical candles are downloaded.';
        this.loadingRegime = false;
        return of(null);
      }))
      .subscribe(res => {
        this.loadingRegime = false;
        if (!res) return;
        if (res.status !== 'OK') {
          this.errorMsg = res.message || 'Clustering model returned an error state.';
          return;
        }
        this.regimeResult = res;
        this.buildRegimeChart(res.scatter_data);
      });
  }

  buildRegimeChart(scatterData: any[]) {
    if (!scatterData || !scatterData.length) return;

    // Group data by regime
    const chopPoints = scatterData.filter(p => p[2] === 'CHOP / RANGE-BOUND').map(p => [p[0], p[1]]);
    const bullishPoints = scatterData.filter(p => p[2] === 'BULLISH TREND').map(p => [p[0], p[1]]);
    const bearishPoints = scatterData.filter(p => p[2] === 'BEARISH / VOLATILE').map(p => [p[0], p[1]]);

    this.regimeChartOptions = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          return `<strong>${params.seriesName}</strong><br/>Returns: ${params.value[0].toFixed(3)}%<br/>Volatility: ${params.value[1].toFixed(3)}%`;
        },
        backgroundColor: 'rgba(15,23,42,.92)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9', fontSize: 11 }
      },
      legend: {
        top: 0,
        textStyle: { color: '#64748b', fontSize: 10 }
      },
      grid: { left: '4%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
      xAxis: {
        type: 'value',
        name: 'Returns (%)',
        nameLocation: 'middle',
        nameGap: 20,
        axisLabel: { color: '#64748b', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } }
      },
      yAxis: {
        type: 'value',
        name: 'Volatility (%)',
        axisLabel: { color: '#64748b', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } }
      },
      series: [
        {
          name: 'Chop / Range-bound',
          type: 'scatter',
          data: chopPoints,
          symbolSize: 6,
          itemStyle: { color: '#f59e0b' } // Amber
        },
        {
          name: 'Bullish Trend',
          type: 'scatter',
          data: bullishPoints,
          symbolSize: 6,
          itemStyle: { color: '#10b981' } // Emerald
        },
        {
          name: 'Bearish / Volatile',
          type: 'scatter',
          data: bearishPoints,
          symbolSize: 6,
          itemStyle: { color: '#ef4444' } // Rose
        }
      ]
    };
  }

  onDownloadModeChange() {
    if (this.downloadMode === 'daily') {
      this.downloadParams.interval = '1day';
    } else {
      this.downloadParams.interval = '5';
    }
    this.fetchDbSummary();
  }

  fetchDbSummary() {
    this.loadingDbSummary = true;
    this.dbSummary = null;
    const interval = this.downloadMode === 'daily' ? '1day' : this.downloadParams.interval;
    this.http.get<any>(`/api/historical/summary?symbol=${this.downloadParams.symbol}&interval=${interval}`)
      .pipe(catchError(() => of(null)))
      .subscribe(res => {
        this.dbSummary = res;
        this.loadingDbSummary = false;
      });
  }

  formatChunkDates(fromStr: string, toStr: string): string {
    if (!fromStr || !toStr) return '';
    const f = fromStr.split(' ')[0];
    const t = toStr.split(' ')[0];
    return `${f} to ${t}`;
  }

  runDownload() {
    this.downloading = true;
    this.downloadResult = null;
    this.errorMsg = null;

    if (this.downloadMode === 'intraday') {
      const payload = {
        symbol: this.downloadParams.symbol.trim().toUpperCase(),
        interval: this.downloadParams.interval,
        from_date: this.downloadParams.from_date,
        to_date: this.downloadParams.to_date
      };
      this.http.post<any>('/api/historical/download-intraday', payload)
        .pipe(catchError(err => {
          this.errorMsg = err?.error?.detail || 'Failed to download intraday historical candles.';
          this.downloading = false;
          return of(null);
        }))
        .subscribe(res => {
          this.downloading = false;
          if (res) {
            this.downloadResult = res;
            if (res.ok) {
              this.fetchDbSummary(); // Refresh summary on success
            } else {
              this.errorMsg = res.message || 'Intraday download process returned failures.';
            }
          }
        });
    } else {
      const payload = {
        symbol: this.downloadParams.symbol.trim().toUpperCase(),
        from_date: this.downloadParams.from_date,
        to_date: this.downloadParams.to_date
      };
      this.http.post<any>('/api/historical/download-daily', payload)
        .pipe(catchError(err => {
          this.errorMsg = err?.error?.detail || 'Failed to download daily historical candles.';
          this.downloading = false;
          return of(null);
        }))
        .subscribe(res => {
          this.downloading = false;
          if (res) {
            this.downloadResult = res;
            if (res.ok) {
              this.fetchDbSummary(); // Refresh summary on success
            } else {
              this.errorMsg = res.message || 'Daily download process returned failures.';
            }
          }
        });
    }
  }

  calculateCombinations(): number {
    const sls = this.getRangeCount(this.optRanges.slMin, this.optRanges.slMax, this.optRanges.slStep);
    const tgts = this.getRangeCount(this.optRanges.tgtMin, this.optRanges.tgtMax, this.optRanges.tgtStep);
    return sls * tgts;
  }

  private getRangeCount(min: number, max: number, step: number): number {
    if (step <= 0 || min > max) return 1;
    return Math.floor((max - min) / step) + 1;
  }

  getSelectedStrategyConfig() {
    if (!this.selectedStrategyId) return null;
    const strat = this.strategies.find(s => s.id === this.selectedStrategyId);
    return strat ? strat.config : null;
  }

  runOptimization() {
    this.loading = true;
    this.optimizationResult = null;
    this.walkForwardResult = null;
    this.errorMsg = null;

    const payload = {
      ...this.baseParams,
      name: 'Optimization Run',
      stop_loss_pct_range: [this.optRanges.slMin, this.optRanges.slMax, this.optRanges.slStep],
      target_1_pct_range: [this.optRanges.tgtMin, this.optRanges.tgtMax, this.optRanges.tgtStep],
      strategy_config: this.getSelectedStrategyConfig()
    };

    this.http.post<any>('/api/backtest/optimize', payload)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Optimization failed. Verify date boundary ranges and historical candles exist.';
        this.loading = false;
        return of(null);
      }))
      .subscribe(res => {
        this.loading = false;
        if (!res) return;
        if (!res.ok) {
          this.errorMsg = res.message || 'Grid search failed.';
          return;
        }
        this.optimizationResult = res;
      });
  }

  runWalkForward() {
    this.loading = true;
    this.optimizationResult = null;
    this.walkForwardResult = null;
    this.errorMsg = null;

    const payload = {
      ...this.baseParams,
      name: 'Walk-Forward Run',
      in_sample_days: this.wfParams.in_sample_days,
      out_of_sample_days: this.wfParams.out_of_sample_days,
      strategy_config: this.getSelectedStrategyConfig()
    };

    this.http.post<any>('/api/backtest/walk-forward', payload)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Walk-forward segment run failed. Validate candle data completeness for segments.';
        this.loading = false;
        return of(null);
      }))
      .subscribe(res => {
        this.loading = false;
        if (!res) return;
        if (!res.ok) {
          this.errorMsg = res.message || 'Walk-forward execution failed.';
          return;
        }
        this.walkForwardResult = res;
        this.buildOosChart(res.windows);
      });
  }

  isOptimalCombo(combo: any, optimal: any): boolean {
    if (!optimal) return false;
    return combo.stop_loss_pct === optimal.stop_loss_pct && combo.target_1_pct === optimal.target_1_pct;
  }

  formatDate(dateStr: string): string {
    if (!dateStr) return '';
    return dateStr.split('T')[0];
  }

  buildOosChart(windows: any[]) {
    this.oosChartOptions = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(15,23,42,.92)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9', fontSize: 11 }
      },
      legend: {
        top: 0,
        textStyle: { color: '#64748b', fontSize: 10 }
      },
      grid: { left: '4%', right: '4%', bottom: '3%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: windows.map(w => `Seg #${w.window}`),
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisTick: { show: false }
      },
      yAxis: [
        {
          type: 'value',
          name: 'OOS Net P&L (INR)',
          position: 'left',
          axisLabel: { color: '#64748b', fontSize: 9 },
          splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } },
          nameTextStyle: { color: '#64748b', fontSize: 9 }
        },
        {
          type: 'value',
          name: 'OOS Win Rate (%)',
          position: 'right',
          axisLabel: { color: '#64748b', fontSize: 9 },
          splitLine: { show: false },
          nameTextStyle: { color: '#64748b', fontSize: 9 }
        }
      ],
      series: [
        {
          name: 'OOS Net P&L',
          type: 'bar',
          data: windows.map(w => w.out_of_sample_net_pnl),
          barMaxWidth: 28,
          itemStyle: {
            color: (params: any) => params.value >= 0 ? '#10b981' : '#ef4444',
            borderRadius: [4, 4, 0, 0]
          }
        },
        {
          name: 'OOS Win Rate',
          type: 'line',
          yAxisIndex: 1,
          data: windows.map(w => w.out_of_sample_win_rate),
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { color: '#6366f1', width: 2 },
          itemStyle: { color: '#6366f1' }
        }
      ]
    };
  }

  runMonteCarlo() {
    this.loadingMC = true;
    this.mcResult = null;
    this.errorMsg = null;

    this.http.post<any>('/api/analytics/monte-carlo', this.mcParams)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Monte Carlo simulation failed. Enforce closed paper trades exist if using bootstrapping.';
        this.loadingMC = false;
        return of(null);
      }))
      .subscribe(res => {
        this.loadingMC = false;
        if (!res) return;
        if (res.status !== 'OK') {
          this.errorMsg = res.message || 'Monte Carlo simulation failed.';
          return;
        }
        this.mcResult = res;
        this.buildMcChart(res.sample_curves);
      });
  }

  buildMcChart(sampleCurves: any[][]) {
    if (!sampleCurves || !sampleCurves.length) return;

    // Series configurations for 50 lines
    const series = sampleCurves.map((curve, idx) => {
      return {
        name: `Path ${idx + 1}`,
        type: 'line',
        showSymbol: false,
        data: curve,
        lineStyle: {
          width: 1.2,
          color: curve[curve.length - 1] >= this.mcParams.initial_capital ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)'
        }
      };
    });

    this.mcChartOptions = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line' },
        backgroundColor: 'rgba(15,23,42,.92)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9', fontSize: 11 }
      },
      grid: { left: '4%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
      xAxis: {
        type: 'category',
        name: 'Trade #',
        nameLocation: 'middle',
        nameGap: 20,
        data: Array.from({ length: sampleCurves[0].length }, (_, i) => i.toString()),
        axisLabel: { color: '#64748b', fontSize: 9 },
        axisLine: { lineStyle: { color: '#1e293b' } }
      },
      yAxis: {
        type: 'value',
        name: 'Capital (INR)',
        axisLabel: { color: '#64748b', fontSize: 9 },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } }
      },
      series: series
    };
  }

  scanDataGaps() {
    this.scanningGaps = true;
    this.gapScanResult = null;
    this.gapPatchResult = null;
    this.errorMsg = null;

    const symbol = this.downloadParams.symbol;
    const interval = this.downloadMode === 'daily' ? '1day' : this.downloadParams.interval;
    const from_date = this.downloadParams.from_date;
    const to_date = this.downloadParams.to_date;

    this.http.get<any>(`/api/historical/gap-scan?symbol=${symbol}&interval=${interval}&from_date=${from_date}&to_date=${to_date}`)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Failed to scan for database gaps.';
        this.scanningGaps = false;
        return of(null);
      }))
      .subscribe(res => {
        this.scanningGaps = false;
        if (res && res.ok) {
          this.gapScanResult = res;
        } else if (res && !res.ok) {
          this.errorMsg = res.message || 'Gap scanning returned an error state.';
        }
      });
  }

  patchDataGaps() {
    if (!this.gapScanResult || !this.gapScanResult.gaps || !this.gapScanResult.gaps.length) return;
    this.patchingGaps = true;
    this.gapPatchResult = null;
    this.errorMsg = null;

    const payload = {
      symbol: this.gapScanResult.symbol,
      interval: this.gapScanResult.interval,
      gaps: this.gapScanResult.gaps.map((g: any) => g.date)
    };

    this.http.post<any>('/api/historical/gap-patch', payload)
      .pipe(catchError((err) => {
        this.errorMsg = err?.error?.detail || 'Failed to execute database gap patching.';
        this.patchingGaps = false;
        return of(null);
      }))
      .subscribe(res => {
        this.patchingGaps = false;
        if (res) {
          this.gapPatchResult = res;
          this.scanDataGaps(); // Rescan to confirm patch completeness!
        }
      });
  }
}

