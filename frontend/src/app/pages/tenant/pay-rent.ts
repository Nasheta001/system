import { Component, DestroyRef, inject, input, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, parseError } from '../../core/api.service';
import { KesPipe } from '../../core/format';
import { Icon, Modal } from '../../shared/ui';

/** Pay Rent dialog.
 *  - "M-Pesa prompt": STK Push via Daraja (paybill/till shortcode), polled until verified.
 *  - "Send Money": the tenant pays the landlord's phone number in the M-Pesa app and reports the
 *    transaction code. That creates a PENDING payment that staff check against the M-Pesa statement;
 *    nothing is shown as paid until then. */
@Component({
  selector: 'app-pay-rent',
  imports: [FormsModule, KesPipe, Icon, Modal],
  template: `
    <app-modal [(open)]="open" title="Pay rent with M-Pesa" (closed)="reset()">
      @switch (step()) {
        @case ('form') {
          @if (mode() !== 'disabled' && sendMoney()?.enabled) {
            <div class="tabs" role="tablist">
              <button type="button" role="tab" [class.active]="method() === 'stk'" (click)="method.set('stk')">M-Pesa prompt</button>
              <button type="button" role="tab" [class.active]="method() === 'phone'" (click)="method.set('phone')">Send Money to landlord</button>
            </div>
          }
          @if (method() === 'phone' && sendMoney()?.enabled) {
            @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
            <ol class="steps small">
              <li>Open M-Pesa and choose <b>Send Money</b>.</li>
              <li>Enter the landlord's number <b class="mono">{{ sendMoney().phone }}</b>@if (sendMoney().name) { and check the name shown is <b>{{ sendMoney().name }}</b> }.</li>
              <li>Send the amount and wait for the M-Pesa confirmation SMS.</li>
              <li>Enter the transaction code from that SMS below.</li>
            </ol>
            <form (ngSubmit)="report()">
              <label class="field"><span>M-Pesa transaction code</span><input name="c" [(ngModel)]="code" placeholder="e.g. SGH7XK2LQP" maxlength="12" autocapitalize="characters" required></label>
              <div class="form-grid">
                <label class="field"><span>Amount sent (KES)</span><input type="number" min="1" step="1" name="ra" [(ngModel)]="amount" required></label>
                <label class="field"><span>Date sent</span><input type="date" name="d" [(ngModel)]="paidOn" required></label>
              </div>
              <p class="muted small">Your balance updates after the office confirms the payment on the M-Pesa statement. You will then get a receipt.</p>
              <button class="btn btn-primary btn-lg btn-block" [disabled]="busy() || !code || !amount || !paidOn">{{ busy() ? 'Submitting…' : 'Submit payment details' }}</button>
            </form>
          } @else if (mode() === 'disabled') {
            <div class="alert alert-warn">Online payment is not enabled. Please pay at the office or contact management.</div>
          } @else {
            @if (mode() === 'simulated') { <div class="alert alert-warn small"><b>Demo mode:</b> M-Pesa is simulated. No real prompt is sent and no money moves.</div> }
            @if (mode() === 'sandbox') { <div class="alert alert-info small">Safaricom sandbox – test transactions only.</div> }
            @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
            <form (ngSubmit)="pay()">
              <label class="field"><span>Amount (KES)</span><input type="number" min="1" step="1" name="a" [(ngModel)]="amount" required>
                <small>Outstanding balance: {{ balance() | kes }}</small></label>
              <label class="field"><span>M-Pesa phone number</span><input type="tel" name="p" [(ngModel)]="phone" placeholder="07XX XXX XXX" required></label>
              <p class="muted small">You will receive a prompt on this phone. Enter your M-Pesa PIN to complete the payment.</p>
              <button class="btn btn-primary btn-lg btn-block" [disabled]="busy() || !amount || !phone">{{ busy() ? 'Sending…' : 'Send payment request' }}</button>
            </form>
          }
        }
        @case ('waiting') {
          <div class="center">
            <span class="spinner big"></span>
            <h3>Check your phone</h3>
            <p class="muted">Enter your M-Pesa PIN on {{ txn()?.phone }} to pay {{ txn()?.amount | kes }}. We'll confirm here once M-Pesa verifies the payment.</p>
            @if (mode() === 'simulated') {
              <div class="sim-box">
                <div class="sim-flag">SIMULATED PHONE</div>
                <p class="small">In demo mode, choose what the customer does on their phone:</p>
                <div class="row" style="justify-content:center">
                  <button class="btn btn-primary" (click)="simulate('success')">Approve payment</button>
                  <button class="btn" (click)="simulate('cancel')">Cancel on phone</button>
                </div>
              </div>
            }
          </div>
        }
        @case ('reported') {
          <div class="center">
            <span class="f-icon ok"><app-icon name="check" /></span>
            <h3>Payment details submitted</h3>
            <p>We have recorded M-Pesa code <b class="mono">{{ reported()?.reference }}</b> for {{ reported()?.amount | kes }}.</p>
            <p class="muted small">It shows as <b>pending</b> until the office confirms it on the M-Pesa statement. Your receipt is issued then.</p>
            <button class="btn btn-primary" (click)="finish()">Done</button>
          </div>
        }
        @case ('done') {
          <div class="center">
            @if (txn()?.status === 'success') {
              <span class="f-icon ok"><app-icon name="check" /></span>
              <h3>Payment received</h3>
              <p>{{ txn()?.amount | kes }} has been recorded. Receipt <b class="mono">{{ txn()?.receipt_number }}</b>.</p>
              @if (txn()?.is_simulated) { <p class="sim-flag">SIMULATED – demo only, no money was transferred</p> }
            } @else {
              <span class="f-icon bad"><app-icon name="x" /></span>
              <h3>{{ txn()?.status === 'cancelled' ? 'Payment cancelled' : txn()?.status === 'timeout' ? 'No response received' : 'Payment not completed' }}</h3>
              <p class="muted">{{ txn()?.result_desc || 'No money was taken. You can try again.' }}</p>
            }
            <button class="btn btn-primary" (click)="finish()">Done</button>
          </div>
        }
      }
    </app-modal>`,
  styles: `
    .center { text-align: center; padding: 8px 0; }
    .spinner.big { width: 40px; height: 40px; border-width: 3px; display: inline-block; margin-bottom: 10px; }
    .sim-box { border: 1px dashed #f3a59e; border-radius: 10px; padding: 14px; margin-top: 14px; background: #fffaf9; }
    .f-icon { width: 52px; height: 52px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 8px; }
    .f-icon.ok { background: var(--green-bg); color: var(--green); }
    .f-icon.bad { background: var(--red-bg); color: var(--red); }
    .tabs { display: flex; gap: 6px; margin-bottom: 14px; border-bottom: 1px solid var(--line); }
    .tabs button { background: none; border: 0; border-bottom: 2px solid transparent; padding: 8px 10px; font: inherit; cursor: pointer; color: var(--muted); }
    .tabs button.active { border-color: var(--brand); color: var(--ink); font-weight: 600; }
    .steps { padding-left: 18px; margin: 0 0 12px; line-height: 1.6; }
  `,
})
export class PayRent {
  private api = inject(Api);
  open = model(false);
  balance = input<any>(0);
  suggested = input<any>(0);
  defaultPhone = input('');
  mode = input('simulated');
  paid = output<void>();
  step = signal<'form' | 'waiting' | 'done' | 'reported'>('form');
  method = signal<'stk' | 'phone'>('stk');
  sendMoney = signal<any>(null);
  reported = signal<any>(null);
  code = '';
  paidOn = new Date().toISOString().slice(0, 10);
  txn = signal<any>(null);
  busy = signal(false);
  error = signal('');
  amount: any = null;
  phone = '';
  private timer: any;

