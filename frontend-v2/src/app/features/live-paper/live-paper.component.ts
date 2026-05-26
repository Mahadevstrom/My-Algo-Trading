import { Component, OnDestroy, OnInit } from '@angular/core';
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
import {
  catchError,
  forkJoin,
  interval,
  of,
  startWith,
  Subscription,
  switchMap,
} from 'rxjs';

type TradeRow = Record<string, any>;

interface ComboLeg {
  symbol: string;
  expiry: string;
  strike: number;
  option_type: 'CE' | 'PE';
  direction: 'BUY' | 'SELL';
  entry_price: number;
  quantity: number;
}

@Component({
  selector: 'app-live-paper',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTabsModule,
    NgxEchartsDirective,
  ],
  template: `
<div style="max-width:1600px;margin:0 auto">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;
              align-items:flex-start;margin-bottom:20px">
    <div>
      <p class="nx-label">LIVE PAPER Cockpit</p>
      <h1 style="font-size:22px;font-weight:500;
                 color:var(--nx-text-1);margin:0">
        Paper Trade & Option Combination Monitor
      </h1>
      <p style="font-size:12px;color:var(--nx-text-3);margin:4px 0 0">
        Monitor single-leg entries, configure multi-leg option spreads, track absolute portfolio Greeks and decays in real-time.
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

  <!-- Warning Banner -->
  <div style="background:rgba(99,102,241,.08);
              border:0.5px solid rgba(99,102,241,.32);
              border-radius:8px;padding:10px 16px;
              font-size:11px;color:#818cf8;
              margin-bottom:16px;
              display:flex;gap:16px;flex-wrap:wrap">
    <span>PAPER ONLY</span>
    <span>ORDERS BLOCKED</span>
    <span>SIMULATOR MONITOR ACTIVE</span>
    <span>DYNAMIC BS PORTFOLIO GREEKS</span>
    <span style="margin-left:auto;color:var(--nx-text-3)">
      Polling Interval: 15s
    </span>
  </div>

  <div *ngIf="loadError"
       class="nx-card"
       style="margin-bottom:16px;border-color:rgba(239,68,68,.35)">
    <span class="nx-label">LIVE PAPER API ERROR</span>
    <div style="font-size:16px;color:var(--nx-danger);font-weight:600">
      One or more live-paper combo endpoints failed
    </div>
    <div style="font-size:12px;color:var(--nx-text-3);margin-top:6px">
      Verify backend paper simulator is configured and running.
    </div>
  </div>

  <mat-tab-group color="accent" animationDuration="150ms">
    
    <!-- Tab 1: Single-Leg Positions -->
    <mat-tab label="Single-Leg Desk">
      <div style="padding-top:16px;display:flex;flex-direction:column;gap:16px">
        
        <!-- Summary Cards -->
        <div style="display:grid;
                    grid-template-columns:repeat(4,minmax(0,1fr));
                    gap:12px">
          <mat-card class="nx-card" *ngFor="let s of statCards"
                    style="padding:16px">
            <span class="nx-label">{{s.label}}</span>
            <div class="nx-value" [style.color]="s.color">
              {{s.value}}
            </div>
            <div class="nx-sub">{{s.sub}}</div>
          </mat-card>
        </div>

        <!-- Line P&L Chart -->
        <div class="nx-card">
          <div style="display:flex;justify-content:space-between;
                      align-items:center;margin-bottom:10px">
            <div>
              <span class="nx-label">CUMULATIVE P&L LINE</span>
              <div style="font-size:12px;color:var(--nx-text-3)">
                Realized performance tracking across closed paper trades
              </div>
            </div>
            <span class="nx-chip nx-chip-paper">PAPER DESK</span>
          </div>
          <div *ngIf="closedTrades.length > 1; else noPnlChart"
               echarts
               [options]="getPnLLine(closedTrades)"
               style="height:220px;width:100%">
          </div>
          <ng-template #noPnlChart>
            <div style="height:160px;display:flex;align-items:center;
                        justify-content:center;color:var(--nx-text-3);
                        font-size:13px;border:0.5px dashed var(--nx-border);
                        border-radius:8px">
              Need at least two closed trades to draw the P&L line.
            </div>
          </ng-template>
        </div>

        <!-- Open Trades table -->
        <div class="nx-card">
          <div style="display:flex;justify-content:space-between;
                      align-items:center;margin-bottom:12px">
            <div>
              <span class="nx-label">ACTIVE SINGLE-LEG POSITIONS</span>
              <div style="font-size:12px;color:var(--nx-text-3)">
                Current MTM, trailing stop-losses, and premium target parameters
              </div>
            </div>
            <span class="nx-chip nx-chip-warn">
              {{openTrades.length}} OPEN LEGS
            </span>
          </div>

          <div *ngIf="!openTrades.length"
               style="padding:28px;text-align:center;
                      color:var(--nx-text-3);font-size:13px">
            No active single-leg positions monitored.
          </div>

          <div *ngIf="openTrades.length" style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;
                          font-size:12px;min-width:980px">
              <thead>
                <tr style="color:var(--nx-text-3);font-size:10px;
                           letter-spacing:.07em;
                           border-bottom:0.5px solid var(--nx-border)">
                  <th style="text-align:left;padding:7px 8px">SYMBOL</th>
                  <th style="text-align:left;padding:7px 8px">TYPE</th>
                  <th style="text-align:right;padding:7px 8px">ENTRY PRICE</th>
                  <th style="text-align:right;padding:7px 8px">CURRENT LTP</th>
                  <th style="text-align:right;padding:7px 8px">QTY</th>
                  <th style="text-align:right;padding:7px 8px">UNREALIZED P&L</th>
                  <th style="text-align:right;padding:7px 8px">STOP LOSS</th>
                  <th style="text-align:right;padding:7px 8px">TARGET</th>
                  <th style="text-align:left;padding:7px 8px">STATUS</th>
                  <th style="text-align:right;padding:7px 8px">ACTION</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let t of openTrades"
                    style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:9px 8px;color:var(--nx-text-1);
                             font-weight:500">{{t.optionSymbol}}</td>
                  <td style="padding:9px 8px">
                    <span class="nx-chip" [ngClass]="sideChip(t.side)">
                      {{t.side}}
                    </span>
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.entryPrice}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.currentLtp}}
                  </td>
                  <td style="padding:9px 8px;text-align:right">
                    {{t.quantity}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             font-weight:600"
                      [style.color]="pnlColor(t.unrealizedPnl)">
                    INR {{t.unrealizedPnl}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.stopLoss || '-'}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.target || '-'}}
                  </td>
                  <td style="padding:9px 8px;color:var(--nx-text-3)">
                    <span class="nx-chip nx-chip-neutral">{{t.status}}</span>
                  </td>
                  <td style="padding:9px 8px;text-align:right">
                    <button mat-flat-button (click)="exitSingleTrade(t.id)" 
                            style="background:var(--nx-danger);color:#fff;font-size:10px;height:24px;line-height:24px;padding:0 8px">
                      Exit
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Closed Trades Table -->
        <div class="nx-card">
          <div style="display:flex;justify-content:space-between;
                      align-items:center;margin-bottom:12px">
            <div>
              <span class="nx-label">REALIZED POSITIONS JOURNAL</span>
              <div style="font-size:12px;color:var(--nx-text-3)">
                Realized paper logs, exit triggers, and timestamps
              </div>
            </div>
            <span class="nx-chip nx-chip-info">
              {{closedTrades.length}} CLOSED
            </span>
          </div>

          <div *ngIf="!closedTrades.length"
               style="padding:28px;text-align:center;
                      color:var(--nx-text-3);font-size:13px">
            No realized single-leg trades reported.
          </div>

          <div *ngIf="closedTrades.length" style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;
                          font-size:12px;min-width:1080px">
              <thead>
                <tr style="color:var(--nx-text-3);font-size:10px;
                           letter-spacing:.07em;
                           border-bottom:0.5px solid var(--nx-border)">
                  <th style="text-align:left;padding:7px 8px">SYMBOL</th>
                  <th style="text-align:left;padding:7px 8px">TYPE</th>
                  <th style="text-align:right;padding:7px 8px">ENTRY</th>
                  <th style="text-align:right;padding:7px 8px">EXIT</th>
                  <th style="text-align:right;padding:7px 8px">QTY</th>
                  <th style="text-align:right;padding:7px 8px">REALIZED P&L</th>
                  <th style="text-align:left;padding:7px 8px">EXIT REASON</th>
                  <th style="text-align:left;padding:7px 8px">EXIT TIME</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let t of closedTrades"
                    style="border-bottom:0.5px solid var(--nx-border)">
                  <td style="padding:9px 8px;color:var(--nx-text-1);
                             font-weight:500">{{t.optionSymbol}}</td>
                  <td style="padding:9px 8px">
                    <span class="nx-chip" [ngClass]="sideChip(t.side)">
                      {{t.side}}
                    </span>
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.entryPrice}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             color:var(--nx-text-2)">
                    {{t.exitPrice}}
                  </td>
                  <td style="padding:9px 8px;text-align:right">
                    {{t.quantity}}
                  </td>
                  <td style="padding:9px 8px;text-align:right;
                             font-weight:600"
                      [style.color]="pnlColor(t.realizedPnl)">
                    INR {{t.realizedPnl}}
                  </td>
                  <td style="padding:9px 8px;color:var(--nx-text-3)">
                    {{t.exitReason}}
                  </td>
                  <td style="padding:9px 8px;color:var(--nx-text-3)">
                    {{formatTime(t.exitTime)}}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </mat-tab>

    <!-- Tab 2: Multi-Leg Option Combo Lab -->
    <mat-tab label="Multi-Leg Combo Lab">
      <div style="padding-top:16px;display:flex;gap:20px;flex-wrap:wrap">
        
        <!-- Left Column: Combo Execution Wizard -->
        <div style="flex:1 1 500px;min-width:350px;display:flex;flex-direction:column;gap:16px">
          
          <div class="nx-card">
            <span class="nx-label">OPTION SPREAD WIZARD</span>
            <p style="font-size:11px;color:var(--nx-text-3);margin:4px 0 12px;line-height:1.4">
              Select a predefined option strategy or customize leg parameters. 
              The simulator supports simultaneous entries and provides dynamic margin estimations.
            </p>

            <mat-form-field appearance="outline" style="width:100%" class="compact-form">
              <mat-label>Option Combination Strategy</mat-label>
              <mat-select [(ngModel)]="selectedComboTemplate" (selectionChange)="onComboTemplateSelect()">
                <mat-option value="CUSTOM">-- Custom Option combination --</mat-option>
                <mat-option value="BULL_CALL">Bull Call Spread (2 legs)</mat-option>
                <mat-option value="BEAR_PUT">Bear Put Spread (2 legs)</mat-option>
                <mat-option value="STRADDLE">Long Straddle (2 legs)</mat-option>
                <mat-option value="STRANGLE">Long Strangle (2 legs)</mat-option>
                <mat-option value="IRON_CONDOR">Iron Condor (4 legs)</mat-option>
              </mat-select>
            </mat-form-field>

            <div style="margin-top:10px">
              <mat-form-field appearance="outline" style="width:100%" class="compact-form">
                <mat-label>Custom Combination Name</mat-label>
                <input matInput [(ngModel)]="newComboName" placeholder="e.g. NIFTY Iron Condor Spread">
              </mat-form-field>
            </div>

            <!-- Predefined Legs List -->
            <div style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
              <span class="nx-label" style="font-size:10px">COMBINATION LEGS (CONTRACT DETAILS)</span>
              
              <div *ngFor="let leg of newComboLegs; let i = index" 
                   style="background:var(--nx-bg-raised);border:0.5px solid var(--nx-border);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:8px">
                
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span style="font-size:12px;font-weight:700;color:var(--nx-accent)">Leg #{{i + 1}}</span>
                  <button mat-icon-button (click)="removeLeg(i)" 
                          [disabled]="newComboLegs.length <= 1"
                          style="width:24px;height:24px;color:var(--nx-text-3)">
                    <mat-icon style="font-size:14px;width:14px;height:14px">close</mat-icon>
                  </button>
                </div>

                <div style="display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:8px">
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Leg Symbol</mat-label>
                    <input matInput [(ngModel)]="leg.symbol" (ngModelChange)="estimateMarginAndPremium()">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Strike</mat-label>
                    <input matInput type="number" [(ngModel)]="leg.strike" (ngModelChange)="estimateMarginAndPremium()">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Expiry</mat-label>
                    <input matInput [(ngModel)]="leg.expiry" placeholder="YYYY-MM-DD" (ngModelChange)="estimateMarginAndPremium()">
                  </mat-form-field>
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px">
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Type</mat-label>
                    <mat-select [(ngModel)]="leg.option_type" (selectionChange)="estimateMarginAndPremium()">
                      <mat-option value="CE">CE</mat-option>
                      <mat-option value="PE">PE</mat-option>
                    </mat-select>
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Direction</mat-label>
                    <mat-select [(ngModel)]="leg.direction" (selectionChange)="estimateMarginAndPremium()">
                      <mat-option value="BUY">BUY (Long)</mat-option>
                      <mat-option value="SELL">SELL (Short)</mat-option>
                    </mat-select>
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Entry price</mat-label>
                    <input matInput type="number" [(ngModel)]="leg.entry_price" (ngModelChange)="estimateMarginAndPremium()">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="compact-form">
                    <mat-label>Quantity</mat-label>
                    <input matInput type="number" [(ngModel)]="leg.quantity" (ngModelChange)="estimateMarginAndPremium()">
                  </mat-form-field>
                </div>

              </div>

              <button mat-stroked-button (click)="addLeg()" style="color:var(--nx-text-2);margin-top:4px">
                <mat-icon>add</mat-icon> Add Custom Leg
              </button>
            </div>

            <!-- Dynamic Margin & Net Premium estimations -->
            <div style="margin-top:16px;background:rgba(124,58,237,.06);border:0.5px solid rgba(124,58,237,.3);border-radius:8px;padding:12px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
              <div>
                <span class="nx-label" style="font-size:9px">EST. MARGIN REQUIRED</span>
                <div style="font-size:18px;font-weight:700;color:var(--nx-text-1)">
                  INR {{estMargin | number:'1.0-2'}}
                </div>
                <div style="font-size:9px;color:var(--nx-text-3);margin-top:2px">Long prem + short margins</div>
              </div>
              <div>
                <span class="nx-label" style="font-size:9px">NET PREMIUM DEPLOYMENT</span>
                <div style="font-size:18px;font-weight:700"
                     [style.color]="estNetPremium >= 0 ? 'var(--nx-warning)' : 'var(--nx-success)'">
                  {{estNetPremium >= 0 ? 'Debit: ' : 'Credit: '}}INR {{absNum(estMargin) | number:'1.0-2'}}
                </div>
                <div style="font-size:9px;color:var(--nx-text-3);margin-top:2px">Paid vs received premium</div>
              </div>
            </div>

            <button mat-flat-button (click)="executeCombo()" 
                    [disabled]="comboLoading" 
                    style="background:var(--nx-success);color:#fff;font-weight:600;width:100%;margin-top:16px">
              <mat-icon>play_circle</mat-icon> EXECUTE OPTION COMBINATION
            </button>
            <mat-progress-bar *ngIf="comboLoading" mode="indeterminate" color="accent" style="margin-top:10px"></mat-progress-bar>
          </div>

        </div>

        <!-- Right Column: Open Combinations & Portfolio Greeks -->
        <div style="flex:1.5 1 600px;min-width:400px;display:flex;flex-direction:column;gap:16px">
          
          <!-- Open Combos Cockpit -->
          <div class="nx-card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
              <div>
                <span class="nx-label">ACTIVE MULTI-LEG OPTION COMBINATIONS</span>
                <div style="font-size:12px;color:var(--nx-text-3)">
                  Open spreads, dynamic portfolio margins, decay rates, and absolute Greeks
                </div>
              </div>
              <span class="nx-chip nx-chip-warn">{{openCombos.length}} OPEN SPREADS</span>
            </div>

            <div *ngIf="!openCombos.length" 
                 style="text-align:center;padding:64px 0;color:var(--nx-text-3);font-size:13px">
              <mat-icon style="font-size:40px;width:40px;height:40px;margin-bottom:12px;color:var(--nx-text-3)">schema</mat-icon>
              <div>No active multi-leg positions monitored.</div>
              <div style="font-size:11px;color:var(--nx-text-3);margin-top:4px">
                Build and execute spreads using the Wizard on the left.
              </div>
            </div>

            <!-- Loop of Combos -->
            <div style="display:flex;flex-direction:column;gap:16px">
              <div *ngFor="let combo of openCombos" 
                   style="border:0.5px solid var(--nx-border);border-radius:10px;padding:16px;background:var(--nx-bg-raised);position:relative">
                
                <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:0.5px solid var(--nx-border);padding-bottom:10px;margin-bottom:12px">
                  <div>
                    <h3 style="font-size:14px;font-weight:700;color:var(--nx-text-1);margin:0">
                      {{combo.name}}
                    </h3>
                    <span style="font-size:10px;color:var(--nx-text-3)">Executed at {{formatTime(combo.created_at)}}</span>
                  </div>
                  <div style="text-align:right">
                    <span class="nx-label" style="font-size:8px">UNREALIZED P&L</span>
                    <div style="font-size:18px;font-weight:700" 
                         [style.color]="combo.unrealized_pnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                      {{combo.unrealized_pnl >= 0 ? '+' : ''}}INR {{combo.unrealized_pnl | number:'1.0-2'}}
                    </div>
                  </div>
                </div>

                <!-- Portfolio Greeks Dashboard -->
                <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:10px;background:var(--nx-bg);border-radius:8px;padding:10px;margin-bottom:12px">
                  <div style="text-align:center">
                    <span style="font-size:8px;color:var(--nx-text-3)">MARGIN</span>
                    <div style="font-size:12px;font-weight:700;color:var(--nx-text-1)">₹{{combo.margin_required | number:'1.0-0'}}</div>
                  </div>
                  <div style="text-align:center">
                    <span style="font-size:8px;color:var(--nx-text-3)">PORTFOLIO THETA</span>
                    <div style="font-size:12px;font-weight:700" [style.color]="combo.unified_theta >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                      {{combo.unified_theta >= 0 ? '+' : ''}}{{combo.unified_theta}} INR/day
                    </div>
                  </div>
                  <div style="text-align:center">
                    <span style="font-size:8px;color:var(--nx-text-3)">PORTFOLIO GAMMA</span>
                    <div style="font-size:12px;font-weight:700;color:var(--nx-text-1)">{{combo.unified_gamma}}</div>
                  </div>
                  <div style="text-align:center">
                    <span style="font-size:8px;color:var(--nx-text-3)">PORTFOLIO DELTA</span>
                    <div style="font-size:12px;font-weight:700" [style.color]="combo.unified_delta >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)'">
                      {{combo.unified_delta >= 0 ? '+' : ''}}{{combo.unified_delta}}
                    </div>
                  </div>
                </div>

                <!-- Legs list table -->
                <div style="overflow-x:auto;margin-bottom:12px">
                  <table style="width:100%;border-collapse:collapse;font-size:11px">
                    <thead>
                      <tr style="text-align:left;color:var(--nx-text-3);border-bottom:0.5px solid var(--nx-border)">
                        <th style="padding:4px">LEG</th>
                        <th style="padding:4px">SIDE</th>
                        <th style="padding:4px;text-align:right">ENTRY</th>
                        <th style="padding:4px;text-align:right">LTP</th>
                        <th style="padding:4px;text-align:right">QTY</th>
                        <th style="padding:4px;text-align:right">UNREALIZED</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr *ngFor="let leg of combo.legs" style="border-bottom:0.5px solid var(--nx-border)">
                        <td style="padding:6px 4px;font-weight:500;color:var(--nx-text-1)">{{leg.symbol}}</td>
                        <td style="padding:6px 4px">
                          <span class="nx-chip" [ngClass]="sideChip(leg.signal_type || leg.direction)">
                            {{leg.direction}}
                          </span>
                        </td>
                        <td style="padding:6px 4px;text-align:right">{{leg.entry_price}}</td>
                        <td style="padding:6px 4px;text-align:right">{{leg.current_price || leg.entry_price}}</td>
                        <td style="padding:6px 4px;text-align:right">{{leg.quantity}}</td>
                        <td style="padding:6px 4px;text-align:right;font-weight:600" 
                            [style.color]="pnlColor(leg.unrealized_pnl)">
                          {{leg.unrealized_pnl >= 0 ? '+' : ''}}{{leg.unrealized_pnl | number:'1.0-2'}}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <!-- Exit combo button -->
                <button mat-flat-button (click)="exitCombo(combo.id)" 
                        style="background:var(--nx-danger);color:#fff;width:100%;font-weight:600">
                  <mat-icon>close</mat-icon> SQUARE OFF ALL SPREAD LEGS
                </button>

              </div>
            </div>
          </div>

          <!-- Closed Combos Journal -->
          <div class="nx-card">
            <span class="nx-label">HISTORICAL SPREAD POSITIONS REALIZED</span>
            <div style="font-size:12px;color:var(--nx-text-3);margin-bottom:10px">Historical combo P&L journal</div>
            
            <div *ngIf="!closedCombos.length" 
                 style="text-align:center;padding:24px 0;color:var(--nx-text-3);font-size:12px">
              No historical combo records found.
            </div>

            <div *ngIf="closedCombos.length" style="overflow-x:auto">
              <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead>
                  <tr style="text-align:left;color:var(--nx-text-3);border-bottom:0.5px solid var(--nx-border);font-size:10px">
                    <th style="padding:6px 4px">STRATEGY</th>
                    <th style="padding:6px 4px">EXECUTED TIME</th>
                    <th style="padding:6px 4px">CLOSED TIME</th>
                    <th style="padding:6px 4px;text-align:right">MARGIN</th>
                    <th style="padding:6px 4px;text-align:right">REALIZED P&L</th>
                  </tr>
                </thead>
                <tbody>
                  <tr *ngFor="let combo of closedCombos" style="border-bottom:0.5px solid var(--nx-border)">
                    <td style="padding:8px 4px;font-weight:600;color:var(--nx-text-1)">{{combo.name}}</td>
                    <td style="padding:8px 4px;color:var(--nx-text-3);font-size:11px">{{formatTime(combo.created_at)}}</td>
                    <td style="padding:8px 4px;color:var(--nx-text-3);font-size:11px">{{formatTime(combo.closed_at)}}</td>
                    <td style="padding:8px 4px;text-align:right">₹{{combo.margin_required | number:'1.0-0'}}</td>
                    <td style="padding:8px 4px;text-align:right;font-weight:600" 
                        [style.color]="pnlColor(combo.pnl)">
                      {{combo.pnl >= 0 ? '+' : ''}}INR {{combo.pnl | number:'1.0-2'}}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

        </div>

      </div>
    </mat-tab>
  </mat-tab-group>

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
  `]
})
export class LivePaperComponent implements OnInit, OnDestroy {
  readonly endpoints = [
    '/api/live-paper/performance',
    '/api/live-paper/closed-trades',
    '/api/live-paper/open-trades',
    '/api/live-paper/combos/open',
    '/api/live-paper/combos/closed'
  ];

