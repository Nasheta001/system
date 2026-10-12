import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, parseError } from '../../core/api.service';
import { Auth, ROLE_LABELS } from '../../core/auth.service';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal, PageHeader } from '../../shared/ui';

@Component({
  imports: [FormsModule, DatePipe, Badge, Empty, Icon, Loading, Modal, PageHeader],
  template: `
    <app-page-header title="Staff & access" subtitle="Invite staff, assign properties and control roles. Caretakers and managers only see their assigned properties.">
      <button class="btn btn-primary" (click)="open(null)"><app-icon name="plus" /> Invite staff member</button>
    </app-page-header>
    @if (devLink()) {
      <div class="alert alert-warn">
        <b>Development only:</b> email delivery is not configured, so share this single-use link with the invitee yourself.
        It is never shown when the server runs with DEBUG off.
        <div class="mono small dev-link">{{ devLink() }}</div>
        <button class="btn btn-sm" (click)="devLink.set('')">Hide</button>
      </div>
    }
    @if (invites().length) {
      <div class="card mb">
        <div class="card-head"><h2>Pending invitations</h2><span class="muted small">Single-use links. Expired or revoked links stop working.</span></div>
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Invitee</th><th>Role</th><th>Expires</th><th>Status</th><th></th></tr></thead>
          <tbody>@for (i of invites(); track i.id) {
            <tr><td data-label="Invitee"><b>{{ i.first_name }} {{ i.last_name }}</b><span class="sub">{{ i.email }}</span>
                @if (i.property_names.length) { <span class="sub">{{ i.property_names.join(', ') }}</span> }</td>
              <td data-label="Role">{{ i.role_label }}</td>
              <td data-label="Expires">{{ i.expires_at | date: 'd MMM yyyy, HH:mm' }}</td>
              <td data-label="Status"><app-badge [value]="i.status" /></td>
              <td class="actions"><button class="btn btn-sm btn-ghost" (click)="resend(i)">Resend</button>
                <button class="btn btn-sm btn-ghost" (click)="revoke(i)">Revoke</button></td></tr>
          }</tbody></table></div>
      </div>
    }
    <div class="card">
      <div class="toolbar">
        <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search staff…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
        <select [(ngModel)]="list.filters['role']" (change)="list.load(true)"><option value="">All roles</option>@for (r of roles; track r[0]) { <option [value]="r[0]">{{ r[1] }}</option> }</select>
        <select [(ngModel)]="list.filters['is_active']" (change)="list.load(true)"><option value="">Active & inactive</option><option value="true">Active</option><option value="false">Deactivated</option></select>
      </div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) { <app-empty icon="users" title="No staff found" /> }
      @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Name</th><th>Role</th><th>Properties</th><th>Last sign-in</th><th>Status</th><th></th></tr></thead>
          <tbody>@for (s of list.items(); track s.id) {
            <tr><td data-label="Name"><b>{{ s.full_name || s.email }}</b><span class="sub">{{ s.email }} · {{ s.phone }}</span>@if (s.job_title) { <span class="sub">{{ s.job_title }}</span> }</td>
              <td data-label="Role">{{ roleLabel(s.role) }}</td>
              <td data-label="Properties">@if (s.role === 'admin' || s.role === 'landlord') { <span class="muted">Whole portfolio</span> }
                @else { @for (p of s.assigned_properties; track p.id) { <span class="sub" style="display:block;color:inherit">{{ p.name }}</span> } @empty { <span class="text-amber small">None assigned</span> } }</td>
              <td data-label="Last sign-in">{{ s.last_login ? (s.last_login | date: 'd MMM yyyy, HH:mm') : 'Never' }}</td>
              <td data-label="Status"><app-badge [value]="s.is_active ? 'active' : 'inactive'" /></td>
              <td class="actions"><button class="btn btn-sm btn-ghost" (click)="open(s)">Edit</button>
                <button class="btn btn-sm btn-ghost" (click)="sendReset(s)">Password link</button>
                @if (s.id !== auth.me()?.id) { <button class="btn btn-sm btn-ghost" (click)="toggleActive(s)">{{ s.is_active ? 'Deactivate' : 'Activate' }}</button> }</td></tr>
          }</tbody></table></div>
      }
    </div>

    <app-modal [(open)]="editOpen" [title]="form.id ? 'Edit staff member' : 'Invite staff member'" [wide]="true">
      <form (ngSubmit)="save()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>First name *</span><input name="fn" [(ngModel)]="form.first_name"></label>
          <label class="field"><span>Last name</span><input name="ln" [(ngModel)]="form.last_name"></label>
          <label class="field"><span>Email *</span><input name="e" type="email" [(ngModel)]="form.email"></label>
          <label class="field"><span>Phone</span><input name="p" [(ngModel)]="form.phone"></label>
          <label class="field"><span>Role *</span><select name="r" [(ngModel)]="form.role">@for (r of roles; track r[0]) { <option [value]="r[0]">{{ r[1] }}</option> }</select></label>
          <label class="field"><span>Job title</span><input name="j" [(ngModel)]="form.job_title"></label>
        </div>
        <div class="alert alert-info small">{{ roleHelp[form.role] }}</div>
        @if (form.role === 'manager' || form.role === 'caretaker') {
          <div class="field"><span class="field-label">Assigned properties</span>
            <div class="chips">@for (p of auth.me()?.assigned_properties; track p.id) {
              <span class="chip" [class.selected]="form.property_ids.includes(p.id)" (click)="toggleProp(p.id)">{{ p.name }}</span> }</div></div>
        }
        @if (!form.id) { <p class="muted small">We email a single-use invitation link (valid for 3 days). Their account is created only when they accept it and choose a password.</p> }
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !form.email || !form.first_name">{{ form.id ? 'Save' : 'Send invitation' }}</button></div>
      </form>
    </app-modal>`,
  styles: `.dev-link { word-break: break-all; background: #fff; padding: 6px 8px; border-radius: 6px; margin: 6px 0; }`,
})
export class StaffPage {
  private api = inject(Api);
  private ui = inject(Ui);
  auth = inject(Auth);
  list = new ListState(this.api, 'staff/', { search: '', role: '', is_active: '' });
  roles = [['admin', 'Company administrator'], ['landlord', 'Landlord / owner'], ['manager', 'Property manager'], ['caretaker', 'Caretaker']];
  roleHelp: Record<string, string> = {
    admin: 'Full access, including staff accounts, settings and the audit log.',
    landlord: 'Whole portfolio: properties, tenants, payments, reports and settings. Cannot manage staff accounts.',
    manager: 'Manages tenants, rent, notices, documents, applications and maintenance for assigned properties only.',
    caretaker: 'Sees assigned properties, tenant contacts and maintenance. No financial data.',
  };
  editOpen = signal(false);
  invites = signal<any[]>([]);
  devLink = signal('');
  busy = signal(false);
  formErr = signal('');
  form: any = {};

