import { DatePipe } from '@angular/common';
import { ChangeDetectorRef, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { CompanyStore } from '../../core/company.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, DatePipe, LabelPipe, Badge, Empty, Icon, PageHeader, Pager],
  template: `
    <app-page-header title="Settings" />
    <div class="tabs">
      @for (t of tabs(); track t[0]) { <button class="tab" [class.active]="tab() === t[0]" (click)="setTab(t[0])">{{ t[1] }}</button> }
    </div>

    @switch (tab()) {
      @case ('account') {
        <form class="card card-pad" style="max-width:520px" (ngSubmit)="changePassword()">
          <h2>Change password</h2>
          @if (pwErr()) { <div class="alert alert-error">{{ pwErr() }}</div> }
          <label class="field"><span>Current password</span><input type="password" name="c" [(ngModel)]="pw.current_password" autocomplete="current-password"></label>
          <label class="field"><span>New password (min. 10 characters)</span><input type="password" name="n" [(ngModel)]="pw.new_password" autocomplete="new-password"></label>
          <label class="field"><span>Confirm new password</span><input type="password" name="n2" [(ngModel)]="pw.confirm" autocomplete="new-password"></label>
          <div class="form-actions"><button class="btn btn-primary" [disabled]="!pw.current_password || !pw.new_password || pw.new_password !== pw.confirm">Update password</button></div>
        </form>
      }
      @case ('company') {
        <form class="card card-pad" style="max-width:900px" (ngSubmit)="saveCompany()">
          <div class="form-grid">
            <label class="field"><span>Company name</span><input name="n" [(ngModel)]="company.name"></label>
            <label class="field"><span>Tagline</span><input name="t" [(ngModel)]="company.tagline"></label>
            <label class="field"><span>Phone</span><input name="p" [(ngModel)]="company.phone"></label>
            <label class="field"><span>WhatsApp (international format)</span><input name="w" [(ngModel)]="company.whatsapp"></label>
            <label class="field"><span>Email</span><input name="e" type="email" [(ngModel)]="company.email"></label>
            <label class="field"><span>Address</span><input name="a" [(ngModel)]="company.address"></label>
            <label class="field"><span>Default grace period (days)</span><input type="number" name="g" [(ngModel)]="company.default_grace_days"></label>
            <label class="field"><span>Reservation expiry (days)</span><input type="number" name="r" [(ngModel)]="company.reservation_expiry_days"></label>
            <label class="field"><span>Receipt prefix</span><input name="rp" [(ngModel)]="company.receipt_prefix" maxlength="10"></label>
            <label class="field"><span>Currency</span><input name="c" [(ngModel)]="company.currency" maxlength="3"></label>
            <fieldset class="span-2 rent-phone">
              <legend>Rent by M-Pesa Send Money (landlord's phone)</legend>
              <div class="form-grid">
                <label class="field"><span>Rent-receiving M-Pesa number</span><input name="rrp" [(ngModel)]="company.rent_receiving_phone" placeholder="+2547XXXXXXXX"></label>
                <label class="field"><span>Name M-Pesa shows for this number</span><input name="rrn" [(ngModel)]="company.rent_receiving_name" placeholder="As shown in the M-Pesa confirmation"></label>
              </div>
              <label class="check"><input type="checkbox" name="rpe" [(ngModel)]="company.rent_phone_payments_enabled"> Show this number to tenants in the portal</label>
              <p class="muted small">Tenants send rent from their M-Pesa app and enter the confirmation code. Safaricom does not notify this system about payments to a personal number, so each report stays <b>pending</b> until an administrator or landlord checks it on the M-Pesa statement and verifies it under Payments. The number is only shown to signed-in tenants.</p>
            </fieldset>
            <label class="field span-2"><span>About (public website)</span><textarea name="ab" rows="4" [(ngModel)]="company.about"></textarea></label>
            <label class="field span-2"><span>Privacy notice (public website)</span><textarea name="pn" rows="5" [(ngModel)]="company.privacy_notice"></textarea></label>
          </div>
          <h3>Frequently asked questions</h3>
          @for (q of company.faq; track $index; let i = $index) {
            <div class="faq-edit"><input [(ngModel)]="q.question" [name]="'q' + i" placeholder="Question"><textarea [(ngModel)]="q.answer" [name]="'a' + i" rows="2" placeholder="Answer"></textarea>
              <button type="button" class="btn btn-sm btn-ghost" (click)="company.faq.splice(i, 1)">Remove</button></div>
          }
          <button type="button" class="btn btn-sm" (click)="company.faq.push({ question: '', answer: '' })"><app-icon name="plus" [size]="14" /> Add question</button>
          <div class="form-actions"><button class="btn btn-primary" [disabled]="!auth.can('manage_settings')">Save company settings</button></div>
        </form>
      }
      @case ('reminders') {
        <div class="stack">
          <div class="alert alert-info">Reminders are sent only while a balance is outstanding and stop automatically once it is paid. They never add penalties or threaten legal action. Wording is edited under Message templates.</div>
          @for (s of schedules(); track s.id) {
            <form class="card" (ngSubmit)="saveSchedule(s)">
              <div class="card-head"><input [(ngModel)]="s.name" [name]="'n' + s.id" style="max-width:320px">
                <label class="check" style="margin:0"><input type="checkbox" [(ngModel)]="s.is_default" [name]="'d' + s.id"> Default schedule</label></div>
              <div class="card-body">
                @for (st of s.steps; track $index; let i = $index) {
                  <div class="step-row">
                    <label class="field"><span>Days from due date</span><input type="number" [(ngModel)]="st.offset_days" [name]="s.id + 'o' + i"></label>
                    <label class="field"><span>Reminder type</span><select [(ngModel)]="st.kind" [name]="s.id + 'k' + i"><option value="rent_upcoming">Upcoming (before due)</option><option value="rent_due">Due today</option><option value="rent_overdue">Overdue (after due)</option></select></label>
                    <label class="check"><input type="checkbox" [(ngModel)]="st.alert_management" [name]="s.id + 'a' + i"> Alert manager</label>
                    <button type="button" class="btn btn-sm btn-ghost" (click)="s.steps.splice(i, 1)">Remove</button>
                  </div>
                }
                <div class="row-between"><button type="button" class="btn btn-sm" (click)="s.steps.push({ offset_days: 1, kind: 'rent_overdue', alert_management: false, custom_message: '' })">Add step</button>
                  <button class="btn btn-primary btn-sm" [disabled]="!auth.can('manage_settings')">Save schedule</button></div>
              </div>
            </form>
          }
          @if (auth.can('manage_settings')) { <button class="btn" (click)="addSchedule()"><app-icon name="plus" /> New schedule</button> }
        </div>
      }
      @case ('templates') {
        <div class="stack">
          <div class="alert alert-info">Placeholders: {{ placeholders }}. Keep SMS text short and free of private details.</div>
          @for (t of templates(); track t.id) {
            <form class="card card-pad" (ngSubmit)="saveTemplate(t)">
              <div class="row-between"><h3 style="margin:0">{{ t.name }} <span class="muted small mono">{{ t.key }}</span></h3>
                <label class="check" style="margin:0"><input type="checkbox" [(ngModel)]="t.is_active" [name]="'a' + t.id"> Active</label></div>
              <label class="field mt"><span>Subject</span><input [(ngModel)]="t.subject" [name]="'s' + t.id"></label>
              <label class="field"><span>Email / in-app body</span><textarea rows="4" [(ngModel)]="t.body" [name]="'b' + t.id"></textarea></label>
              <label class="field"><span>SMS / WhatsApp text ({{ t.short_body.length }}/320)</span><textarea rows="2" maxlength="320" [(ngModel)]="t.short_body" [name]="'sb' + t.id"></textarea></label>
              <div class="form-actions"><button class="btn btn-sm btn-primary">Save</button></div>
            </form>
          }
        </div>
      }
      @case ('channels') {
        <div class="stack">
          <div class="grid-4">
            @for (c of channelList(); track c.key) {
              <div class="card card-pad"><div class="row-between"><b>{{ c.key | label }}</b><app-badge [value]="c.active ? 'active' : 'logged'" [text]="c.active ? 'Active' : 'Not configured'" /></div>
                <p class="muted small" style="margin-top:6px">{{ c.detail }}</p></div>
            }
            <div class="card card-pad"><div class="row-between"><b>M-Pesa</b><app-badge [value]="mpesa()?.is_live ? 'active' : 'logged'" [text]="mpesa()?.mpesa_mode" /></div><p class="muted small" style="margin-top:6px">{{ mpesa()?.label }}</p></div>
          </div>
          <div class="card">
            <div class="card-head"><h2>Notification log</h2>
              @if (auth.can('manage_settings')) { <button class="btn btn-sm" (click)="runJobs()" [disabled]="running()"><app-icon name="refresh" [size]="14" /> {{ running() ? 'Running…' : 'Run scheduled jobs now' }}</button> }</div>
            <div class="toolbar">
              <select [(ngModel)]="log.filters['channel']" (change)="log.load(true)"><option value="">All channels</option><option value="in_app">In-app</option><option value="email">Email</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option></select>
              <select [(ngModel)]="log.filters['status']" (change)="log.load(true)"><option value="">Any status</option><option value="sent">Sent</option><option value="delivered">Delivered (in-app)</option><option value="logged">Logged only</option><option value="failed">Failed</option><option value="queued">Queued</option></select>
            </div>
            @if (!log.items().length) { <app-empty icon="bell" title="No notifications yet" /> }
            <div class="table-wrap"><table class="table responsive">
              <tbody>@for (n of log.items(); track n.id) {
                <tr><td data-label="When" class="nowrap">{{ n.created_at | date: 'd MMM HH:mm' }}</td><td data-label="Channel">{{ n.channel | label }}</td>
                  <td data-label="To">{{ n.recipient }}<span class="sub">{{ n.to_address }}</span></td>
                  <td data-label="Message">{{ n.subject }}<span class="sub">{{ n.body.slice(0, 90) }}{{ n.body.length > 90 ? '…' : '' }}</span></td>
                  <td data-label="Status"><app-badge [value]="n.status" />@if (n.last_error) { <span class="sub text-red">{{ n.last_error }}</span> }<span class="sub">{{ n.attempts }} attempt(s)</span></td>
                  <td class="actions">@if (n.status === 'failed' && auth.can('manage_settings')) { <button class="btn btn-sm" (click)="retry(n)">Retry</button> }</td></tr>
              }</tbody></table></div>
            <app-pager [count]="log.count()" [page]="log.page()" (pageChange)="log.go($event)" />
          </div>
        </div>
      }
    }`,
  styles: `
    .rent-phone { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin: 4px 0 8px; }
    .rent-phone legend { font-weight: 600; padding: 0 6px; }
    .faq-edit { display: grid; grid-template-columns: 1fr 2fr auto; gap: 8px; margin-bottom: 8px; align-items: start; }
    .step-row { display: grid; grid-template-columns: 160px 1fr auto auto; gap: 12px; align-items: end; border-bottom: 1px dashed var(--line); margin-bottom: 10px; }
    @media (max-width: 720px) { .faq-edit, .step-row { grid-template-columns: 1fr; } }
  `,
})
export class SettingsPage {
  private api = inject(Api);
  private ui = inject(Ui);
  private store = inject(CompanyStore);
  auth = inject(Auth);
  tab = signal('account');
  placeholders = ['first_name', 'amount', 'due_date', 'unit', 'balance', 'receipt', 'title', 'link', 'company'].map((x) => `{${x}}`).join(', ');
  company: any = { faq: [] };
  private cdr = inject(ChangeDetectorRef);
  schedules = signal<any[]>([]);
  templates = signal<any[]>([]);
  channelList = signal<any[]>([]);
  mpesa = signal<any>(null);
  running = signal(false);
  pwErr = signal('');
  pw: any = { current_password: '', new_password: '', confirm: '' };
  log = new ListState(this.api, 'notification-log/', { channel: '', status: '' });

