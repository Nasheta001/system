import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { KesPipe } from '../../core/format';
import { Badge, Empty, Icon, Loading } from '../../shared/ui';
import { PayRent } from './pay-rent';

@Component({
  imports: [RouterLink, DatePipe, KesPipe, Badge, Empty, Icon, Loading, PayRent],
  template: `
    @if (!d()) { <app-loading /> } @else {
      <h1 class="hello">Hello, {{ d().tenant.first_name }}</h1>
      @if (!d().tenancy) {
        <div class="card"><app-empty icon="home" title="No tenancy linked yet" text="Your landlord has not assigned a unit to your account yet. Please contact the management office." /></div>
      } @else {
        <div class="hero-card" [class.overdue]="d().account?.status === 'overdue'">
          <div>
            <div class="small op">{{ d().tenancy.property }} · Unit {{ d().tenancy.unit }}</div>
            @if (+d().account.balance > 0) {
              <div class="big">{{ d().account.balance | kes }}</div>
              <div class="op">@if (d().account.status === 'overdue') { Overdue since {{ d().account.overdue_since | date: 'd MMM' }} } @else { Outstanding balance @if (d().account.next_due_date) { · next due {{ d().account.next_due_date | date: 'd MMM' }} } }</div>
            } @else {
              <div class="big">{{ +d().account.balance < 0 ? 'In credit' : 'All paid up' }}</div>
              <div class="op">@if (+d().account.balance < 0) { {{ -d().account.balance | kes }} credit · } Next rent {{ d().account.next_due_amount | kes }} due {{ d().account.next_due_date | date: 'd MMM' }}</div>
            }
            @if (+d().account.pending_payments > 0) { <div class="small op">{{ d().account.pending_payments | kes }} awaiting verification</div> }
          </div>
          @if (d().tenancy.status !== 'ended') {
            <button class="btn btn-lg pay-btn" (click)="payOpen.set(true)"><app-icon name="wallet" /> Pay rent</button>
          }
        </div>

        @if (d().pending_documents?.length) {
          <div class="card mt"><div class="card-head"><h2>Action needed</h2></div>
            <ul class="list">@for (p of d().pending_documents; track $index) {
              <li class="row-between"><span><app-icon name="file" [size]="16" /> {{ p.title }}</span>
                <a class="btn btn-sm btn-primary" routerLink="/tenant/documents">{{ p.action === 'sign' ? (p.status === 'rejected' ? 'Re-upload signed copy' : 'Sign') : 'Acknowledge' }}</a></li>
            }</ul></div>
        }

        <div class="tgrid mt">
          <div class="card">
            <div class="card-head"><h2>My home</h2></div>
            <div class="card-body"><dl class="kv">
              <dt>Property</dt><dd>{{ d().tenancy.property }}</dd>
              <dt>Unit</dt><dd>{{ d().tenancy.unit }} · {{ d().tenancy.unit_type }}</dd>
              <dt>Monthly rent</dt><dd>{{ d().tenancy.monthly_rent | kes }} @if (+d().tenancy.service_charge) { + {{ d().tenancy.service_charge | kes }} service }</dd>
              <dt>Rent due</dt><dd>Day {{ d().tenancy.rent_due_day }} of each month</dd>
              <dt>Tenancy</dt><dd>Since {{ d().tenancy.start_date | date: 'mediumDate' }} @if (d().tenancy.planned_move_out) { · moving out {{ d().tenancy.planned_move_out | date: 'mediumDate' }} }</dd>
            </dl></div>
          </div>
          <div class="card">
            <div class="card-head"><h2>Recent payments</h2><a routerLink="/tenant/payments" class="small">All</a></div>
            @if (!d().recent_payments.length) { <p class="card-body muted">No payments yet.</p> }
            <ul class="list">@for (p of d().recent_payments; track p.id) {
              <li class="row-between"><span>{{ p.paid_on | date: 'd MMM yyyy' }} @if (p.is_simulated) { <span class="sim-flag">SIMULATED</span> }<span class="sub muted small" style="display:block">{{ p.receipt_number }}</span></span><b>{{ p.amount | kes }}</b></li>
            }</ul>
          </div>
          <div class="card">
            <div class="card-head"><h2>Notices</h2><a routerLink="/tenant/announcements" class="small">All</a></div>
            @if (!d().announcements.length) { <p class="card-body muted">No notices.</p> }
            <ul class="list">@for (a of d().announcements; track a.id) {
              <li><a routerLink="/tenant/announcements" [class.strong]="!a.opened">{{ a.title }}</a>
                <div class="row small" style="gap:6px">@if (a.priority === 'high' || a.priority === 'urgent') { <app-badge [value]="a.priority" /> }
                  @if (a.requires_acknowledgement && !a.acknowledged) { <app-badge value="pending" text="Please acknowledge" /> }
                  <span class="muted">{{ a.published_at | date: 'd MMM' }}</span></div></li>
            }</ul>
          </div>
          <div class="card">
            <div class="card-head"><h2>Maintenance</h2><a routerLink="/tenant/maintenance" class="small">Report an issue</a></div>
            @if (!d().maintenance.length) { <p class="card-body muted">No requests.</p> }
            <ul class="list">@for (m of d().maintenance; track m.id) {
              <li class="row-between"><a [routerLink]="['/tenant/maintenance', m.id]">{{ m.title }}</a><app-badge [value]="m.status" /></li>
            }</ul>
          </div>
          @if (d().manager; as m) {
            <div class="card card-pad">
              <h3>Your property manager</h3>
              <p class="strong" style="margin-bottom:6px">{{ m.name }}</p>
              <div class="row">
                @if (m.phone) { <a class="btn btn-sm" [href]="'tel:' + m.phone"><app-icon name="phone" [size]="14" /> Call</a> }
                @if (m.whatsapp) { <a class="btn btn-sm" [href]="'https://wa.me/' + m.whatsapp.replace('+', '')" target="_blank" rel="noopener"><app-icon name="chat" [size]="14" /> WhatsApp</a> }
                @if (m.email) { <a class="btn btn-sm" [href]="'mailto:' + m.email"><app-icon name="mail" [size]="14" /> Email</a> }
              </div>
            </div>
          }
        </div>
        <app-pay-rent [(open)]="payOpen" [balance]="d().account.balance" [suggested]="+d().account.balance > 0 ? d().account.balance : d().account.next_due_amount"
          [defaultPhone]="d().tenant.phone" [mode]="mode()" (paid)="load()" />
      }
    }`,
  styles: `
    .hello { font-family: var(--font-display); font-weight: 600; font-size: 1.6rem; }
    .hero-card { background: var(--brand); color: #fff; border-radius: 14px; padding: 22px; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
    .hero-card.overdue { background: #7c2d12; }
    .hero-card .big { font-size: 2rem; font-weight: 700; letter-spacing: -0.02em; margin: 4px 0; }
    .op { opacity: .85; }
    .pay-btn { background: #fff; color: var(--brand); border-color: #fff; font-weight: 700; }
    .overdue .pay-btn { color: #7c2d12; }
    .tgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    @media (max-width: 720px) { .tgrid { grid-template-columns: 1fr; } .pay-btn { width: 100%; } .hero-card .big { font-size: 1.6rem; } }
  `,
})
export class TenantDashboardPage {
  private api = inject(Api);
  d = signal<any>(null);
  mode = signal('simulated');
  payOpen = signal(false);

  constructor() {
    this.load();
    this.api.get('payment-config/').subscribe((r) => this.mode.set(r.mpesa_mode));
  }

  async load() {
    this.d.set(await this.api.getP('portal/dashboard/'));
  }
}
