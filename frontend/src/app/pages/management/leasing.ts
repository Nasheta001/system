import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe, today } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Loading, Modal, PageHeader, Pager } from "../../shared/ui";

@Component({
  imports: [FormsModule, DatePipe, KesPipe, Badge, Empty, Loading, Modal, PageHeader, Pager],
  template: `
    <app-page-header title="Applications & vacancies" subtitle="Viewing requests, rental applications, reservations and move-ins. An application never creates a tenancy by itself." />
    <div class="tabs">
      @for (t of tabs; track t[0]) { <button class="tab" [class.active]="tab() === t[0]" (click)="setTab(t[0])">{{ t[1] }}</button> }
    </div>
    <div class="card">
      <div class="toolbar">
        <select [(ngModel)]="property" (change)="reload()"><option value="">All properties</option>
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
        @if (tab() === 'applications') {
          <select [(ngModel)]="apps.filters['status']" (change)="apps.load(true)"><option value="">Any status</option>
            @for (s of ['pending','under_review','approved','rejected','withdrawn']; track s) { <option [value]="s">{{ s.replace('_', ' ') }}</option> }</select>
        }
        @if (tab() === 'viewings') {
          <select [(ngModel)]="views.filters['status']" (change)="views.load(true)"><option value="">Any status</option>
            @for (s of ['new','contacted','scheduled','completed','cancelled']; track s) { <option [value]="s">{{ s }}</option> }</select>
        }
        @if (tab() === 'reservations') {
          <select [(ngModel)]="res.filters['status']" (change)="res.load(true)"><option value="">Any status</option>
            @for (s of ['active','converted','expired','cancelled']; track s) { <option [value]="s">{{ s }}</option> }</select>
        }
      </div>

      @switch (tab()) {
        @case ('applications') {
          @if (apps.loading() && !apps.loaded()) { <app-loading /> }
          @else if (!apps.items().length) { <app-empty icon="clipboard" title="No applications" text="Applications submitted on the public website appear here." /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Applicant</th><th>Unit</th><th>Submitted</th><th>Status</th><th></th></tr></thead>
              <tbody>@for (a of apps.items(); track a.id) {
                <tr><td data-label="Applicant"><b>{{ a.full_name }}</b><span class="sub">{{ a.phone }} · {{ a.email }}</span><span class="sub mono">{{ a.reference }}</span></td>
                  <td data-label="Unit">{{ a.unit_label }} · {{ a.rent_amount | kes }}<span class="sub">{{ a.property_name }} · unit {{ a.unit_status }}</span></td>
                  <td data-label="Submitted">{{ a.created_at | date: 'd MMM yyyy' }}</td>
                  <td data-label="Status"><app-badge [value]="a.status" />@if (a.active_reservation) { <span class="sub">Reserved until {{ a.active_reservation.expires_at | date: 'd MMM HH:mm' }}</span> }</td>
                  <td class="actions"><button class="btn btn-sm" (click)="openApp(a)">Review</button>
                    @if (a.status === 'approved' && !a.active_reservation && a.unit_status === 'available') { <button class="btn btn-sm btn-primary" (click)="reserveApp(a)">Reserve unit</button> }</td></tr>
              }</tbody></table></div>
            <app-pager [count]="apps.count()" [page]="apps.page()" (pageChange)="apps.go($event)" />
          }
        }
        @case ('viewings') {
          @if (!views.items().length) { <app-empty icon="calendar" title="No viewing requests" /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Name</th><th>Property</th><th>Preferred</th><th>Status</th><th></th></tr></thead>
              <tbody>@for (v of views.items(); track v.id) {
                <tr><td data-label="Name"><b>{{ v.full_name }}</b><span class="sub">{{ v.phone }} {{ v.email }}</span>@if (v.message) { <span class="sub">“{{ v.message }}”</span> }</td>
                  <td data-label="Property">{{ v.property_name }}<span class="sub">{{ v.unit_label ? 'Unit ' + v.unit_label : 'Any unit' }}</span></td>
                  <td data-label="Preferred">{{ v.preferred_date ? (v.preferred_date | date: 'd MMM') : '—' }}@if (v.scheduled_for) { <span class="sub">Booked {{ v.scheduled_for | date: 'd MMM HH:mm' }}</span> }</td>
                  <td data-label="Status"><app-badge [value]="v.status" /></td>
                  <td class="actions"><button class="btn btn-sm" (click)="openViewing(v)">Update</button></td></tr>
              }</tbody></table></div>
            <app-pager [count]="views.count()" [page]="views.page()" (pageChange)="views.go($event)" />
          }
        }
        @case ('reservations') {
          @if (!res.items().length) { <app-empty icon="key" title="No reservations" text="Reserve a unit for an approved applicant, or directly for a walk-in client from the Vacancies tab." /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Holder</th><th>Unit</th><th>Expires</th><th>Status</th><th></th></tr></thead>
              <tbody>@for (r of res.items(); track r.id) {
                <tr><td data-label="Holder"><b>{{ r.holder_name }}</b><span class="sub">{{ r.holder_phone }} {{ r.holder_email }}</span>@if (r.application_reference) { <span class="sub mono">{{ r.application_reference }}</span> }</td>
                  <td data-label="Unit">{{ r.unit_label }}<span class="sub">{{ r.property_name }}</span></td>
                  <td data-label="Expires">{{ r.expires_at | date: 'd MMM yyyy, HH:mm' }}</td>
                  <td data-label="Status"><app-badge [value]="r.status" /></td>
                  <td class="actions">@if (r.status === 'active') {
                    <button class="btn btn-sm btn-primary" (click)="openConvert(r)">Move in</button>
                    <button class="btn btn-sm btn-ghost" (click)="cancelRes(r)">Cancel</button> }
                    @if (r.tenancy_id) { <span class="muted small">Tenancy created</span> }</td></tr>
              }</tbody></table></div>
          }
        }
        @case ('vacancies') {
          @if (!vacancies().length) { <app-empty icon="door" title="No vacant units" text="Every unit is occupied, reserved or unavailable." /> }
          @else {
            <div class="table-wrap"><table class="table responsive">
              <thead><tr><th>Unit</th><th>Property</th><th class="num">Rent</th><th>On website</th><th></th></tr></thead>
              <tbody>@for (u of vacancies(); track u.id) {
                <tr><td data-label="Unit"><b>{{ u.label }}</b><span class="sub">{{ u.unit_type_name }}</span></td><td data-label="Property">{{ u.property_name }}</td>
                  <td data-label="Rent" class="num">{{ u.rent_amount | kes }}</td><td data-label="On website">{{ u.is_listed ? 'Listed' : 'Hidden' }}</td>
                  <td class="actions"><button class="btn btn-sm" (click)="openWalkIn(u)">Reserve</button>
                    <button class="btn btn-sm btn-primary" (click)="router.navigate(['/management/tenants/new'], { queryParams: { property: u.property, unit: u.id } })">Let directly</button></td></tr>
              }</tbody></table></div>
          }
        }
      }
    </div>

    <app-modal [(open)]="appOpen" [title]="'Application ' + (app?.reference || '')" [wide]="true">
      @if (app) {
        <div class="grid-2">
          <dl class="kv">
            <dt>Applicant</dt><dd>{{ app.full_name }}</dd><dt>Phone</dt><dd><a [href]="'tel:' + app.phone">{{ app.phone }}</a></dd>
            <dt>Email</dt><dd>{{ app.email }}</dd><dt>Occupation</dt><dd>{{ app.occupation || '—' }} {{ app.employer ? '· ' + app.employer : '' }}</dd>
            <dt>Household</dt><dd>{{ app.household_size }}</dd><dt>Move-in</dt><dd>{{ app.desired_move_in ? (app.desired_move_in | date: 'mediumDate') : '—' }}</dd>
            <dt>Unit</dt><dd>{{ app.unit_label }}, {{ app.property_name }} ({{ app.rent_amount | kes }})</dd>
            <dt>Message</dt><dd>{{ app.message || '—' }}</dd>
          </dl>
          <form (ngSubmit)="saveApp()">
            @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
            <label class="field"><span>Status</span><select name="s" [(ngModel)]="appForm.status">
              @for (s of ['pending','under_review','approved','rejected','withdrawn']; track s) { <option [value]="s">{{ s.replace('_', ' ') }}</option> }</select></label>
            <label class="field"><span>Message to applicant (shown on status lookup & emailed)</span><textarea name="m" rows="3" [(ngModel)]="appForm.applicant_message"></textarea></label>
            <label class="field"><span>Internal notes</span><textarea name="n" rows="3" [(ngModel)]="appForm.internal_notes"></textarea></label>
            <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
          </form>
        </div>
      }
    </app-modal>

    <app-modal [(open)]="viewOpen" title="Update viewing request">
      <form (ngSubmit)="saveViewing()">
        <label class="field"><span>Status</span><select name="s" [(ngModel)]="viewForm.status">@for (s of ['new','contacted','scheduled','completed','cancelled']; track s) { <option [value]="s">{{ s }}</option> }</select></label>
        <label class="field"><span>Scheduled for</span><input type="datetime-local" name="sf" [(ngModel)]="viewForm.scheduled_for"></label>
        <label class="field"><span>Staff notes</span><textarea name="n" rows="3" [(ngModel)]="viewForm.staff_notes"></textarea></label>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="walkOpen" title="Reserve unit">
      <form (ngSubmit)="saveWalkIn()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <p class="muted">{{ walk.unitLabel }}</p>
        <label class="field"><span>Holder name *</span><input name="n" [(ngModel)]="walk.holder_name"></label>
        <div class="form-grid">
          <label class="field"><span>Phone *</span><input name="p" [(ngModel)]="walk.holder_phone"></label>
          <label class="field"><span>Email</span><input name="e" type="email" [(ngModel)]="walk.holder_email"></label>
        </div>
        <label class="field"><span>Reservation expires</span><input type="datetime-local" name="x" [(ngModel)]="walk.expires_at"><small>Leave blank for the company default. Expired reservations release the unit automatically.</small></label>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !walk.holder_name || !walk.holder_phone">Reserve</button></div>
      </form>
    </app-modal>

    <app-modal [(open)]="convOpen" title="Move-in: convert reservation to tenancy">
      <form (ngSubmit)="saveConvert()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <p class="muted">{{ conv.unit_label }} for {{ conv.holder_name }}</p>
        <div class="form-grid">
          <label class="field"><span>First name</span><input name="fn" [(ngModel)]="conv.first_name"></label>
          <label class="field"><span>Last name</span><input name="ln" [(ngModel)]="conv.last_name"></label>
          <label class="field"><span>ID / passport</span><input name="id" [(ngModel)]="conv.id_number"></label>
          <label class="field"><span>Start date *</span><input type="date" name="sd" [(ngModel)]="conv.start_date"></label>
          <label class="field"><span>Expected end</span><input type="date" name="ed" [(ngModel)]="conv.expected_end_date"></label>
          <label class="field"><span>Monthly rent (blank = unit rent)</span><input type="number" name="mr" [(ngModel)]="conv.monthly_rent"></label>
        </div>
        <label class="field"><span>Move-in inspection notes</span><textarea rows="2" name="in" [(ngModel)]="conv.move_in_inspection_notes"></textarea></label>
        <label class="check"><input type="checkbox" name="pa" [(ngModel)]="conv.create_portal_account" [disabled]="!conv.holder_email"> Create tenant portal account and send invitation {{ conv.holder_email ? '(' + conv.holder_email + ')' : '(no email on file)' }}</label>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !conv.start_date">Create tenancy</button></div>
      </form>
    </app-modal>`,
})
export class LeasingPage {
  private api = inject(Api);
  private ui = inject(Ui);
  router = inject(Router);
  auth = inject(Auth);
  tabs = [['applications', 'Applications'], ['viewings', 'Viewing requests'], ['reservations', 'Reservations'], ['vacancies', 'Vacancies']];
  tab = signal('applications');
  property = '';
  apps = new ListState(this.api, 'applications/', { status: '' });
  views = new ListState(this.api, 'viewing-requests/', { status: '' });
  res = new ListState(this.api, 'reservations/', { status: 'active' });
  vacancies = signal<any[]>([]);
  busy = signal(false);
  formErr = signal('');
  appOpen = signal(false); viewOpen = signal(false); walkOpen = signal(false); convOpen = signal(false);
  app: any = null; appForm: any = {}; viewForm: any = {}; walk: any = {}; conv: any = {};