  constructor() {
    inject(DestroyRef).onDestroy(() => clearInterval(this.timer));
  }

  ngOnChanges() {
    if (this.open() && this.step() === 'form') {
      this.amount = Math.ceil(Number(this.suggested()) || 0) || null;
      this.phone = this.defaultPhone();
      this.api.getP('portal/payments/phone-report/').then((cfg) => {
        this.sendMoney.set(cfg);
        this.method.set(this.mode() === 'disabled' && cfg.enabled ? 'phone' : 'stk');
      }).catch(() => this.sendMoney.set(null));
    }
  }

  async report() {
    this.busy.set(true);
    this.error.set('');
    try {
      this.reported.set(await this.api.postP('portal/payments/phone-report/', { mpesa_code: this.code, amount: this.amount, paid_on: this.paidOn }));
      this.step.set('reported');
      this.paid.emit();
    } catch (e) {
      const err = parseError(e);
      this.error.set(err.fields['mpesa_code'] || err.fields['amount'] || err.fields['paid_on'] || err.message);
    } finally {
      this.busy.set(false);
    }
  }

  async pay() {
    this.busy.set(true);
    this.error.set('');
    try {
      this.txn.set(await this.api.postP('portal/payments/mpesa/', { phone: this.phone, amount: this.amount }));
      this.step.set('waiting');
      this.poll();
    } catch (e) {
      this.error.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  private poll() {
    clearInterval(this.timer);
    let tries = 0;
    this.timer = setInterval(async () => {
      tries++;
      try {
        const t = await this.api.getP(`portal/payments/mpesa/${this.txn().id}/`);
        this.txn.set(t);
        if (t.status !== 'pending') {
          clearInterval(this.timer);
          this.step.set('done');
          if (t.status === 'success') this.paid.emit();
        }
      } catch {
        /* keep polling */
      }
      if (tries > 60) {
        clearInterval(this.timer);
        this.txn.update((t) => ({ ...t, status: 'timeout', result_desc: 'We have not received confirmation yet. If money was deducted it will reflect once M-Pesa confirms.' }));
        this.step.set('done');
      }
    }, 3000);
  }

  async simulate(outcome: 'success' | 'cancel') {
    try {
      const t = await this.api.postP(`portal/payments/mpesa/${this.txn().id}/simulate/`, { outcome });
      clearInterval(this.timer);
      this.txn.set(t);
      this.step.set('done');
      if (t.status === 'success') this.paid.emit();
    } catch (e) {
      this.error.set(parseError(e).message);
    }
  }

  finish() {
    this.open.set(false);
    this.reset();
  }

  reset() {
    clearInterval(this.timer);
    this.step.set('form');
    this.txn.set(null);
    this.reported.set(null);
    this.code = '';
    this.error.set('');
  }
}
