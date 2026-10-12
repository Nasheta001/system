import { DatePipe } from '@angular/common';
import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe, LabelPipe, today } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { Badge, Empty, Icon, Loading, Modal, PageHeader, Stat } from '../../shared/ui';

@Component({
  imports: [FormsModule, DatePipe, KesPipe, LabelPipe, Badge, Empty, Icon, Loading, Modal, PageHeader, Stat],
  template: `
    @if (!t()) { <app-loading /> } @else {
      <app-page-header [title]="t().full_name" back="/management/tenants" backLabel="Tenants">
        @if (auth.can('manage_tenants')) {
          <button class="btn" (click)="openEdit()"><app-icon name="edit" /> Edit details</button>
          @if (t().has_portal_account !== undefined) {
            @if (t().has_portal_account) {
              @if (t().portal_active) { <button class="btn" (click)="portalAccount()"><app-icon name="key" /> Send password link</button> }
            } @else if (t().status === 'active') {
              <button class="btn" (click)="portalAccount()"><app-icon name="key" /> {{ t().portal_invitation ? 'Resend portal invitation' : 'Invite to tenant portal' }}</button>
            }
          }
        }
      </app-page-header>
      <div class="row mb"><app-badge [value]="t().status" />
        @if (t().has_portal_account) { <span class="muted small">Portal account {{ t().portal_active ? 'active' : 'disabled' }}</span>
          @if (auth.can('manage_tenants') && (t().portal_active || t().status === 'active')) { <button class="btn-link small" (click)="togglePortal()">{{ t().portal_active ? 'Disable access' : 'Enable access' }}</button> } }
        @if (!t().has_portal_account && t().portal_invitation; as inv) {
          <span class="muted small">Portal invitation {{ inv.status }} – sent to {{ inv.email }}, expires {{ inv.expires_at | date: 'd MMM, HH:mm' }}</span>
          @if (auth.can('manage_tenants')) { <button class="btn-link small" (click)="revokeInvite()">Revoke invitation</button> }
        }
        @if (t().status === 'former' && t().has_portal_account) { <span class="muted small">Portal closed at move-out. History is kept below.</span> }
      </div>
      @if (devLink()) {
        <div class="alert alert-warn small">
          <b>Development only:</b> email delivery is not configured. Share this single-use link with the tenant yourself
          (never shown when the server runs with DEBUG off): <span class="mono" style="word-break:break-all">{{ devLink() }}</span>
        </div>
      }

      <div class="split">
        <div class="stack">
          @if (tenancy(); as ten) {
            <div class="card">
              <div class="card-head">
                <h2>{{ ten.is_current ? 'Current tenancy' : 'Tenancy' }} · {{ ten.unit_label }}, {{ ten.property_name }}</h2>
                <app-badge [value]="ten.status" />
              </div>
              <div class="card-body">
                <dl class="kv">
                  <dt>Period</dt><dd>{{ ten.start_date | date: 'mediumDate' }} – {{ ten.actual_move_out ? (ten.actual_move_out | date: 'mediumDate') : (ten.expected_end_date ? (ten.expected_end_date | date: 'mediumDate') + ' (expected)' : 'open-ended') }}</dd>
                  <dt>Monthly rent</dt><dd>{{ ten.monthly_rent | kes }} @if (+ten.service_charge) { + {{ ten.service_charge | kes }} service }</dd>
                  <dt>Due day / grace</dt><dd>Day {{ ten.rent_due_day }} · {{ ten.grace_days }} days grace</dd>
                  <dt>Deposit</dt><dd>{{ ten.deposit_amount | kes }}</dd>
                  <dt>Reminders</dt><dd>{{ ten.reminders_enabled ? (ten.reminder_schedule_name || 'Default schedule') : 'Off' }}</dd>
                  @if (ten.notice_date) { <dt>Notice</dt><dd>Given {{ ten.notice_date | date: 'mediumDate' }} · move-out {{ ten.planned_move_out | date: 'mediumDate' }}</dd> }
                  @if (ten.status === 'ended') {
                    <dt>Move-out inspection</dt><dd>{{ ten.move_out_inspection_date ? (ten.move_out_inspection_date | date: 'mediumDate') : '—' }} {{ ten.move_out_inspection_notes }}</dd>
                    <dt>Deposit reconciliation</dt><dd>Deductions {{ ten.deposit_deductions | kes }} · applied to balance {{ ten.deposit_applied_to_balance | kes }} · refund {{ ten.deposit_refund_amount | kes }}</dd>
                  }
                </dl>
                @if (ten.is_current && auth.can('manage_tenants')) {
                  <div class="row mt">
                    @if (auth.can('manage_payments')) {
                      <button class="btn btn-primary btn-sm" (click)="openPayment()"><app-icon name="wallet" [size]="15" /> Record payment</button>
                      <button class="btn btn-sm" (click)="openCharge()"><app-icon name="receipt" [size]="15" /> Charge / credit</button>
                    }
                    <button class="btn btn-sm" (click)="openTerms()">Edit terms</button>
                    @if (ten.status === 'active') { <button class="btn btn-sm" (click)="notice = { notice_date: todayStr, planned_move_out: '' }; noticeOpen.set(true)">Record notice</button> }
                    <button class="btn btn-sm" (click)="openMoveOut()">Move out</button>
                    <button class="btn btn-sm" (click)="openTransfer()">Transfer unit</button>
                  </div>
                }
              </div>
            </div>
          } @else {
            <div class="card"><app-empty icon="door" title="No tenancy yet" text="Assign this tenant to a vacant unit to start their rent account.">
              @if (auth.can('manage_tenants')) { <button class="btn btn-primary" (click)="openMoveIn()">Move into a unit</button> }
            </app-empty></div>
          }

          @if (acct(); as a) {
            <div class="grid-4">
              <app-stat label="Balance" [value]="money(a.balance)" [hint]="+a.balance < 0 ? 'In credit' : ''" icon="wallet" [tone]="+a.balance > 0 ? 'amber' : 'green'" />
              <app-stat label="Overdue" [value]="money(a.overdue_amount)" [hint]="a.days_overdue ? a.days_overdue + ' days' : ''" icon="alert" [tone]="+a.overdue_amount > 0 ? 'red' : 'green'" />
              <app-stat label="Total paid" [value]="money(a.total_paid)" [hint]="+a.pending_payments ? money(a.pending_payments) + ' pending' : ''" icon="check" />
              <app-stat label="Next due" [value]="a.next_due_date ? (a.next_due_date | date: 'd MMM') : '—'" [hint]="money(a.next_due_amount)" icon="calendar" tone="blue" />
            </div>
          }

          @if (auth.can('view_payments') && tenancy()) {
            <div class="card">
              <div class="tabs" style="margin:0;padding:0 12px">
                @for (x of ['statement', 'payments', 'charges']; track x) { <button class="tab" [class.active]="tab() === x" (click)="tab.set(x)">{{ x | label }}</button> }
              </div>
              @switch (tab()) {
                @case ('statement') {
                  <div class="toolbar"><span class="muted small" style="flex:1">Charges and verified payments, oldest first.</span>
                    <button class="btn btn-sm" (click)="api.download('tenancies/' + tenancy().id + '/ledger/', { export: 'pdf' }, 'statement.pdf')"><app-icon name="download" [size]="15" /> PDF statement</button></div>
                  @if (!ledger().length) { <p class="card-body muted">No entries yet.</p> }
                  <div class="table-wrap"><table class="table responsive">
                    @if (ledger().length) { <thead><tr><th>Date</th><th>Description</th><th class="num">Charge</th><th class="num">Paid / credit</th><th class="num">Balance</th></tr></thead> }
                    <tbody>@for (r of ledger(); track r.type + r.id) {
                      <tr><td data-label="Date" class="nowrap">{{ r.date | date: 'd MMM yyyy' }}</td>
                        <td data-label="Description">{{ r.description }} @if (r.is_simulated) { <span class="sim-flag">SIMULATED</span> } @if (r.receipt_number) { <span class="sub mono">{{ r.receipt_number }}</span> }</td>
                        <td data-label="Charge" class="num">{{ r.debit ? (r.debit | kes) : '' }}</td>
                        <td data-label="Paid / credit" class="num text-green">{{ r.credit ? (r.credit | kes) : '' }}</td>
                        <td data-label="Balance" class="num strong">{{ r.balance | kes }}</td></tr>
                    }</tbody></table></div>
                }
                @case ('payments') {
                  @if (!payments().length) { <p class="card-body muted">No payments recorded.</p> }
                  <div class="table-wrap"><table class="table responsive">
                    @if (payments().length) { <thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th><th>Status</th><th></th></tr></thead> }
                    <tbody>@for (p of payments(); track p.id) {
                      <tr><td data-label="Date">{{ p.paid_on | date: 'd MMM yyyy' }}</td><td data-label="Method">{{ p.method_label }} @if (p.is_simulated) { <span class="sim-flag">SIMULATED</span> }<span class="sub">by {{ p.recorded_by_name || 'tenant (STK)' }}</span></td>
                        <td data-label="Reference" class="mono">{{ p.reference || '—' }}</td><td data-label="Amount" class="num">{{ p.amount | kes }}</td>
                        <td data-label="Status"><app-badge [value]="p.status" /></td>
                        <td class="actions">@if (p.status === 'verified') { <button class="btn btn-sm btn-ghost" (click)="api.download('payments/' + p.id + '/receipt/', {}, 'receipt.pdf')">Receipt</button> }
                          @if (p.status === 'pending' && auth.can('verify_payments')) { <button class="btn btn-sm" (click)="verify(p)">Verify</button> }</td></tr>
                    }</tbody></table></div>
                }
                @case ('charges') {
                  <div class="table-wrap"><table class="table responsive">
                    <thead><tr><th>Due</th><th>Description</th><th>Type</th><th class="num">Amount</th><th></th></tr></thead>
                    <tbody>@for (c of charges(); track c.id) {
                      <tr [style.opacity]="c.voided ? .5 : 1"><td data-label="Due">{{ c.due_date | date: 'd MMM yyyy' }}</td><td data-label="Description">{{ c.description }} @if (c.voided) { <span class="sub">Voided: {{ c.void_reason }}</span> }</td>
                        <td data-label="Type">{{ c.kind_label }}</td><td data-label="Amount" class="num" [class.text-green]="c.kind === 'credit'">{{ c.kind === 'credit' ? '−' : '' }}{{ c.amount | kes }}</td>
                        <td class="actions">@if (!c.voided && auth.can('manage_payments')) { <button class="btn btn-sm btn-ghost" (click)="voidCharge(c)">Void</button> }</td></tr>
                    }</tbody></table></div>
                }
              }
            </div>
          }

          @if ((t().tenancies?.length ?? 0) > 1) {
            <div class="card"><div class="card-head"><h2>Tenancy history</h2></div>
              <ul class="list">@for (h of t().tenancies; track h.id) {
                <li class="row-between"><span>{{ h.unit_label }}, {{ h.property_name }} <span class="muted small">{{ h.start_date | date: 'MMM yyyy' }} – {{ h.actual_move_out ? (h.actual_move_out | date: 'MMM yyyy') : 'now' }}</span></span>
                  <span class="row"><app-badge [value]="h.status" /><button class="btn btn-sm btn-ghost" (click)="selectTenancy(h.id)">View</button></span></li>
              }</ul></div>
          }
        </div>

        <aside class="stack">
          <div class="card card-pad">
            <h3>Contact</h3>
            <dl class="kv">
              <dt>Phone</dt><dd><a [href]="'tel:' + t().phone">{{ t().phone }}</a></dd>
              @if (t().email !== undefined) { <dt>Email</dt><dd>{{ t().email || '—' }}</dd> }
              @if (t().alternative_phone) { <dt>Alt. phone</dt><dd>{{ t().alternative_phone }}</dd> }
              @if (t().id_number !== undefined) { <dt>ID / passport</dt><dd>{{ t().id_number || '—' }}</dd> }
              @if (t().occupation) { <dt>Occupation</dt><dd>{{ t().occupation }}</dd> }
            </dl>
          </div>
          @if (t().emergency_contact_name !== undefined) {
            <div class="card card-pad"><h3>Emergency contact</h3>
              <p>{{ t().emergency_contact_name || '—' }} @if (t().emergency_contact_relationship) { <span class="muted">({{ t().emergency_contact_relationship }})</span> }<br>{{ t().emergency_contact_phone }}</p></div>
            <div class="card card-pad"><h3>Communication preferences</h3>
              <div class="chips"><span class="chip" [class.selected]="true">In-app</span><span class="chip" [class.selected]="t().notify_sms">SMS</span>
                <span class="chip" [class.selected]="t().notify_email">Email</span><span class="chip" [class.selected]="t().notify_whatsapp">WhatsApp</span></div></div>
            @if (t().notes) { <div class="card card-pad"><h3>Internal notes</h3><p class="small" style="white-space:pre-line">{{ t().notes }}</p></div> }
          }
        </aside>
      </div>
    }

    <!-- Modals -->
    <app-modal [(open)]="editOpen" title="Edit tenant details" [wide]="true">
      <form (ngSubmit)="saveEdit()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>First name</span><input name="fn" [(ngModel)]="edit.first_name"></label>
          <label class="field"><span>Last name</span><input name="ln" [(ngModel)]="edit.last_name"></label>
          <label class="field"><span>Phone</span><input name="ph" [(ngModel)]="edit.phone"></label>
          <label class="field"><span>Email</span><input name="em" type="email" [(ngModel)]="edit.email"></label>
          <label class="field"><span>Alternative phone</span><input name="ap" [(ngModel)]="edit.alternative_phone"></label>
          <label class="field"><span>ID / passport</span><input name="id" [(ngModel)]="edit.id_number"></label>
          <label class="field"><span>Emergency contact</span><input name="ecn" [(ngModel)]="edit.emergency_contact_name"></label>
          <label class="field"><span>Emergency phone</span><input name="ecp" [(ngModel)]="edit.emergency_contact_phone"></label>
          <div class="span-2 row"><label class="check"><input type="checkbox" name="ns" [(ngModel)]="edit.notify_sms"> SMS</label>
            <label class="check"><input type="checkbox" name="ne" [(ngModel)]="edit.notify_email"> Email</label>
            <label class="check"><input type="checkbox" name="nw" [(ngModel)]="edit.notify_whatsapp"> WhatsApp</label></div>
          <label class="field span-2"><span>Internal notes (never shown to the tenant)</span><textarea name="no" rows="3" [(ngModel)]="edit.notes"></textarea></label>
        </div>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="payOpen" title="Record a payment">
      <form (ngSubmit)="savePayment()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <p class="muted small">For cash, bank transfers or M-Pesa payments received outside the portal. Tenant STK payments are recorded automatically; payments the tenant reports from the portal already appear under Payments as pending.</p>
        <div class="form-grid">
          <label class="field"><span>Amount (KES) *</span><input type="number" min="1" name="a" [(ngModel)]="pay.amount" required></label>
          <label class="field"><span>Date received *</span><input type="date" name="d" [(ngModel)]="pay.paid_on" required></label>
          <label class="field"><span>Method *</span><select name="m" [(ngModel)]="pay.method"><option value="cash">Cash</option><option value="bank">Bank transfer / deposit</option><option value="mpesa_manual">M-Pesa (paybill, recorded manually)</option><option value="mpesa_phone">M-Pesa Send Money to landlord's number</option><option value="cheque">Cheque</option><option value="other">Other</option></select></label>
          <label class="field"><span>Reference {{ pay.method === 'cash' ? '' : '*' }}</span><input name="r" [(ngModel)]="pay.reference"></label>
          <label class="field span-2"><span>Notes</span><input name="n" [(ngModel)]="pay.notes"></label>
        </div>
        @if (auth.can('verify_payments')) { <label class="check"><input type="checkbox" name="v" [(ngModel)]="pay.mark_verified"> I have confirmed this money was received – mark as verified and issue a receipt</label> }
        @else { <div class="alert alert-info">The payment will be saved as <b>pending verification</b> until an administrator confirms it.</div> }
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !pay.amount">Save payment</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="chargeOpen" title="Add a charge or credit">
      <form (ngSubmit)="saveCharge()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>Type</span><select name="k" [(ngModel)]="charge.kind"><option value="credit">Credit / adjustment (reduces balance)</option><option value="utility">Utility</option><option value="service">Service charge</option><option value="other">Other agreed charge</option></select></label>
          <label class="field"><span>Amount (KES)</span><input type="number" min="1" name="a" [(ngModel)]="charge.amount"></label>
          <label class="field span-2"><span>Description *</span><input name="d" [(ngModel)]="charge.description" placeholder="e.g. Water bill – September"></label>
          <label class="field"><span>Due date</span><input type="date" name="dd" [(ngModel)]="charge.due_date"></label>
        </div>
        <p class="muted small">Only add charges agreed in the tenancy. Penalties should not be applied without an approved policy.</p>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !charge.amount || !charge.description">Save</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="termsOpen" title="Tenancy terms & reminders">
      <form (ngSubmit)="saveTerms()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>Monthly rent (future months)</span><input type="number" name="mr" [(ngModel)]="terms.monthly_rent"></label>
          <label class="field"><span>Service charge</span><input type="number" name="sc" [(ngModel)]="terms.service_charge"></label>
          <label class="field"><span>Rent due day</span><input type="number" min="1" max="28" name="dd" [(ngModel)]="terms.rent_due_day"></label>
          <label class="field"><span>Grace period (days)</span><input type="number" min="0" name="gd" [(ngModel)]="terms.grace_days"></label>
          <label class="field"><span>Expected end date</span><input type="date" name="ee" [(ngModel)]="terms.expected_end_date"></label>
          <label class="field"><span>Reminder schedule</span><select name="rs" [(ngModel)]="terms.reminder_schedule"><option [ngValue]="null">Company default</option>
            @for (s of schedules(); track s.id) { <option [ngValue]="s.id">{{ s.name }}</option> }</select></label>
        </div>
        <label class="check"><input type="checkbox" name="re" [(ngModel)]="terms.reminders_enabled"> Send automatic rent reminders</label>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="noticeOpen" title="Record notice to vacate">
      <form (ngSubmit)="saveNotice()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>Notice date</span><input type="date" name="nd" [(ngModel)]="notice.notice_date"></label>
          <label class="field"><span>Planned move-out</span><input type="date" name="pm" [(ngModel)]="notice.planned_move_out"></label>
        </div>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !notice.planned_move_out">Save notice</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="moveOutOpen" title="Complete move-out" [wide]="true">
      <form (ngSubmit)="saveMoveOut()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>Actual move-out date *</span><input type="date" name="am" [(ngModel)]="moveOut.actual_move_out"></label>
          <label class="field"><span>Inspection date</span><input type="date" name="id" [(ngModel)]="moveOut.inspection_date"></label>
          <label class="field span-2"><span>Inspection notes</span><textarea rows="2" name="in" [(ngModel)]="moveOut.inspection_notes"></textarea></label>
          <label class="field"><span>Deposit held</span><input [value]="tenancy()?.deposit_amount" disabled></label>
          <label class="field"><span>Deposit deductions (KES)</span><input type="number" min="0" name="dd" [(ngModel)]="moveOut.deposit_deductions"></label>
          <label class="field span-2"><span>Reason for deductions</span><input name="dn" [(ngModel)]="moveOut.deduction_notes"></label>
          <label class="field"><span>Unit status after move-out</span><select name="us" [(ngModel)]="moveOut.unit_status_after"><option value="available">Available for letting</option><option value="maintenance">Under maintenance</option><option value="unavailable">Unavailable</option></select></label>
          <label class="field"><span>Unit available from</span><input type="date" name="ua" [(ngModel)]="moveOut.unit_available_from"></label>
        </div>
        <label class="check"><input type="checkbox" name="ap" [(ngModel)]="moveOut.apply_deposit_to_balance"> Apply remaining deposit to any outstanding balance (current balance {{ acct()?.balance | kes }})</label>
        <div class="alert alert-info small">Rent is charged up to the move-out month. The tenancy and all payments remain in the records.</div>
        <div class="form-actions"><button class="btn btn-danger" [disabled]="busy() || !moveOut.actual_move_out">Complete move-out</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="transferOpen" title="Transfer to another unit">
      <form (ngSubmit)="saveTransfer()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <label class="field"><span>Property</span><select name="p" [(ngModel)]="transferProp" (ngModelChange)="loadVacant($event)">
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></label>
        <label class="field"><span>New unit</span><select name="u" [(ngModel)]="transfer.unit"><option [ngValue]="null">— Select —</option>
          @for (u of vacant(); track u.id) { <option [ngValue]="u.id">{{ u.label }} · {{ u.rent_amount | kes }}</option> }</select></label>
        <label class="field"><span>Transfer date</span><input type="date" name="d" [(ngModel)]="transfer.transfer_date"></label>
        <label class="field"><span>New monthly rent (leave blank for unit rent)</span><input type="number" name="r" [(ngModel)]="transfer.monthly_rent"></label>
        <p class="muted small">The current balance and deposit are carried to the new tenancy.</p>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !transfer.unit">Transfer</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="moveInOpen" title="Move into a unit">
      <form (ngSubmit)="saveMoveIn()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <label class="field"><span>Property</span><select name="p" [(ngModel)]="transferProp" (ngModelChange)="loadVacant($event)">
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></label>
        <label class="field"><span>Vacant unit</span><select name="u" [(ngModel)]="mi.unit"><option [ngValue]="null">— Select —</option>
          @for (u of vacant(); track u.id) { <option [ngValue]="u.id">{{ u.label }} · {{ u.rent_amount | kes }}</option> }</select></label>
        <div class="form-grid">
          <label class="field"><span>Start date</span><input type="date" name="sd" [(ngModel)]="mi.start_date"></label>
          <label class="field"><span>Expected end</span><input type="date" name="ed" [(ngModel)]="mi.expected_end_date"></label>
        </div>
        <label class="check"><input type="checkbox" name="cd" [(ngModel)]="mi.charge_deposit"> Charge the unit's deposit to the account</label>
        <label class="field"><span>Move-in inspection notes</span><textarea name="n" rows="2" [(ngModel)]="mi.move_in_inspection_notes"></textarea></label>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !mi.unit">Move in</button></div>
      </form>
    </app-modal>`,
})
export class TenantDetailPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  id = input.required<string>();
  t = signal<any>(null);
  tenancy = signal<any>(null);
  ledger = signal<any[]>([]);
  acct = signal<any>(null);
  payments = signal<any[]>([]);
  charges = signal<any[]>([]);
  schedules = signal<any[]>([]);
  vacant = signal<any[]>([]);
  tab = signal('statement');
  busy = signal(false);
  formErr = signal('');
  todayStr = today();
  editOpen = signal(false); payOpen = signal(false); chargeOpen = signal(false); termsOpen = signal(false);
  noticeOpen = signal(false); moveOutOpen = signal(false); transferOpen = signal(false); moveInOpen = signal(false);
  edit: any = {}; pay: any = {}; charge: any = {}; terms: any = {}; notice: any = {}; moveOut: any = {}; transfer: any = {}; mi: any = {};
  transferProp = '';
  private selectedTenancyId: number | null = null;

  ngOnInit() {
    this.load();
  }

  async load() {
    try {
      const t = await this.api.getP(`tenants/${this.id()}/`);
      this.t.set(t);
      // Caretakers receive a reduced record with only the current tenancy
      const tenancies = t.tenancies ?? (t.current_tenancy ? [t.current_tenancy] : []);
      const current = tenancies.find((x: any) => x.status === 'active' || x.status === 'notice');
      const id = this.selectedTenancyId ?? current?.id ?? tenancies[0]?.id;
      if (id) await this.loadTenancy(id);
      else this.tenancy.set(null);
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async selectTenancy(id: number) {
    this.selectedTenancyId = id;
    await this.loadTenancy(id);
  }

  async loadTenancy(id: number) {
    const ten = await this.api.getP(`tenancies/${id}/`);
    ten.unit_label = ten.unit_label;
    ten.is_current = ten.status === 'active' || ten.status === 'notice';
    this.tenancy.set(ten);
    this.acct.set(ten.account);
    if (this.auth.can('view_payments')) {
      const [ledger, pays, charges] = await Promise.all([
        this.api.getP(`tenancies/${id}/ledger/`),
        this.api.all('payments/', { tenancy: id, ordering: '-paid_on' }),
        this.api.all('charges/', { tenancy: id }),
      ]);
      this.ledger.set(ledger.rows);
      this.acct.set(ledger.account);
      this.payments.set(pays);
      this.charges.set(charges);
    }
  }

  money(v: any) {
    return v === null || v === undefined ? '—' : `KES ${Number(v).toLocaleString('en-KE')}`;
  }

  private async run(fn: () => Promise<any>, done: string, close?: () => void) {
    this.busy.set(true);
    this.formErr.set('');
    try {
      await fn();
      close?.();
      this.ui.toast(done);
      await this.load();
    } catch (e) {
      this.formErr.set(parseError(e).message);
      if (!close) this.ui.error(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  openEdit() {
    this.formErr.set('');
    this.edit = { ...this.t() };
    this.editOpen.set(true);
  }
  saveEdit() {
    const { tenancies, full_name, has_portal_account, portal_active, portal_invitation, created_at, status, ...body } = this.edit;
    return this.run(() => this.api.patchP(`tenants/${this.id()}/`, body), 'Tenant updated.', () => this.editOpen.set(false));
  }

  devLink = signal('');

  async portalAccount() {
    await this.run(async () => {
      const r = await this.api.postP(`tenants/${this.id()}/portal-account/`);
      this.devLink.set(r.dev_invite_link || '');
    }, this.t().has_portal_account ? 'Password link sent.' : 'Invitation sent. The tenant creates their own password from the email link.');
  }
  async revokeInvite() {
    if (!(await this.ui.confirm({ title: 'Revoke portal invitation?', message: 'The emailed link stops working immediately.', danger: true, confirmText: 'Revoke' }))) return;
    this.devLink.set('');
    await this.run(() => this.api.postP(`tenants/${this.id()}/portal-invite/revoke/`), 'Invitation revoked.');
  }
  togglePortal() {
    return this.run(() => this.api.postP(`tenants/${this.id()}/portal-access/`, { enabled: !this.t().portal_active }), 'Portal access updated.');
  }

  openPayment() {
    this.formErr.set('');
    this.pay = { amount: this.acct()?.balance > 0 ? this.acct().balance : null, paid_on: today(), method: 'bank', reference: '', notes: '', mark_verified: this.auth.can('verify_payments') };
    this.payOpen.set(true);
  }
  savePayment() {
    return this.run(() => this.api.postP('payments/', { ...this.pay, tenancy: this.tenancy().id }), 'Payment recorded.', () => this.payOpen.set(false));
  }
  async verify(p: any) {
    if (await this.ui.confirm({ title: 'Verify payment?', message: `Confirm that ${this.money(p.amount)} (${p.reference || p.method_label}) has been received. A receipt will be issued and the tenant notified.`, confirmText: 'Verify' }))
      await this.run(() => this.api.postP(`payments/${p.id}/verify/`), 'Payment verified.');
  }

  openCharge() {
    this.formErr.set('');
    this.charge = { kind: 'credit', amount: null, description: '', due_date: today() };
    this.chargeOpen.set(true);
  }
  saveCharge() {
    return this.run(() => this.api.postP('charges/', { ...this.charge, tenancy: this.tenancy().id }), 'Saved.', () => this.chargeOpen.set(false));
  }
  async voidCharge(c: any) {
    const reason = await this.ui.confirm({ title: 'Void this charge?', message: `${c.description} – ${this.money(c.amount)}`, reasonLabel: 'Reason (recorded in the audit log)', danger: true, confirmText: 'Void charge' });
    if (reason) await this.run(() => this.api.postP(`charges/${c.id}/void/`, { reason }), 'Charge voided.');
  }

  openTerms() {
    this.formErr.set('');
    const t = this.tenancy();
    this.terms = { monthly_rent: t.monthly_rent, service_charge: t.service_charge, rent_due_day: t.rent_due_day, grace_days: t.grace_days,
      expected_end_date: t.expected_end_date, reminder_schedule: t.reminder_schedule, reminders_enabled: t.reminders_enabled };
    this.api.get('reminder-schedules/').subscribe((r) => this.schedules.set(r));
    this.termsOpen.set(true);
  }
  saveTerms() {
    const body = { ...this.terms, expected_end_date: this.terms.expected_end_date || null };
    return this.run(() => this.api.patchP(`tenancies/${this.tenancy().id}/`, body), 'Terms updated.', () => this.termsOpen.set(false));
  }
  saveNotice() {
    return this.run(() => this.api.postP(`tenancies/${this.tenancy().id}/notice/`, this.notice), 'Notice recorded.', () => this.noticeOpen.set(false));
  }

  openMoveOut() {
    this.formErr.set('');
    const t = this.tenancy();
    this.moveOut = { actual_move_out: t.planned_move_out || today(), inspection_date: today(), inspection_notes: '', deposit_deductions: 0,
      deduction_notes: '', apply_deposit_to_balance: true, unit_status_after: 'available', unit_available_from: null };
    this.moveOutOpen.set(true);
  }
  async saveMoveOut() {
    if (!(await this.ui.confirm({ title: 'Complete move-out?', message: 'The tenancy will end and the unit will be released. This cannot be undone.', danger: true, confirmText: 'Complete move-out' }))) return;
    const body = { ...this.moveOut, inspection_date: this.moveOut.inspection_date || null, unit_available_from: this.moveOut.unit_available_from || null };
    await this.run(() => this.api.postP(`tenancies/${this.tenancy().id}/move-out/`, body), 'Move-out completed.', () => this.moveOutOpen.set(false));
  }

  async loadVacant(propertyId: any) {
    this.vacant.set(propertyId ? await this.api.all('units/', { property: propertyId, status: 'available' }) : []);
  }
  openTransfer() {
    this.formErr.set('');
    this.transfer = { unit: null, transfer_date: today(), monthly_rent: null };
    this.transferProp = String(this.tenancy().property);
    this.loadVacant(this.transferProp);
    this.transferOpen.set(true);
  }
  saveTransfer() {
    const body: any = { ...this.transfer };
    if (!body.monthly_rent) delete body.monthly_rent;
    this.selectedTenancyId = null;
    return this.run(() => this.api.postP(`tenancies/${this.tenancy().id}/transfer/`, body), 'Tenant transferred.', () => this.transferOpen.set(false));
  }

  openMoveIn() {
    this.formErr.set('');
    this.mi = { unit: null, start_date: today(), expected_end_date: null, charge_deposit: true, move_in_inspection_notes: '' };
    this.transferProp = String(this.auth.me()?.assigned_properties[0]?.id ?? '');
    this.loadVacant(this.transferProp);
    this.moveInOpen.set(true);
  }
  saveMoveIn() {
    const body = { ...this.mi, tenant: +this.id(), expected_end_date: this.mi.expected_end_date || null };
    return this.run(() => this.api.postP('tenancies/move-in/', body), 'Tenant moved in.', () => this.moveInOpen.set(false));
  }
}