  constructor() {
    this.setTab(inject(ActivatedRoute).snapshot.queryParams['tab'] || 'applications');
  }

  setTab(t: string) {
    this.tab.set(t);
    this.reload();
  }

  reload() {
    for (const l of [this.apps, this.views, this.res]) l.filters['property'] = this.property;
    const t = this.tab();
    if (t === 'applications') this.apps.load(true);
    if (t === 'viewings') this.views.load(true);
    if (t === 'reservations') this.res.load(true);
    if (t === 'vacancies') this.api.all('units/', { status: 'available', property: this.property }).then((r) => this.vacancies.set(r));
  }

  private async run(fn: () => Promise<any>, msg: string, close: () => void) {
    this.busy.set(true);
    this.formErr.set('');
    try {
      const r = await fn();
      close();
      this.ui.toast(msg);
      this.reload();
      return r;
    } catch (e) {
      this.formErr.set(parseError(e).message);
      this.ui.error(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  openApp(a: any) {
    this.formErr.set('');
    this.app = a;
    this.appForm = { status: a.status, applicant_message: a.applicant_message, internal_notes: a.internal_notes };
    this.appOpen.set(true);
  }
  saveApp() {
    return this.run(() => this.api.postP(`applications/${this.app.id}/set-status/`, this.appForm), 'Application updated. The applicant has been notified of status changes.', () => this.appOpen.set(false));
  }
  async reserveApp(a: any) {
    if (!(await this.ui.confirm({ title: 'Reserve this unit?', message: `${a.unit_label} will be held for ${a.full_name} and hidden from other applicants until the reservation expires.`, confirmText: 'Reserve' }))) return;
    await this.run(() => this.api.postP(`applications/${a.id}/reserve/`, {}), 'Unit reserved.', () => {});
  }

  openViewing(v: any) {
    this.viewForm = { id: v.id, status: v.status, scheduled_for: v.scheduled_for ? v.scheduled_for.slice(0, 16) : '', staff_notes: v.staff_notes };
    this.viewOpen.set(true);
  }
  saveViewing() {
    const body = { ...this.viewForm, scheduled_for: this.viewForm.scheduled_for ? new Date(this.viewForm.scheduled_for).toISOString() : null };
    return this.run(() => this.api.patchP(`viewing-requests/${this.viewForm.id}/`, body), 'Viewing updated.', () => this.viewOpen.set(false));
  }

  openWalkIn(u: any) {
    this.formErr.set('');
    this.walk = { unit: u.id, unitLabel: `${u.label}, ${u.property_name}`, holder_name: '', holder_phone: '', holder_email: '', expires_at: '' };
    this.walkOpen.set(true);
  }
  saveWalkIn() {
    const { unitLabel, ...body } = this.walk;
    if (body.expires_at) body.expires_at = new Date(body.expires_at).toISOString(); else delete body.expires_at;
    return this.run(() => this.api.postP('reservations/', body), 'Unit reserved.', () => this.walkOpen.set(false));
  }

  async cancelRes(r: any) {
    const reason = await this.ui.confirm({ title: 'Cancel reservation?', message: `${r.unit_label} will become available again.`, reasonLabel: 'Reason', danger: true, confirmText: 'Cancel reservation' });
    if (reason) await this.run(() => this.api.postP(`reservations/${r.id}/cancel/`, { reason }), 'Reservation cancelled.', () => {});
  }

  openConvert(r: any) {
    this.formErr.set('');
    const [first, ...rest] = r.holder_name.split(' ');
    this.conv = { id: r.id, unit_label: `${r.unit_label}, ${r.property_name}`, holder_name: r.holder_name, holder_email: r.holder_email,
      first_name: first, last_name: rest.join(' '), id_number: '', start_date: today(), expected_end_date: null, monthly_rent: null,
      move_in_inspection_notes: '', create_portal_account: !!r.holder_email };
    this.convOpen.set(true);
  }
  async saveConvert() {
    const { id, unit_label, holder_name, holder_email, ...body } = this.conv;
    if (!body.monthly_rent) delete body.monthly_rent;
    if (!body.expected_end_date) body.expected_end_date = null;
    const r = await this.run(() => this.api.postP(`reservations/${id}/convert/`, body), 'Tenancy created.', () => this.convOpen.set(false));
    if (r?.tenant_id) this.router.navigate(['/management/tenants', r.tenant_id]);
  }
}