  performance: any = null;
  openTrades: TradeRow[] = [];
  closedTrades: TradeRow[] = [];
  
  // Combo states
  openCombos: any[] = [];
  closedCombos: any[] = [];
  
  // Combo template wizard fields
  selectedComboTemplate = 'CUSTOM';
  newComboName = 'NIFTY Bull Call Spread';
  newComboLegs: ComboLeg[] = [
    { symbol: 'NIFTY2652822000CE', expiry: '2026-05-28', strike: 22000, option_type: 'CE', direction: 'BUY', entry_price: 110.0, quantity: 50 }
  ];

  estMargin = 0.0;
  estNetPremium = 0.0;
  
  lastUpdated = 'never';
  loadError = false;
  comboLoading = false;
  private sub?: Subscription;

  get statCards(): any[] {
    const netPnl = this.netPnl;
    return [
      {
        label: 'OPEN TRADES',
        value: this.openTrades.length,
        sub: 'currently active',
        color: 'var(--nx-cyan)',
      },
      {
        label: 'CLOSED TRADES',
        value: this.closedTrades.length,
        sub: 'completed exits',
        color: 'var(--nx-accent)',
      },
      {
        label: 'NET P&L',
        value: this.money(netPnl),
        sub: 'realized + open MTM',
        color: netPnl >= 0 ? 'var(--nx-success)' : 'var(--nx-danger)',
      },
      {
        label: 'WIN RATE',
        value: this.winRate + '%',
        sub: this.wins + 'W / ' + this.losses + 'L',
        color: Number(this.winRate) >= 50
          ? 'var(--nx-success)' : 'var(--nx-warning)',
      },
    ];
  }