  tabs() {
    const t = [['account', 'My account']];
    if (this.auth.can('manage_settings') || this.auth.me()?.portfolio_access) t.push(['company', 'Company profile']);
    if (this.auth.can('view_tenants')) t.push(['reminders', 'Rent reminders']);
    if (this.auth.can('manage_settings')) t.push(['templates', 'Message templates']);
    if (this.auth.can('view_audit')) t.push(['channels', 'Channels & notification log']);
    return t;
  }

  async setTab(t: string) {
    this.tab.set(t);
    try {
      if (t === 'company') {
        this.company = await this.api.getP('settings/company/');
        this.cdr.markForCheck(); // plain object bound with ngModel: tell zoneless change detection
      }
      if (t === 'reminders') this.schedules.set(await this.api.getP('reminder-schedules/'));
      if (t === 'templates') this.templates.set(await this.api.getP('notification-templates/'));
      if (t === 'channels') {
        const c = await this.api.getP('notification-channels/');
        this.channelList.set(Object.entries(c).map(([key, v]: any) => ({ key, ...v })));
        this.mpesa.set(await this.api.getP('payment-config/'));
        this.log.load(true);
      }
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
      this.auth.refresh();
    } catch (e) {
      const err = parseError(e);
      this.pwErr.set(err.fields['new_password'] || err.fields['current_password'] || err.message);
    }
  }

