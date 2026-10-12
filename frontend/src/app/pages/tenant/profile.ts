import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, parseError } from '../../core/api.service';
import { Ui } from '../../core/ui.service';
import { Loading } from '../../shared/ui';
import { StaffNotificationsPage } from '../management/notifications';

@Component({
  imports: [FormsModule, Loading, StaffNotificationsPage],
  template: `
    <h1>My profile</h1>
    @if (!p()) { <app-loading /> } @else {
      <div class="grid-2">
        <form class="card card-pad" (ngSubmit)="save()">
          <h2>Contact details</h2>
          <p class="muted small">To change your name, email or main phone number, contact management.</p>
          <dl class="kv mb"><dt>Name</dt><dd>{{ p().full_name }}</dd><dt>Email</dt><dd>{{ p().email || '—' }}</dd><dt>Phone</dt><dd>{{ p().phone }}</dd></dl>
          <label class="field"><span>Alternative phone</span><input name="ap" [(ngModel)]="form.alternative_phone"></label>
          <h3>Emergency contact</h3>
          <label class="field"><span>Name</span><input name="en" [(ngModel)]="form.emergency_contact_name"></label>
          <div class="form-grid">
            <label class="field"><span>Phone</span><input name="ep" [(ngModel)]="form.emergency_contact_phone"></label>
            <label class="field"><span>Relationship</span><input name="er" [(ngModel)]="form.emergency_contact_relationship"></label>
          </div>
          <h3>How should we contact you?</h3>
          <p class="muted small">Portal notifications are always on. Messages never include your full financial history.</p>
          <label class="check"><input type="checkbox" name="s" [(ngModel)]="form.notify_sms"> SMS</label>
          <label class="check"><input type="checkbox" name="e" [(ngModel)]="form.notify_email"> Email</label>
          <label class="check"><input type="checkbox" name="w" [(ngModel)]="form.notify_whatsapp"> WhatsApp</label>
          <div class="form-actions"><button class="btn btn-primary">Save</button></div>
        </form>
        <div class="stack">
          <form class="card card-pad" (ngSubmit)="changePassword()">
            <h2>Change password</h2>
            @if (pwErr()) { <div class="alert alert-error">{{ pwErr() }}</div> }
            <label class="field"><span>Current password</span><input type="password" name="c" [(ngModel)]="pw.current_password" autocomplete="current-password"></label>
            <label class="field"><span>New password</span><input type="password" name="n" [(ngModel)]="pw.new_password" autocomplete="new-password"></label>
            <label class="field"><span>Confirm</span><input type="password" name="n2" [(ngModel)]="pw.confirm" autocomplete="new-password"></label>
            <div class="form-actions"><button class="btn" [disabled]="!pw.current_password || !pw.new_password || pw.new_password !== pw.confirm">Update password</button></div>
          </form>
        </div>
      </div>
      <div class="mt"><app-inbox /></div>
    }`,
})
export class TenantProfilePage {
  private api = inject(Api);
  private ui = inject(Ui);
  p = signal<any>(null);
  form: any = {};
  pw: any = { current_password: '', new_password: '', confirm: '' };
  pwErr = signal('');

  constructor() {
    this.api.getP('portal/profile/').then((p) => {
      this.p.set(p);
      this.form = { ...p };
    });
  }

  async save() {
    try {
      const { alternative_phone, emergency_contact_name, emergency_contact_phone, emergency_contact_relationship, notify_sms, notify_email, notify_whatsapp } = this.form;
      this.p.set(await this.api.patchP('portal/profile/', { alternative_phone, emergency_contact_name, emergency_contact_phone, emergency_contact_relationship, notify_sms, notify_email, notify_whatsapp }));
      this.ui.toast('Profile saved.');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async changePassword() {
    this.pwErr.set('');
    try {
      await this.api.postP('auth/password/change/', { current_password: this.pw.current_password, new_password: this.pw.new_password });
      this.pw = { current_password: '', new_password: '', confirm: '' };
      this.ui.toast('Password updated.');
    } catch (e) {
      const err = parseError(e);
      this.pwErr.set(err.fields['new_password'] || err.fields['current_password'] || err.message);
    }
  }
}