  constructor() {
    this.list.load();
    this.loadInvites();
  }

  async loadInvites() {
    this.invites.set(await this.api.getP<any[]>('staff-invitations/', { open: 'true' }));
  }

  async resend(i: any) {
    try {
      const r = await this.api.postP(`staff-invitations/${i.id}/resend/`);
      this.devLink.set(r.dev_invite_link || '');
      this.ui.toast('New invitation sent. The previous link no longer works.');
      this.loadInvites();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async revoke(i: any) {
    if (!(await this.ui.confirm({ title: `Revoke invitation for ${i.email}?`, message: 'The link stops working immediately.', danger: true, confirmText: 'Revoke' }))) return;
    try {
      await this.api.postP(`staff-invitations/${i.id}/revoke/`);
      this.loadInvites();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  roleLabel(r: string) {
    return ROLE_LABELS[r] ?? r;
  }

  open(s: any) {
    this.formErr.set('');
    this.form = s
      ? { ...s, property_ids: s.assigned_properties.map((p: any) => p.id) }
      : { first_name: '', last_name: '', email: '', phone: '', role: 'manager', job_title: '', property_ids: [] };
    this.editOpen.set(true);
  }

  toggleProp(id: number) {
    const ids: number[] = this.form.property_ids;
    this.form.property_ids = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
  }

  async save() {
    this.busy.set(true);
    this.formErr.set('');
    const body = { first_name: this.form.first_name, last_name: this.form.last_name, email: this.form.email, phone: this.form.phone,
      role: this.form.role, job_title: this.form.job_title, property_ids: this.form.property_ids };
    try {
      if (this.form.id) {
        await this.api.patchP(`staff/${this.form.id}/`, body);
        this.list.load();
      } else {
        const r = await this.api.postP('staff-invitations/', body);
        this.devLink.set(r.dev_invite_link || '');
        this.loadInvites();
      }
      this.editOpen.set(false);
      this.ui.toast(this.form.id ? 'Staff member updated.' : 'Invitation sent.');
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async toggleActive(s: any) {
    const action = s.is_active ? 'deactivate' : 'activate';
    if (!(await this.ui.confirm({ title: `${s.is_active ? 'Deactivate' : 'Activate'} ${s.full_name}?`, message: s.is_active ? 'All their sessions end immediately and they cannot sign in. Their history is kept.' : 'They will be able to sign in again.', danger: s.is_active, confirmText: s.is_active ? 'Deactivate' : 'Activate' }))) return;
    try {
      await this.api.postP(`staff/${s.id}/${action}/`);
      this.list.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async sendReset(s: any) {
    const r = await this.api.postP(`staff/${s.id}/send-reset/`);
    this.ui.toast(r.detail);
  }
}
