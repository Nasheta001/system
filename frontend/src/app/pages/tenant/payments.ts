import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, parseError } from '../../core/api.service';
import { KesPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { Badge, Empty, Icon, Loading } from '../../shared/ui';
import { PayRent } from './pay-rent';

@Component({
  imports: [FormsModule, DatePipe, KesPipe, Badge, Empty, Icon, Loading, PayRent],
  template: `
    <div class="row-between mb"><h1 style="margin:0">Rent & payments</h1>
      @if (data()?.tenancies?.length > 1) {
        <select [ngModel]="tenancyId()" (ngModelChange)="load($event)" style="width:auto">@for (t of data().tenancies; track t.id) { <option [ngValue]="t.id">{{ t.label }} ({{ t.status }})</option> }</select>
      }
    </div>
    @if (!data()) { <app-loading /> }
    @else if (!data().tenancy) { <div class="card"><app-empty icon="wallet" title="No rent account yet" /></div> }
    @else {
      <div class="grid-4">
        <div class="stat stat-static"><div class="stat-label">Balance</div><div class="stat-value" [class.text-red]="+a().balance > 0">{{ a().balance | kes }}</div><div class="stat-hint">{{ +a().balance < 0 ? 'Credit in your favour' : a().status === 'overdue' ? 'Overdue' : '' }}</div></div>
        <div class="stat stat-static"><div class="stat-label">Next due</div><div class="stat-value">{{ a().next_due_date ? (a().next_due_date | date: 'd MMM') : '—' }}</div><div class="stat-hint">{{ a().next_due_amount | kes }}</div></div>
        <div class="stat stat-static"><div class="stat-label">Paid to date</div><div class="stat-value">{{ a().total_paid | kes }}</div></div>
        <div class="stat stat-static"><div class="stat-label">Awaiting verification</div><div class="stat-value">{{ a().pending_payments | kes }}</div></div>
      </div>
      <div class="row mt">
        @if (data().tenancy.status !== 'ended') { <button class="btn btn-primary btn-lg" (click)="payOpen.set(true)"><app-icon name="wallet" /> Pay rent</button> }
        <button class="btn btn-lg" (click)="statement()"><app-icon name="download" /> Download statement</button>
      </div>

      <div class="card mt">
        <div class="card-head"><h2>Payments</h2></div>
        @if (!data().payments.length) { <p class="card-body muted">No payments yet.</p> }
        <div class="table-wrap"><table class="table responsive">
          <tbody>@for (p of data().payments; track p.id) {
            <tr><td data-label="Date">{{ p.paid_on | date: 'd MMM yyyy' }}</td>
              <td data-label="Method">{{ p.method }} @if (p.is_simulated) { <span class="sim-flag">SIMULATED</span> }<span class="sub mono">{{ p.reference }}</span></td>
              <td data-label="Amount" class="num strong">{{ p.amount | kes }}</td>
              <td data-label="Status"><app-badge [value]="p.status" /></td>
              <td class="actions">@if (p.status === 'verified') { <button class="btn btn-sm" (click)="receipt(p)"><app-icon name="receipt" [size]="14" /> Receipt</button> }</td></tr>
          }</tbody></table></div>
      </div>

      <div class="card mt">
        <div class="card-head"><h2>Statement</h2><span class="muted small">Charges and verified payments</span></div>
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Date</th><th>Description</th><th class="num">Charge</th><th class="num">Paid</th><th class="num">Balance</th></tr></thead>
          <tbody>@for (r of data().ledger; track r.type + r.id) {
            <tr><td data-label="Date" class="nowrap">{{ r.date | date: 'd MMM yyyy' }}</td><td data-label="Description">{{ r.description }}</td>
              <td data-label="Charge" class="num">{{ r.debit ? (r.debit | kes) : '' }}</td><td data-label="Paid" class="num text-green">{{ r.credit ? (r.credit | kes) : '' }}</td>
              <td data-label="Balance" class="num strong">{{ r.balance | kes }}</td></tr>
          }</tbody></table></div>
      </div>
      <app-pay-rent [(open)]="payOpen" [balance]="a().balance" [suggested]="data().suggested_amount" [defaultPhone]="data().phone" [mode]="mode()" (paid)="load(tenancyId())" />
    }`,
})
export class TenantPaymentsPage {
  private api = inject(Api);
  private ui = inject(Ui);
  data = signal<any>(null);
  tenancyId = signal<number | null>(null);
  mode = signal('simulated');
  payOpen = signal(false);
  a = () => this.data()?.account;

  constructor() {
    this.load(null);
    this.api.get('payment-config/').subscribe((r) => this.mode.set(r.mpesa_mode));
  }

  async load(id: number | null) {
    const r = await this.api.getP('portal/account/', { tenancy: id });
    this.data.set(r);
    this.tenancyId.set(r.tenancy?.id ?? null);
  }

  receipt(p: any) {
    this.api.download(`portal/payments/${p.id}/receipt/`, {}, `${p.receipt_number}.pdf`).catch((e) => this.ui.error(parseError(e).message));
  }
  statement() {
    this.api.download(`portal/tenancies/${this.tenancyId()}/statement/`, {}, 'statement.pdf').catch((e) => this.ui.error(parseError(e).message));
  }
}