  get wins(): number {
    return this.closedTrades.filter((trade) =>
      this.toNumber(trade.realizedPnl) > 0).length;
  }

  get losses(): number {
    return this.closedTrades.filter((trade) =>
      this.toNumber(trade.realizedPnl) < 0).length;
  }

  get winRate(): string {
    const total = this.wins + this.losses;
    if (!total) return '0';
    return Math.round((this.wins / total) * 100).toString();
  }

  get netPnl(): number {
    const perfValue = this.findValue(this.performance, [
      'total_pnl',
      'totalPnl',
      'net_pnl',
      'realized_pnl',
      'realizedPnl',
    ]);
    if (perfValue !== undefined && perfValue !== null) {
      return this.toNumber(perfValue);
    }
    const realized = this.closedTrades.reduce((sum, trade) =>
      sum + this.toNumber(trade.realizedPnl), 0);
    const unrealized = this.openTrades.reduce((sum, trade) =>
      sum + this.toNumber(trade.unrealizedPnl), 0);
    return Math.round((realized + unrealized) * 100) / 100;
  }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.sub = interval(15000).pipe(
      startWith(0),
      switchMap(() => this.load())
    ).subscribe((state) => this.applyState(state));
    this.onComboTemplateSelect();
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  refresh() {
    this.load().subscribe((state) => this.applyState(state));
  }

