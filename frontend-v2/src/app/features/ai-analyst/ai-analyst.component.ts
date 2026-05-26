import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTabsModule } from '@angular/material/tabs';
import { catchError, finalize, of, timeout } from 'rxjs';
import { marked } from 'marked';

@Component({
  selector: 'app-ai-analyst',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatButtonModule, MatTabsModule],
  templateUrl: './ai-analyst.component.html',
  styleUrl: './ai-analyst.component.scss'
})
export class AiAnalystComponent implements OnInit {
  isConfigured = signal<boolean | null>(null);
  loadingMarket = signal(false);
  loadingReport = signal(false);
  
  marketStructureHtml = signal<string>('');
  postMarketHtml = signal<string>('');
  
  errorMarket = signal<string | null>(null);
  errorReport = signal<string | null>(null);

  provider = signal<string>('ollama');
  providers = signal<any>({});

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.checkStatus();
  }

  setProvider(p: string) {
    this.provider.set(p);
    this.fetchMarketStructure();
  }

  checkStatus() {
    this.http.get<any>('/api/ai/status')
      .pipe(catchError(() => of(null)))
      .subscribe(r => {
        if (r) {
          this.isConfigured.set(r.configured || r.is_ready);
          this.providers.set(r.providers || {});
          
          const configuredProviders = r.providers || {};
          const preferred = r.default_provider;
          if (preferred && configuredProviders[preferred]?.configured) {
            this.provider.set(preferred);
          } else if (configuredProviders.gemini?.configured) {
            this.provider.set('gemini');
          } else if (configuredProviders.openai?.configured) {
            this.provider.set('openai');
          } else if (configuredProviders.ollama?.configured) {
            this.provider.set('ollama');
          }
          
          if (r.configured || r.is_ready) {
            this.fetchMarketStructure();
          }
        }
      });
  }

  fetchMarketStructure() {
    if (this.loadingMarket()) return;
    this.loadingMarket.set(true);
    this.errorMarket.set(null);
    
    this.http.get<any>(`/api/ai/market-structure?provider=${encodeURIComponent(this.provider())}`)
      .pipe(
        timeout(90000),
        catchError(err => {
          this.errorMarket.set(err?.error?.detail || 'Failed to fetch market structure analysis.');
          return of(null);
        }),
        finalize(() => this.loadingMarket.set(false))
      )
      .subscribe(async r => {
        if (r) {
          const html = await marked.parse(this.marketStructureToMarkdown(r));
          this.marketStructureHtml.set(html);
        } else if (r && r.error) {
          this.errorMarket.set(r.error);
        }
      });
  }

  fetchPostMarketReport() {
    if (this.loadingReport()) return;
    this.loadingReport.set(true);
    this.errorReport.set(null);
    
    this.http.get<any>(`/api/ai/post-market-report?provider=${encodeURIComponent(this.provider())}`)
      .pipe(
        timeout(90000),
        catchError(err => {
          this.errorReport.set(err?.error?.detail || 'Failed to generate post-market report.');
          return of(null);
        }),
        finalize(() => this.loadingReport.set(false))
      )
      .subscribe(async r => {
        if (r) {
          const html = await marked.parse(this.postMarketToMarkdown(r));
          this.postMarketHtml.set(html);
        } else if (r && r.error) {
          this.errorReport.set(r.error);
        }
      });
  }

  private marketStructureToMarkdown(response: any): string {
    if (response?.analysis) return String(response.analysis);
    if (typeof response === 'string') return response;

    const traps = Array.isArray(response?.traps_identified) && response.traps_identified.length
      ? response.traps_identified
          .map((trap: any) => `- **${trap.type || 'TRAP'} ${trap.strike ?? ''}** (${trap.severity || 'UNKNOWN'}): ${trap.description || '-'}`)
          .join('\n')
      : '- No major traps identified.';

    const support = this.formatLevels(response?.key_levels?.support);
    const resistance = this.formatLevels(response?.key_levels?.resistance);

    return `
## ${response?.sentiment || 'Market Structure'} ${response?.confidence_score ? `(${response.confidence_score}/100)` : ''}

${response?.executive_summary || 'AI response received, but no executive summary was provided.'}

### Path Of Least Resistance
${response?.path_of_least_resistance || '-'}

### Institutional Bias
${response?.institutional_bias || '-'}

### Key Levels
- **Support:** ${support}
- **Resistance:** ${resistance}

### Traps Identified
${traps}
`.trim();
  }

  private postMarketToMarkdown(response: any): string {
    if (response?.report) return String(response.report);
    if (response?.summary) {
      return `
## Performance Rating: ${response.performance_rating || '-'}

${response.summary}

### What Went Right
${this.formatBullets(response.what_went_right)}

### What Went Wrong
${this.formatBullets(response.what_went_wrong)}

### Suggestions
${this.formatBullets(response.suggestions_for_improvement)}

### Market Regime
${response.market_regime_identified || '-'}
`.trim();
    }
    return `\`\`\`json\n${JSON.stringify(response, null, 2)}\n\`\`\``;
  }

  private formatLevels(values: unknown): string {
    return Array.isArray(values) && values.length ? values.join(', ') : '-';
  }

  private formatBullets(values: unknown): string {
    return Array.isArray(values) && values.length
      ? values.map(item => `- ${item}`).join('\n')
      : '-';
  }
}
