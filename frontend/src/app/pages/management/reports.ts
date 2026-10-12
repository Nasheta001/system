import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { formatKes, monthStart, today } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { Empty, Icon, Loading, PageHeader } from '../../shared/ui';

const MONEY_COLS = new Set(['amount', 'collected', 'balance', 'overdue', 'deposit_refund', 'simulated_amount']);

@Component({
  imports: [FormsModule, Empty, Icon, Loading, PageHeader],
  template: `
    <app-page-header title="Reports" subtitle="Calculated from stored records, limited to the properties you can access." />
    <div class="report-layout">
      <nav class="card report-nav">
        @for (r of reports(); track r.key) {
          <button [class.active]="current() === r.key" (click)="select(r.key)">{{ r.title }}</button>
        }
      </nav>
      <div class="card">
        <div class="toolbar">
          <select [(ngModel)]="property" (change)="load()"><option value="">All my properties</option>
            @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
          <label class="row small" style="gap:6px">From <input type="date" [(ngModel)]="start" (change)="load()"></label>
          <label class="row small" style="gap:6px">To <input type="date" [(ngModel)]="end" (change)="load()"></label>
          <span style="flex:1"></span>
          <button class="btn btn-sm" (click)="exportCsv()" [disabled]="!data()?.rows?.length"><app-icon name="download" [size]="15" /> Export CSV</button>
        </div>
        @if (loading()) { <app-loading /> }
        @else if (data(); as d) {
          <div class="card-body"><h2 style="margin:0">{{ d.title }}</h2>
            @if (current() === 'occupancy' || current() === 'arrears') { <p class="muted small">Snapshot as of {{ current() === 'arrears' ? d.end : 'today' }}.</p> }
            @else { <p class="muted small">{{ d.start }} to {{ d.end }}</p> }</div>
          @if (!d.rows.length) { <app-empty icon="chart" title="No data for this period" /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr>@for (c of d.columns; track c) { <th [class.num]="isNum(c)">{{ head(c) }}</th> }</tr></thead>
              <tbody>@for (row of d.rows; track $index) {
                <tr>@for (c of d.columns; track c) { <td [attr.data-label]="head(c)" [class.num]="isNum(c)">{{ cell(c, row[c]) }}</td> }</tr>
              }</tbody>
              @if (hasTotals()) {
                <tfoot><tr>@for (c of d.columns; track c; let i = $index) { <td class="strong" [class.num]="isNum(c)">{{ i === 0 ? 'Total' : (d.totals[c] !== undefined ? cell(c, d.totals[c]) : '') }}</td> }</tr></tfoot>
              }
            </table></div>
          }
        }
      </div>
    </div>`,
  styles: `
    .report-layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; align-items: start; }
    .report-nav { padding: 8px; }
    .report-nav button { display: block; width: 100%; text-align: left; padding: 9px 12px; border: 0; background: none; border-radius: 7px; font: inherit; cursor: pointer; color: var(--ink-2); }
    .report-nav button:hover { background: var(--surface-2); }
    .report-nav button.active { background: var(--brand-50); color: var(--brand); font-weight: 600; }
    tfoot td { border-top: 2px solid var(--line); background: var(--surface-2); }
    @media (max-width: 900px) { .report-layout { grid-template-columns: 1fr; } .report-nav { display: flex; overflow-x: auto; } .report-nav button { white-space: nowrap; width: auto; } }
  `,
})
export class ReportsPage {
  private api = inject(Api);
  private ui = inject(Ui);
  auth = inject(Auth);
  reports = signal<any[]>([]);
  current = signal('');
  data = signal<any>(null);
  loading = signal(false);
  property = '';
  private route = inject(ActivatedRoute);
  start = monthStart().slice(0, 4) + '-01-01';
  end = today();

  async ngOnInit() {
    const list = await this.api.getP('reports/');
    this.reports.set(list);
    const wanted = this.route.snapshot.queryParams['r'];
    this.select(list.find((r: any) => r.key === wanted)?.key ?? list[0]?.key);
  }


  select(key: string) {
    if (!key) return;
    this.current.set(key);
    this.load();
  }

  params() {
    return { property: this.property, start: this.start, end: this.end };
  }

  async load() {
    this.loading.set(true);
    try {
      this.data.set(await this.api.getP(`reports/${this.current()}/`, this.params()));
    } catch (e) {
      this.ui.error(parseError(e).message);
    } finally {
      this.loading.set(false);
    }
  }

  exportCsv() {
    this.api.download(`reports/${this.current()}/`, { ...this.params(), export: 'csv' }, `${this.current()}.csv`).catch((e) => this.ui.error(parseError(e).message));
  }

  head(c: string) {
    return c.replace(/_/g, ' ').replace(/^./, (x) => x.toUpperCase());
  }
  isNum(c: string) {
    return MONEY_COLS.has(c) || /count|units|payments|days|rate|recipients|opened|acknowledged|occupied|available|reserved|maintenance|unavailable|applications|approved|rejected|reservations|converted|expired|viewing/.test(c);
  }
  cell(c: string, v: any) {
    if (v === null || v === undefined || v === '') return '—';
    if (MONEY_COLS.has(c)) return formatKes(v);
    if (/rate$/.test(c)) return `${v}%`;
    return String(v);
  }
  hasTotals() {
    return Object.keys(this.data()?.totals ?? {}).length > 0;
  }
}