  absNum(val: number): number {
    return Math.abs(val);
  }

  onComboTemplateSelect() {
    const todayStr = '2026-05-28';
    if (this.selectedComboTemplate === 'BULL_CALL') {
      this.newComboName = 'NIFTY Bull Call Spread';
      this.newComboLegs = [
        { symbol: 'NIFTY2652822000CE', expiry: todayStr, strike: 22000, option_type: 'CE', direction: 'BUY', entry_price: 110.0, quantity: 50 },
        { symbol: 'NIFTY2652822100CE', expiry: todayStr, strike: 22100, option_type: 'CE', direction: 'SELL', entry_price: 65.0, quantity: 50 }
      ];
    } else if (this.selectedComboTemplate === 'BEAR_PUT') {
      this.newComboName = 'NIFTY Bear Put Spread';
      this.newComboLegs = [
        { symbol: 'NIFTY2652822000PE', expiry: todayStr, strike: 22000, option_type: 'PE', direction: 'BUY', entry_price: 95.0, quantity: 50 },
        { symbol: 'NIFTY2652821900PE', expiry: todayStr, strike: 21900, option_type: 'PE', direction: 'SELL', entry_price: 52.0, quantity: 50 }
      ];
    } else if (this.selectedComboTemplate === 'STRADDLE') {
      this.newComboName = 'NIFTY Long Straddle';
      this.newComboLegs = [
        { symbol: 'NIFTY2652822000CE', expiry: todayStr, strike: 22000, option_type: 'CE', direction: 'BUY', entry_price: 110.0, quantity: 50 },
        { symbol: 'NIFTY2652822000PE', expiry: todayStr, strike: 22000, option_type: 'PE', direction: 'BUY', entry_price: 95.0, quantity: 50 }
      ];
    } else if (this.selectedComboTemplate === 'STRANGLE') {
      this.newComboName = 'NIFTY Long Strangle';
      this.newComboLegs = [
        { symbol: 'NIFTY2652822100CE', expiry: todayStr, strike: 22100, option_type: 'CE', direction: 'BUY', entry_price: 65.0, quantity: 50 },
        { symbol: 'NIFTY2652821900PE', expiry: todayStr, strike: 21900, option_type: 'PE', direction: 'BUY', entry_price: 52.0, quantity: 50 }
      ];
    } else if (this.selectedComboTemplate === 'IRON_CONDOR') {
      this.newComboName = 'NIFTY Iron Condor';
      this.newComboLegs = [
        { symbol: 'NIFTY2652821800PE', expiry: todayStr, strike: 21800, option_type: 'PE', direction: 'BUY', entry_price: 25.0, quantity: 50 },
        { symbol: 'NIFTY2652821900PE', expiry: todayStr, strike: 21900, option_type: 'PE', direction: 'SELL', entry_price: 52.0, quantity: 50 },
        { symbol: 'NIFTY2652822100CE', expiry: todayStr, strike: 22100, option_type: 'CE', direction: 'SELL', entry_price: 65.0, quantity: 50 },
        { symbol: 'NIFTY2652822200CE', expiry: todayStr, strike: 22200, option_type: 'CE', direction: 'BUY', entry_price: 30.0, quantity: 50 }
      ];
    } else {
      this.newComboName = 'Custom NIFTY Option Spread';
      this.newComboLegs = [
        { symbol: 'NIFTY2652822000CE', expiry: todayStr, strike: 22000, option_type: 'CE', direction: 'BUY', entry_price: 110.0, quantity: 50 }
      ];
    }
    this.estimateMarginAndPremium();
  }

