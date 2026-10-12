import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe, formatKes, monthStart, today } from '../../core/format';
import { Badge, Empty, Icon, Loading, PageHeader, Stat } from '../../shared/ui';

@Component({
  imports: [FormsModule, RouterLink, DatePipe, KesPipe, Badge, Empty, Icon, Loading, PageHeader, Stat],
  template: `
    <app-page-header [title]="'Good ' + greeting() + ', ' + (auth.me()?.first_name || '')" subtitle="Here is what is happening across your properties.">
      <select [(ngModel)]="property" (change)="load()" aria-label="Property filter" style="width:auto">
        <option value="">All my properties</option>
        @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }
      </select>
      <input type="date" [(ngModel)]="start" (change)="load()" aria-label="From" style="width:auto">
      <input type="date" [(ngModel)]="end" (change)="load()" aria-label="To" style="width:auto">
    </app-page-header>

    @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
    @if (!d()) { <app-loading /> }
    @else if (d().properties === 0) {
      <div class="card">
        <app-empty icon="building" title="Welcome! Let's add your first property"
          text="Add a property, then its buildings and units. You can then register tenants, record rent and publish vacancies.">
          @if (auth.can('create_properties')) { <a class="btn btn-primary" routerLink="/management/properties/new"><app-icon name="plus" /> Add your first property</a> }
          @else { <p class="muted small">Ask an administrator to assign you to a property.</p> }
        </app-empty>
      </div>
    } @else {
      <div class="grid-4">
        <app-stat label="Active properties" [value]="d().properties" icon="building" link="/management/properties" />
        <app-stat label="Total units" [value]="d().units.total" [hint]="d().units.available + ' vacant · ' + d().units.reserved + ' reserved'" icon="layers" link="/management/properties" />
        <app-stat label="Occupancy rate" [value]="d().units.occupancy_rate + '%'" [hint]="d().units.occupied + ' occupied units'" icon="users" tone="blue" />
        <app-stat label="Open maintenance" [value]="d().maintenance.open" [hint]="d().maintenance.emergency + ' high / emergency'" icon="wrench" [tone]="d().maintenance.emergency ? 'red' : 'amber'" link="/management/maintenance" />
        @if (f()) {
          <app-stat label="Rent collected" [value]="kes(f().collected)" [hint]="(start | date: 'd MMM') + ' – ' + (end | date: 'd MMM yyyy')" icon="wallet" link="/management/payments" />
          <app-stat label="Outstanding rent" [value]="kes(f().outstanding)" [hint]="'Expected monthly ' + kes(f().expected_monthly)" icon="receipt" tone="clay" link="/management/reports" />
          <app-stat label="Overdue" [value]="kes(f().overdue_total)" [hint]="f().overdue_count + ' tenant(s) past grace period'" icon="alert" [tone]="f().overdue_count ? 'red' : 'green'" link="/management/tenants" />
        }
        <app-stat label="Vacant units" [value]="d().units.available" [hint]="d().units.maintenance + ' under maintenance'" icon="door" tone="amber" link="/management/leasing" />
      </div>

      @if (actionList().length) {
        <div class="card mt">
          <div class="card-head"><h2>Needs your attention</h2></div>
          <div class="actions-grid">
            @for (a of actionList(); track a.label) {
              <a class="action-item" [routerLink]="a.link" [queryParams]="a.query"><span class="action-count">{{ a.count }}</span><span>{{ a.label }}</span><app-icon name="right" [size]="16" /></a>
            }
          </div>
        </div>
      }

      <div class="split mt">
        <div class="stack">
          @if (f()) {
            <div class="card">
              <div class="card-head"><h2>Collections – last 6 months</h2><span class="muted small">Verified payments</span></div>
              <div class="card-body">
                @if (!f().monthly.length) { <p class="muted">No verified payments yet.</p> }
                @else {
                  <div class="bars">
                    @for (m of f().monthly; track m.month) {
                      <div class="bar"><b>{{ short(m.amount) }}</b><span class="fill" [style.height.%]="pct(m.amount)"></span><small>{{ m.month + '-01' | date: 'MMM' }}</small></div>
                    }
                  </div>
                }
              </div>
            </div>
            <div class="card">
              <div class="card-head"><h2>Overdue rent</h2><a routerLink="/management/reports" [queryParams]="{ r: 'arrears' }" class="small">Arrears report</a></div>
              @if (!f().overdue.length) { <p class="card-body muted">No overdue balances. 🎉</p> }
              @else {
                <div class="table-wrap"><table class="table responsive">
                  <thead><tr><th>Tenant</th><th>Unit</th><th class="num">Overdue</th><th class="num">Days</th></tr></thead>
                  <tbody>@for (r of f().overdue; track r.tenancy_id) {
                    <tr class="clickable" [routerLink]="['/management/tenants', r.tenant_id]">
                      <td data-label="Tenant">{{ r.tenant }}</td><td data-label="Unit">{{ r.unit }}<span class="sub">{{ r.property }}</span></td>
                      <td data-label="Overdue" class="num text-red strong">{{ r.overdue_amount | kes }}</td><td data-label="Days" class="num">{{ r.days_overdue }}</td></tr>
                  }</tbody></table></div>
              }
            </div>
            <div class="card">
              <div class="card-head"><h2>Due in the next 7 days</h2></div>
              @if (!f().upcoming.length) { <p class="card-body muted">Nothing due this week.</p> }
              @else {
                <ul class="list">@for (r of f().upcoming; track r.tenancy_id) {
                  <li class="row-between"><span><a [routerLink]="['/management/tenants', r.tenant_id]">{{ r.tenant }}</a> <span class="muted small">· {{ r.unit }}, {{ r.property }}</span></span>
                    <span class="nowrap"><span class="muted small">{{ r.due_date | date: 'd MMM' }}</span> <b>{{ r.amount | kes }}</b></span></li>
                }</ul>
              }
            </div>
          }
        </div>
        <div class="stack">
          @if (f()) {
            <div class="card">
              <div class="card-head"><h2>Recent payments</h2><a routerLink="/management/payments" class="small">All</a></div>
              @if (!f().recent_payments.length) { <p class="card-body muted">No payments yet.</p> }
              <ul class="list">@for (p of f().recent_payments; track p.id) {
                <li class="row-between pay-row"><span>{{ p.tenant }}<span class="sub muted small" style="display:block">{{ p.unit }} · {{ p.method }} @if (p.is_simulated) { <span class="sim-flag">SIMULATED</span> }</span></span>
                  <span class="right"><b>{{ p.amount | kes }}</b><span class="muted small" style="display:block">{{ p.paid_on | date: 'd MMM' }}</span></span></li>
              }</ul>
            </div>
          }
          <div class="card">
            <div class="card-head"><h2>Open maintenance</h2><a routerLink="/management/maintenance" class="small">All</a></div>
            @if (!d().maintenance.recent.length) { <p class="card-body muted">No open requests.</p> }
            <ul class="list">@for (m of d().maintenance.recent; track m.id) {
              <li><a [routerLink]="['/management/maintenance', m.id]" class="strong">{{ m.title }}</a>
                <div class="row small" style="gap:6px;margin-top:3px"><app-badge [value]="m.urgency" /><app-badge [value]="m.status" /><span class="muted">{{ m.property__name }} {{ m.unit__unit_number }}</span></div></li>
            }</ul>
          </div>
          <div class="card">
            <div class="card-head"><h2>Recent announcements</h2><a routerLink="/management/announcements" class="small">All</a></div>
            @if (!d().announcements.length) { <p class="card-body muted">No announcements published yet.</p> }
            <ul class="list">@for (a of d().announcements; track a.id) {
              <li class="row-between"><a [routerLink]="['/management/announcements', a.id]">{{ a.title }}</a><span class="muted small">{{ a.published_at | date: 'd MMM' }}</span></li>
            }</ul>
          </div>
        </div>
      </div>
    }`,
  styles: `
    .actions-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
    .action-item { display: flex; align-items: center; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--line); border-right: 1px solid var(--line); color: var(--ink); text-decoration: none; }
    .action-item:hover { background: var(--surface-2); }
    .action-item span:nth-child(2) { flex: 1; }
    .action-count { min-width: 30px; height: 30px; border-radius: 8px; background: var(--amber-bg); color: var(--amber); font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
  `,
})
export class DashboardPage {
  private api = inject(Api);
  auth = inject(Auth);
  d = signal<any>(null);
  error = signal('');
  property = '';
  start = monthStart();
  end = today();
  f = computed(() => this.d()?.financials);
  actionList = computed(() => {
    const a = this.d()?.actions ?? {};
    const list = [
      { key: 'payments_to_verify', label: 'Payments awaiting verification', link: '/management/payments', query: { status: 'pending' } },
      { key: 'pending_applications', label: 'Applications to review', link: '/management/leasing', query: { tab: 'applications' } },
      { key: 'new_viewing_requests', label: 'New viewing requests', link: '/management/leasing', query: { tab: 'viewings' } },
      { key: 'reservations_expiring', label: 'Reservations expiring within 2 days', link: '/management/leasing', query: { tab: 'reservations' } },
      { key: 'open_follow_ups', label: 'Rent follow-ups', link: '/management/payments', query: { tab: 'followups' } },
      { key: 'signatures_to_review', label: 'Signed documents to verify', link: '/management/documents', query: { tab: 'signatures' } },
    ];
    return list.filter((x) => a[x.key] > 0).map((x) => ({ ...x, count: a[x.key] }));
  });
  private maxMonth = computed(() => Math.max(1, ...(this.f()?.monthly ?? []).map((m: any) => +m.amount)));

  constructor() {
    this.load();
  }

  greeting() {
    const h = new Date().getHours();
    return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
  }

  kes(v: any) {
    return formatKes(v);
  }
  short(v: any) {
    const n = +v;
    return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'K' : String(n);
  }
  pct(v: any) {
    return Math.max(2, (100 * +v) / this.maxMonth());
  }

  async load() {
    this.error.set('');
    try {
      this.d.set(await this.api.getP('dashboard/', { property: this.property, start: this.start, end: this.end }));
    } catch (e) {
      this.error.set(parseError(e).message);
    }
  }
}
