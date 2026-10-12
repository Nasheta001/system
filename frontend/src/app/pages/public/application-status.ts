import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { Api, parseError } from '../../core/api.service';
import { Ui } from '../../core/ui.service';
import { Badge } from '../../shared/ui';

@Component({
  imports: [FormsModule, Badge, DatePipe],
  template: `
    <div class="pub-wrap narrow-page">
      <div class="card card-pad">
        <h1>Check your application</h1>
        <p class="muted">Enter the reference number you received and the email you applied with.</p>
        @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
        <form (ngSubmit)="lookup()">
          <label class="field"><span>Reference number</span><input name="r" [(ngModel)]="reference" placeholder="APP-XXXXXXXX" required></label>
          <label class="field"><span>Email</span><input name="e" type="email" [(ngModel)]="email" required></label>
          <button class="btn btn-primary btn-block" [disabled]="busy() || !reference || !email">Check status</button>
        </form>
        @if (result(); as r) {
          <div class="divider"></div>
          <dl class="kv">
            <dt>Reference</dt><dd class="mono">{{ r.reference }}</dd>
            <dt>Property</dt><dd>{{ r.property }} – Unit {{ r.unit }}</dd>
            <dt>Submitted</dt><dd>{{ r.submitted | date: 'mediumDate' }}</dd>
            <dt>Status</dt><dd><app-badge [value]="r.status" /></dd>
            @if (r.message) { <dt>Message</dt><dd>{{ r.message }}</dd> }
          </dl>
          @if (r.status === 'pending' || r.status === 'under_review' || r.status === 'approved') {
            <div class="form-actions"><button class="btn btn-ghost text-red" (click)="withdraw()">Withdraw application</button></div>
          }
        }
      </div>
    </div>`,
})
export class ApplicationStatusPage {
  private api = inject(Api);
  private ui = inject(Ui);
  ref = input<string>('');
  reference = '';
  email = '';
  busy = signal(false);
  error = signal('');
  result = signal<any>(null);

  ngOnInit() {
    this.reference = this.ref() || '';
  }

  async lookup(withdraw = false) {
    this.busy.set(true);
    this.error.set('');
    try {
      this.result.set(await this.api.postP('public/applications/status/', { reference: this.reference, email: this.email, withdraw }));
    } catch (e) {
      this.result.set(null);
      this.error.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async withdraw() {
    if (await this.ui.confirm({ title: 'Withdraw application?', message: 'This cannot be undone.', danger: true, confirmText: 'Withdraw' })) {
      await this.lookup(true);
    }
  }
}
