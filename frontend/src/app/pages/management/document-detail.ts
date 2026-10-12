import { DatePipe } from '@angular/common';
import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Icon, Loading, Modal, PageHeader } from '../../shared/ui';
import { DOC_CATEGORIES } from './documents';

@Component({
  imports: [FormsModule, DatePipe, LabelPipe, Badge, Icon, Loading, Modal, PageHeader],
  template: `
    @if (!d()) { <app-loading /> } @else {
      <app-page-header [title]="d().title" [subtitle]="d().category_label + (d().property_name ? ' · ' + d().property_name : ' · Company-wide') + (d().tenant_name ? ' · ' + d().tenant_name : '')" back="/management/documents" backLabel="Documents">
        <button class="btn" (click)="api.download('documents/' + d().id + '/download/')"><app-icon name="download" /> Download</button>
        @if (auth.can('manage_documents')) {
          @if (d().status === 'draft') { <button class="btn btn-primary" (click)="approve()"><app-icon name="check" /> Approve & publish</button> }
          <label class="btn"><app-icon name="upload" /> New version<input type="file" hidden accept=".pdf,.docx,.doc,.jpg,.jpeg,.png" (change)="newVersion($event)"></label>
          @if (d().status !== 'archived') { <button class="btn btn-ghost" (click)="archive()"><app-icon name="archive" /> Archive</button> }
          @if (d().status === 'draft') { <button class="btn btn-ghost" (click)="remove()">Delete draft</button> }
        }
      </app-page-header>
      <div class="row mb"><app-badge [value]="d().status" /><app-badge [value]="d().workflow" />@if (d().is_library) { <app-badge value="info" text="Library" /> }</div>
      @if (d().status === 'draft') { <div class="alert alert-warn">This document is a draft and is not visible to tenants until approved.</div> }

      <div class="split">
        <div class="stack">
          @if (d().workflow !== 'info') {
            <div class="card">
              <div class="card-head"><h2>{{ d().workflow === 'signature' ? 'Signatures' : 'Acknowledgements' }} – version {{ acks()?.version }}</h2>
                <span class="muted small">{{ doneCount() }} / {{ acks()?.rows?.length ?? 0 }} complete</span></div>
              @if (!acks()?.rows?.length) { <p class="card-body muted">No tenants are currently assigned this document.</p> }
              <div class="table-wrap"><table class="table responsive">
                <tbody>@for (r of acks()?.rows ?? []; track r.tenant_id) {
                  <tr><td data-label="Tenant">{{ r.tenant }}</td>
                    <td data-label="Status">@if (d().workflow === 'signature') { <app-badge [value]="r.signature_status || 'pending'" /> }
                      @else if (r.acknowledged_at) { <app-badge value="done" [text]="'Acknowledged ' + (r.acknowledged_at | date: 'd MMM')" /> } @else { <app-badge value="pending" text="Not yet" /> }</td></tr>
                }</tbody></table></div>
            </div>
          }
          <div class="card">
            <div class="card-head"><h2>Version history</h2></div>
            <ul class="list">@for (v of d().versions; track v.id) {
              <li class="row-between"><span><b>v{{ v.version }}</b> {{ v.original_name }} <span class="muted small">· {{ v.uploaded_by_name }} · {{ v.uploaded_at | date: 'd MMM yyyy HH:mm' }}</span>
                @if (v.notes) { <span class="sub muted small" style="display:block">{{ v.notes }}</span> }</span>
                <span class="row">@if (v.id === d().current_version) { <app-badge value="active" text="Current" /> }
                  <button class="btn btn-sm btn-ghost" (click)="api.download('documents/' + d().id + '/download/', { version: v.id })">Download</button></span></li>
            }</ul>
          </div>
        </div>
        <aside class="stack">
          <div class="card">
            <div class="card-head"><h3>Who can see it</h3>@if (auth.can('manage_documents')) { <button class="btn btn-sm" (click)="openAssign()"><app-icon name="plus" [size]="14" /> Assign</button> }</div>
            <ul class="list">@for (a of d().assignments; track a.id) {
              <li class="row-between"><span>{{ a.target }} <span class="muted small">{{ a.scope | label }}</span></span>
                @if (auth.can('manage_documents')) { <button class="btn btn-sm btn-ghost" (click)="unassign(a)">Remove</button> }</li>
            } @empty { <li class="muted small">Not assigned. Only staff can see it.</li> }</ul>
          </div>
          @if (d().description) { <div class="card card-pad"><h3>Description</h3><p class="small">{{ d().description }}</p></div> }
          @if (d().workflow === 'signature') {
            <div class="alert alert-info small">Tenants download the document, sign it by hand (or with their own legally recognised e-signature tool) and upload the signed copy. Review each copy on the Signatures tab before relying on it.</div>
          }
        </aside>
      </div>

      <app-modal [(open)]="assignOpen" title="Assign document">
        <form (ngSubmit)="assign()">
          @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
          <label class="field"><span>Audience</span><select name="s" [(ngModel)]="asg.scope">
            @if (auth.me()?.portfolio_access) { <option value="all_tenants">All active tenants</option> }
            <option value="property">Tenants of a property</option><option value="building">Tenants of a building / block</option><option value="tenant">A specific tenant</option></select></label>
          @switch (asg.scope) {
            @case ('property') { <label class="field"><span>Property</span><select name="p" [(ngModel)]="asg.property">@for (p of auth.me()?.assigned_properties; track p.id) { <option [ngValue]="p.id">{{ p.name }}</option> }</select></label> }
            @case ('building') { <label class="field"><span>Building</span><select name="b" [(ngModel)]="asg.building">@for (b of buildings(); track b.id) { <option [ngValue]="b.id">{{ b.label }}</option> }</select></label> }
            @case ('tenant') { <label class="field"><span>Tenant</span><select name="t" [(ngModel)]="asg.tenant">@for (t of tenants(); track t.id) { <option [ngValue]="t.id">{{ t.full_name }} – {{ t.current_tenancy?.unit_label }}</option> }</select></label> }
          }
          <label class="field"><span>Due date (optional)</span><input type="date" name="dd" [(ngModel)]="asg.due_date"></label>
          @if (d().status === 'approved' && d().workflow !== 'info') { <p class="muted small">Assigned tenants will be notified that action is required.</p> }
          <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Assign</button></div>
        </form>
      </app-modal>
    }`,
})
export class DocumentDetailPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  private router = inject(Router);
  id = input.required<string>();
  d = signal<any>(null);
  acks = signal<any>(null);
  buildings = signal<any[]>([]);
  tenants = signal<any[]>([]);
  assignOpen = signal(false);
  busy = signal(false);
  formErr = signal('');
  asg: any = {};
  categories = DOC_CATEGORIES;

  ngOnInit() {
    this.load();
  }

  async load() {
    const d = await this.api.getP(`documents/${this.id()}/`);
    this.d.set(d);
    if (d.workflow !== 'info' && d.current_version) this.acks.set(await this.api.getP(`documents/${d.id}/acknowledgements/`));
  }

  doneCount() {
    const rows = this.acks()?.rows ?? [];
    return rows.filter((r: any) => (this.d().workflow === 'signature' ? r.signature_status === 'verified' : r.acknowledged_at)).length;
  }

  private async act(fn: () => Promise<any>, msg: string) {
    try {
      await fn();
      this.ui.toast(msg);
      this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async approve() {
    const msg = this.d().workflow === 'info' ? 'It will become visible to its assigned audience.' : 'Assigned tenants will be notified that action is required.';
    if (await this.ui.confirm({ title: 'Approve this version?', message: msg, confirmText: 'Approve' }))
      this.act(() => this.api.postP(`documents/${this.id()}/approve/`), 'Document approved.');
  }

  async archive() {
    if (await this.ui.confirm({ title: 'Archive document?', message: 'Tenants will no longer see it. Versions and acknowledgements are kept.', confirmText: 'Archive', danger: true }))
      this.act(() => this.api.postP(`documents/${this.id()}/archive/`), 'Archived.');
  }

  async remove() {
    if (!(await this.ui.confirm({ title: 'Delete draft?', message: 'The draft and its files will be removed.', danger: true, confirmText: 'Delete' }))) return;
    try {
      await this.api.deleteP(`documents/${this.id()}/`);
      this.router.navigate(['/management/documents']);
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async newVersion(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (!f) return;
    const notes = await this.ui.confirm({ title: 'Upload new version', message: `${f.name} will replace the current version. It must be approved again; tenants will need to re-acknowledge.`, reasonLabel: 'What changed?', confirmText: 'Upload' });
    if (!notes) return;
    this.act(() => this.api.postP(`documents/${this.id()}/versions/`, toFormData({ file: f, notes })), 'New version uploaded (draft).');
  }

  async openAssign() {
    this.formErr.set('');
    this.asg = { scope: 'property', property: this.d().property ?? this.auth.me()?.assigned_properties[0]?.id, building: null, tenant: null, due_date: '' };
    this.assignOpen.set(true);
    const props = new Map((this.auth.me()?.assigned_properties ?? []).map((p) => [p.id, p.name]));
    const [b, t] = await Promise.all([this.api.all('buildings/'), this.api.all('tenants/', { status: 'active' })]);
    this.buildings.set(b.map((x: any) => ({ ...x, label: `${props.get(x.property) ?? ''} – ${x.name}` })));
    this.tenants.set(t);
  }

  async assign() {
    this.busy.set(true);
    this.formErr.set('');
    const body: any = { scope: this.asg.scope, due_date: this.asg.due_date || null };
    if (body.scope === 'property') body.property = this.asg.property;
    if (body.scope === 'building') body.building = this.asg.building;
    if (body.scope === 'tenant') body.tenant = this.asg.tenant;
    try {
      await this.api.postP(`documents/${this.id()}/assign/`, body);
      this.assignOpen.set(false);
      this.ui.toast('Assigned.');
      this.load();
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  unassign(a: any) {
    this.act(() => this.api.postP(`documents/${this.id()}/unassign/`, { assignment: a.id }), 'Removed.');
  }
}