  async saveCompany() {
    try {
      const body = { ...this.company, faq: this.company.faq.filter((q: any) => q.question && q.answer) };
      this.company = await this.api.patchP('settings/company/', body);
      this.cdr.markForCheck();
      this.store.company.set(this.company);
      this.ui.toast('Company settings saved.');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async saveSchedule(s: any) {
    try {
      const body = { name: s.name, is_default: s.is_default, steps: s.steps.map(({ id, ...x }: any) => x) };
      if (s.id) await this.api.putP(`reminder-schedules/${s.id}/`, body);
      else await this.api.postP('reminder-schedules/', body);
      this.ui.toast('Schedule saved.');
      this.setTab('reminders');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  addSchedule() {
    this.schedules.update((l) => [...l, { id: null, name: 'New schedule', is_default: false, steps: [
      { offset_days: -3, kind: 'rent_upcoming', alert_management: false, custom_message: '' },
      { offset_days: 0, kind: 'rent_due', alert_management: false, custom_message: '' },
      { offset_days: 5, kind: 'rent_overdue', alert_management: true, custom_message: '' }] }]);
  }

  async saveTemplate(t: any) {
    try {
      await this.api.patchP(`notification-templates/${t.id}/`, { subject: t.subject, body: t.body, short_body: t.short_body, is_active: t.is_active });
      this.ui.toast('Template saved.');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async runJobs() {
    this.running.set(true);
    try {
      const r = await this.api.postP('system/run-jobs/');
      this.ui.toast(`Jobs done: ${r.rent_charges_created} charges, ${r.reminders_sent} reminders, ${r.reservations_expired} reservations expired, ${r.notifications_retried} retries.`, 'info', 8000);
      this.log.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    } finally {
      this.running.set(false);
    }
  }

  async retry(n: any) {
    await this.api.postP(`notification-log/${n.id}/retry/`);
    this.log.load();
  }
}
