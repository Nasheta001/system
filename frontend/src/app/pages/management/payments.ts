import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe, today } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, RouterLink, DatePipe, KesPipe, Badge, Empty, Icon, Loading, Modal, PageHeader, Pager],
  template: `
    <app-page-header title="Rent & payments" subtitle="Verified payments reduce balances. Pending entries do not until verified.">
      <span class="badge" [class]="mpesaMode() === 'production' ? 'badge badge-green' : 'badge badge-amber'">M-Pesa: {{ mpesaLabel() }}</span>
      @if (auth.can('manage_payments')) { <button class="btn btn-primary" (click)="openRecord()"><app-icon name="plus" /> Record payment</button> }
    </app-page-header>
    <div class="tabs">
      <button class="tab" [class.active]="tab() === 'payments'" (click)="setTab('payments')">Payments</button>
      <button class="tab" [class.active]="tab() === 'mpesa'" (click)="setTab('mpesa')">M-Pesa requests</button>
      <button class="tab" [class.active]="tab() === 'followups'" (click)="setTab('followups')">Follow-ups</button>
    </div>

    @switch (tab()) {
      @case ('payments') {
        <div class="card">
          <div class="toolbar">
            <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Tenant, receipt, reference…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
            <select [(ngModel)]="list.filters['property']" (change)="list.load(true)"><option value="">All properties</option>
              @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
            <select [(ngModel)]="list.filters['status']" (change)="list.load(true)"><option value="">Any status</option><option value="verified">Verified</option><option value="pending">Pending verification</option><option value="rejected">Rejected</option></select>
            <select [(ngModel)]="list.filters['method']" (change)="list.load(true)"><option value="">Any method</option><option value="mpesa">M-Pesa (STK)</option><option value="mpesa_simulated">M-Pesa (simulated)</option><option value="mpesa_manual">M-Pesa (manual)</option><option value="bank">Bank</option><option value="cash">Cash</option><option value="cheque">Cheque</option></select>
            <input type="date" [(ngModel)]="list.filters['paid_on__gte']" (change)="list.load(true)" aria-label="From">
            <input type="date" [(ngModel)]="list.filters['paid_on__lte']" (change)="list.load(true)" aria-label="To">
          </div>
          @if (list.loading() && !list.loaded()) { <app-loading /> }
          @else if (!list.items().length) { <app-empty icon="wallet" title="No payments found" text="Payments appear here when tenants pay by M-Pesa or staff record them." /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Date</th><th>Tenant</th><th>Method</th><th>Reference</th><th class="num">Amount</th><th>Status</th><th></th></tr></thead>
              <tbody>@for (p of list.items(); track p.id) {
                <tr>
                  <td data-label="Date" class="nowrap">{{ p.paid_on | date: 'd MMM yyyy' }}</td>
                  <td data-label="Tenant"><a [routerLink]="['/management/tenants', p.tenant_id]">{{ p.tenant_name }}</a><span class="sub">{{ p.unit_label }} · {{ p.property_name }}</span></td>
                  <td data-label="Method">{{ p.method_label }} @if (p.is_simulated) { <span class="sim-flag">SIMULATED</span> }<span class="sub">{{ p.source === 'stk' ? 'Tenant portal' : 'Recorded by ' + (p.recorded_by_name || '—') }}</span></td>
                  <td data-label="Reference" class="mono">{{ p.reference || '—' }}@if (p.receipt_number) { <span class="sub">{{ p.receipt_number }}</span> }</td>
                  <td data-label="Amount" class="num strong">{{ p.amount | kes }}</td>
                  <td data-label="Status"><app-badge [value]="p.status" />@if (p.rejection_reason) { <span class="sub">{{ p.rejection_reason }}</span> }@if (p.notes) { <span class="sub">{{ p.notes }}</span> }</td>
                  <td class="actions">
                    @if (p.status === 'verified') { <button class="btn btn-sm btn-ghost" (click)="api.download('payments/' + p.id + '/receipt/', {}, 'receipt.pdf')"><app-icon name="download" [size]="14" /> Receipt</button> }
                    @if (p.status === 'pending' && auth.can('verify_payments')) {
                      <button class="btn btn-sm" (click)="verify(p)">Verify</button>
                      <button class="btn btn-sm btn-ghost" (click)="reject(p)">Reject</button>
                    }
                  </td>
                </tr>
              }</tbody></table></div>
            <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
          }
        </div>
      }
      @case ('mpesa') {
        <div class="card">
          <div class="toolbar"><select [(ngModel)]="tx.filters['status']" (change)="tx.load(true)"><option value="">Any status</option><option value="pending">Awaiting customer</option><option value="success">Successful</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option><option value="timeout">Timed out</option></select>
            <span class="muted small">Every STK Push request. Only successful, verified callbacks create payments.</span></div>
          @if (!tx.items().length) { <app-empty icon="phone" title="No M-Pesa requests yet" /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Initiated</th><th>Tenant</th><th>Phone</th><th class="num">Amount</th><th>Status</th><th>Receipt</th></tr></thead>
              <tbody>@for (t of tx.items(); track t.id) {
                <tr><td data-label="Initiated">{{ t.created_at | date: 'd MMM, HH:mm' }}</td><td data-label="Tenant">{{ t.tenant_name }}<span class="sub">{{ t.unit_label }}</span></td>
                  <td data-label="Phone" class="mono">{{ t.phone }}</td><td data-label="Amount" class="num">{{ t.amount | kes }}</td>
                  <td data-label="Status"><app-badge [value]="t.status" /> @if (t.is_simulated) { <span class="sim-flag">SIMULATED</span> }<span class="sub">{{ t.result_desc }}</span></td>
                  <td data-label="Receipt" class="mono">{{ t.mpesa_receipt || '—' }}</td></tr>
              }</tbody></table></div>
            <app-pager [count]="tx.count()" [page]="tx.page()" (pageChange)="tx.go($event)" />
          }
        </div>
      }
      @case ('followups') {
        <div class="card">
          <div class="toolbar"><select [(ngModel)]="fu.filters['status']" (change)="fu.load(true)"><option value="open">Open</option><option value="done">Done</option><option value="dismissed">Dismissed</option></select>
            <span class="muted small">Created automatically by escalating rent reminders. No penalties or legal steps are taken automatically.</span></div>
          @if (!fu.items().length) { <app-empty icon="check" title="No follow-ups" /> }
          <ul class="list">@for (f of fu.items(); track f.id) {
            <li class="row-between"><div><b>{{ f.title }}</b><div class="muted small">{{ f.details }} · {{ f.created_at | date: 'd MMM' }}</div></div>
              <div class="row">@if (f.tenant_id) { <a class="btn btn-sm" [routerLink]="['/management/tenants', f.tenant_id]">Open tenant</a> }
                @if (f.status === 'open' && auth.can('manage_payments')) { <button class="btn btn-sm" (click)="closeFollowUp(f, 'done')">Mark done</button><button class="btn btn-sm btn-ghost" (click)="closeFollowUp(f, 'dismissed')">Dismiss</button> }</div></li>
          }</ul>
        </div>
      }
    }

    <app-modal [(open)]="recordOpen" title="Record a payment">
      <form (ngSubmit)="saveRecord()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <label class="field"><span>Tenancy *</span>
          <input placeholder="Type to filter tenants or units" [(ngModel)]="tenancyFilter" name="tf">
          <select name="t" [(ngModel)]="rec.tenancy" size="5" style="height:auto">
            @for (t of filteredTenancies(); track t.id) { <option [ngValue]="t.id">{{ t.tenant_name }} – {{ t.unit_label }}, {{ t.property_name }}</option> }
          </select></label>
        <div class="form-grid">
          <label class="field"><span>Amount (KES) *</span><input type="number" min="1" name="a" [(ngModel)]="rec.amount"></label>
          <label class="field"><span>Date received *</span><input type="date" name="d" [(ngModel)]="rec.paid_on"></label>
          <label class="field"><span>Method</span><select name="m" [(ngModel)]="rec.method"><option value="cash">Cash</option><option value="bank">Bank transfer / deposit</option><option value="mpesa_manual">M-Pesa paybill (manual)</option><option value="cheque">Cheque</option><option value="other">Other</option></select></label>
          <label class="field"><span>Reference</span><input name="r" [(ngModel)]="rec.reference"></label>
          <label class="field span-2"><span>Notes</span><input name="n" [(ngModel)]="rec.notes"></label>
        </div>
        @if (auth.can('verify_payments')) { <label class="check"><input type="checkbox" name="v" [(ngModel)]="rec.mark_verified"> Money confirmed received – verify now and issue receipt</label> }
        @else { <div class="alert alert-info small">Saved as pending until an administrator verifies it.</div> }
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !rec.tenancy || !rec.amount">Save</button></div>
      </form>
    </app-modal>`,
})
export class PaymentsPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  tab = signal('payments');
  list = new ListState(this.api, 'payments/', { search: '', status: '', method: '', property: '', paid_on__gte: '', paid_on__lte: '' });
  tx = new ListState(this.api, 'mpesa-transactions/', { status: '' });
  fu = new ListState(this.api, 'follow-ups/', { status: 'open' });
  mpesaMode = signal('');
  mpesaLabel = signal('');
  recordOpen = signal(false);
  busy = signal(false);
  formErr = signal('');
  tenancies = signal<any[]>([]);
  tenancyFilter = '';
  rec: any = {};

  constructor() {
    const q = inject(ActivatedRoute).snapshot.queryParams;
    if (q['status']) this.list.filters['status'] = q['status'];
    this.setTab(q['tab'] || 'payments');
    this.api.get('payment-config/').subscribe((r) => { this.mpesaMode.set(r.mpesa_mode); this.mpesaLabel.set(r.label); });
  }

  setTab(t: string) {
    this.tab.set(t);
    ({ payments: this.list, mpesa: this.tx, followups: this.fu } as any)[t].load();
  }

  filteredTenancies() {
    const f = this.tenancyFilter.toLowerCase();
    return this.tenancies().filter((t) => !f || `${t.tenant_name} ${t.unit_label} ${t.property_name}`.toLowerCase().includes(f));
  }

  async openRecord() {
    this.formErr.set('');
    this.rec = { tenancy: null, amount: null, paid_on: today(), method: 'bank', reference: '', notes: '', mark_verified: this.auth.can('verify_payments') };
    this.recordOpen.set(true);
    this.tenancies.set(await this.api.all('tenancies/', { status: 'active' }).then(async (a) => [...a, ...(await this.api.all('tenancies/', { status: 'notice' }))]));
  }

  async saveRecord() {
    this.busy.set(true);
    this.formErr.set('');
    try {
      await this.api.postP('payments/', this.rec);
      this.recordOpen.set(false);
      this.ui.toast('Payment recorded.');
      this.list.load();
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async verify(p: any) {
    if (!(await this.ui.confirm({ title: 'Verify payment?', message: `Confirm KES ${p.amount} from ${p.tenant_name} (${p.reference || p.method_label}) was received. A receipt will be issued and the tenant notified.`, confirmText: 'Verify' }))) return;
    try {
      await this.api.postP(`payments/${p.id}/verify/`);
      this.ui.toast('Payment verified.');
      this.list.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async reject(p: any) {
    const reason = await this.ui.confirm({ title: 'Reject payment?', message: 'The payment will not count towards the balance.', reasonLabel: 'Reason', danger: true, confirmText: 'Reject' });
    if (!reason) return;
    try {
      await this.api.postP(`payments/${p.id}/reject/`, { reason });
      this.ui.toast('Payment rejected.');
      this.list.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async closeFollowUp(f: any, status: string) {
    await this.api.patchP(`follow-ups/${f.id}/`, { status });
    this.fu.load();
  }
}