  addLeg() {
    const todayStr = '2026-05-28';
    this.newComboLegs.push({
      symbol: 'NIFTY2652822000CE',
      expiry: todayStr,
      strike: 22000,
      option_type: 'CE',
      direction: 'BUY',
      entry_price: 100.0,
      quantity: 50
    });
    this.estimateMarginAndPremium();
  }

  removeLeg(index: number) {
    if (this.newComboLegs.length > 1) {
      this.newComboLegs.splice(index, 1);
    }
    this.estimateMarginAndPremium();
  }

  estimateMarginAndPremium() {
    let total = 0.0;
    let net = 0.0;
    const lotSize = 50;
    const spot = 22000.0;
    
    const hasBuy = this.newComboLegs.some(l => l.direction === 'BUY');
    const hasSell = this.newComboLegs.some(l => l.direction === 'SELL');
    const isHedged = hasBuy && hasSell;

    for (const leg of this.newComboLegs) {
      const prem = (leg.entry_price || 0) * (leg.quantity || 0) * lotSize;
      if (leg.direction === 'BUY') {
        total += prem;
        net += prem;
      } else {
        let shortMargin = (spot * 0.12) * (leg.quantity || 0) * lotSize;
        if (isHedged) {
          shortMargin *= 0.50; // Apply 50% spread hedging margin offset
        }
        total += shortMargin;
        net -= prem;
      }
    }
    this.estMargin = total;
    this.estNetPremium = net;
  }

  executeCombo() {
    this.comboLoading = true;
    const payload = {
      name: this.newComboName,
      legs: this.newComboLegs
    };
    this.http.post<any>('/api/live-paper/combos', payload)
      .pipe(catchError((err) => {
        alert(err?.error?.detail || 'Execution failed. Check parameters and available virtual capital.');
        this.comboLoading = false;
        return of(null);
      }))
      .subscribe(res => {
        this.comboLoading = false;
        if (!res) return;
        if (res.ok) {
          alert('Option spread combination executed successfully!');
          this.refresh();
        } else {
          alert(res.message || 'Execution failed.');
        }
      });
  }

  exitCombo(comboId: number) {
    if (!confirm('Are you sure you want to square off all legs of this spread?')) return;
    this.http.post<any>(`/api/live-paper/combos/${comboId}/manual-exit`, {})
      .subscribe(() => {
        alert('Spread legs squared off successfully!');
        this.refresh();
      });
  }

  exitSingleTrade(tradeId: number) {
    if (!confirm('Are you sure you want to manually exit this single position?')) return;
    this.http.post<any>(`/api/live-paper/trades/${tradeId}/manual-exit`, {})
      .subscribe(() => {
        alert('Position exited successfully!');
        this.refresh();
      });
  }

  getPnLLine(trades: any[]): object {
    const closed = (trades || []).filter((trade) =>
      trade.exitTime || trade.exit_time);
    if (!closed.length) return {};

    let running = 0;
    const labels: string[] = [];
    const values: number[] = [];
    closed.forEach((trade, index) => {
      running = Math.round(
        (running + this.toNumber(
          trade.realizedPnl ?? trade.realized_pnl
          ?? trade.pnl ?? trade.net_pnl
        )) * 100
      ) / 100;
      labels.push('T' + (index + 1));
      values.push(running);
    });

    const isUp = values[values.length - 1] >= 0;
    const lineColor = isUp ? '#10b981' : '#ef4444';
    return {
      backgroundColor: 'transparent',
      animation: true,
      grid: { left: 54, right: 18, top: 18, bottom: 32 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderColor: '#334155',
        borderWidth: 0.5,
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: (params: any[]) => {
          const point = params[0];
          return point.name + '&nbsp;&nbsp;<b>' +
            this.money(Number(point.value || 0)) + '</b>';
        },
      },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#1e293b' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#64748b',
          fontSize: 10,
          formatter: (value: number) => this.money(value),
        },
        splitLine: { lineStyle: { color: '#1e293b', width: 0.5 } },
        axisLine: { show: false },
      },
      series: [{
        name: 'Cumulative P&L',
        type: 'line',
        data: values,
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: lineColor, width: 2 },
        itemStyle: {
          color: lineColor,
          borderColor: '#0a0f1e',
          borderWidth: 2,
        },
        areaStyle: { color: lineColor, opacity: 0.08 },
        markLine: {
          silent: true,
          lineStyle: { color: '#475569', width: 0.5, type: 'dashed' },
          data: [{ yAxis: 0, label: { show: false } }],
        },
      }],
    };
  }

  sideChip(side: string): string {
    const text = (side || '').toUpperCase();
    if (text.includes('CALL') || text.includes('CE') || text === 'BUY') return 'nx-chip-ok';
    if (text.includes('PUT') || text.includes('PE') || text === 'SELL') return 'nx-chip-fail';
    return 'nx-chip-paper';
  }

  pnlColor(value: unknown): string {
    const numberValue = this.toNumber(value);
    if (numberValue > 0) return 'var(--nx-success)';
    if (numberValue < 0) return 'var(--nx-danger)';
    return 'var(--nx-text-2)';
  }

  formatTime(value: unknown): string {
    const text = String(value || '');
    if (!text || text === '-') return '-';
    if (text.includes('T')) return text.slice(11, 19);
    if (text.includes(' ')) return text.split(' ').slice(-1)[0];
    return text;
  }

  private load() {
    return forkJoin({
      performance: this.safeGet(this.endpoints[0]),
      closed: this.safeGet(this.endpoints[1]),
      open: this.safeGet(this.endpoints[2]),
      combosOpen: this.safeGet(this.endpoints[3]),
      combosClosed: this.safeGet(this.endpoints[4])
    });
  }

  private safeGet(path: string) {
    return this.http.get<any>(path).pipe(
      catchError(() => of({ __error: true }))
    );
  }

  private applyState(state: any) {
    this.performance = state.performance?.__error ? null : state.performance;
    this.openTrades = this.arrayFrom(state.open, ['items', 'trades'])
      .map((trade) => this.openTradeRow(trade));
    this.closedTrades = this.arrayFrom(state.closed, ['items', 'trades'])
      .map((trade) => this.closedTradeRow(trade));
    
    // Combo loads
    this.openCombos = state.combosOpen?.__error ? [] : (state.combosOpen?.items ?? []);
    this.closedCombos = state.combosClosed?.__error ? [] : (state.combosClosed?.items ?? []);

    this.loadError = Boolean(
      state.performance?.__error || state.open?.__error || state.closed?.__error ||
      state.combosOpen?.__error || state.combosClosed?.__error
    );
    this.lastUpdated = new Date().toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
    });
  }

  private openTradeRow(trade: unknown): TradeRow {
    return {
      id: this.text(this.findValue(trade, ['id', 'trade_id']), '-'),
      entryTime: this.text(
        this.findValue(trade, ['entryTime', 'entry_time', 'created_at', 'opened_at']),
        '-'
      ),
      underlying: this.text(this.findValue(trade, ['underlying', 'symbol']), '-'),
      optionSymbol: this.text(
        this.findValue(trade, [
          'optionSymbol',
          'option_symbol',
          'instrument_symbol',
          'tradingsymbol',
          'symbol',
        ]),
        '-'
      ),
      side: this.text(this.findValue(trade, ['side', 'signal_type', 'signalType', 'decision']), '-'),
      quantity: this.text(this.findValue(trade, ['quantity', 'qty']), '-'),
      entryPrice: this.text(this.findValue(trade, ['entryPrice', 'entry_price']), '-'),
      currentLtp: this.text(
        this.findValue(trade, ['currentLtp', 'current_ltp', 'ltp', 'last_price', 'current_price']),
        '-'
      ),
      unrealizedPnl: this.text(
        this.findValue(trade, ['unrealizedPnl', 'unrealized_pnl', 'pnl']),
        '0'
      ),
      pnlPercent: this.text(this.findValue(trade, ['pnlPercent', 'pnl_percent', 'return_percent']), '-'),
      stopLoss: this.text(this.findValue(trade, ['stopLoss', 'stop_loss', 'sl_price']), '-'),
      target: this.text(
        this.findValue(trade, ['target', 'target_price', 'target_1', 'target_2']),
        '-'
      ),
      trailingStop: this.text(
        this.findValue(trade, ['trailingStop', 'trailing_stop', 'trailing_sl', 'trailing_stop_price']),
        '-'
      ),
      status: this.text(this.findValue(trade, ['status']), 'OPEN'),
      exitReason: this.text(this.findValue(trade, ['exitReason', 'exit_reason', 'reason']), '-'),
      source: this.text(this.findValue(trade, ['source', 'signal_source']), 'LIVE_PAPER'),
    };
  }

  private closedTradeRow(trade: unknown): TradeRow {
    const row = this.openTradeRow(trade);
    const realizedPnl = this.text(
      this.findValue(trade, ['realizedPnl', 'realized_pnl', 'pnl', 'net_pnl']),
      '0'
    );
    return {
      ...row,
      exitTime: this.text(this.findValue(trade, ['exitTime', 'exit_time', 'closed_at']), '-'),
      exitPrice: this.text(this.findValue(trade, ['exitPrice', 'exit_price']), '-'),
      currentLtp: this.text(
        this.findValue(trade, ['currentLtp', 'current_ltp', 'ltp', 'last_price', 'exit_price']),
        '-'
      ),
      realizedPnl,
      exitReason: this.text(this.findValue(trade, ['exitReason', 'exit_reason', 'reason']), 'UNKNOWN'),
      result: this.toNumber(realizedPnl) > 0
        ? 'WIN' : this.toNumber(realizedPnl) < 0 ? 'LOSS' : 'BREAKEVEN',
    };
  }

  private arrayFrom(value: unknown, keys: string[]): unknown[] {
    if (Array.isArray(value)) return value;
    const found = this.findValue(value, keys);
    return Array.isArray(found) ? found : [];
  }

  private findValue(value: unknown, keys: string[]): unknown {
    const seen = new Set<unknown>();
    const search = (current: unknown): unknown => {
      if (!current || typeof current !== 'object' || seen.has(current)) {
        return undefined;
      }
      seen.add(current);
      if (Array.isArray(current)) {
        for (const item of current) {
          const found = search(item);
          if (found !== undefined) return found;
        }
        return undefined;
      }
      const record = current as Record<string, unknown>;
      for (const key of keys) {
        if (record[key] !== undefined && record[key] !== null) {
          return record[key];
        }
      }
      for (const item of Object.values(record)) {
        const found = search(item);
        if (found !== undefined) return found;
      }
      return undefined;
    };
    return search(value);
  }

  private text(value: unknown, fallback: string): string {
    if (value === undefined || value === null || value === '') return fallback;
    if (typeof value === 'number') {
      return Number.isFinite(value) ? String(Number(value.toFixed(2))) : fallback;
    }
    return String(value);
  }

  private toNumber(value: unknown): number {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : 0;
  }

  private money(value: number): string {
    const sign = value > 0 ? '+' : '';
    return sign + 'Rs ' + Number(value.toFixed(2)).toLocaleString('en-IN');
  }
}
