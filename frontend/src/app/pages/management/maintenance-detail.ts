import { DatePipe } from '@angular/common';
import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Icon, Loading, PageHeader } from '../../shared/ui';
import { MR_STATUSES } from './maintenance';

@Component({
  imports: [FormsModule, RouterLink, DatePipe, LabelPipe, Badge, Icon, Loading, PageHeader],
  template: `
    @if (!r()) { <app-loading /> } @else {
      <app-page-header [title]="r().title" [subtitle]="r().reference + ' · ' + (r().unit_label || 'Common area') + ', ' + r().property_name" back="/management/maintenance" backLabel="Maintenance" />
      <div class="row mb"><app-badge [value]="r().status" /><app-badge [value]="r().urgency" /><span class="muted small">{{ r().category | label }}</span></div>
      <div class="split">
        <div class="stack">
          <div class="card card-pad">
            <h3>Description</h3>
            <p style="white-space:pre-line">{{ r().description }}</p>
            @if (r().attachments.length) {
              <h3 class="mt">Attachments</h3>
              @for (a of r().attachments; track a.id) {
                <div><button class="btn-link" (click)="api.download('maintenance/' + r().id + '/attachments/' + a.id + '/')"><app-icon name="file" [size]="15" /> {{ a.original_name }}</button>
                  @if (a.is_internal) { <span class="muted small">(internal)</span> }</div>
              }
            }
            @if (canManage()) { <label class="btn btn-sm mt"><app-icon name="upload" [size]="14" /> Add photo / file<input type="file" hidden accept=".jpg,.jpeg,.png,.pdf" (change)="attach($event)"></label> }
          </div>

          <div class="card">
            <div class="card-head"><h2>Activity</h2><span class="muted small"><span class="legend"></span> Internal notes are never shown to the tenant</span></div>
            <div class="card-body">
              <ul class="timeline">
                <li><div><b>Request submitted</b> by {{ r().tenant_name || 'staff' }}</div><div class="meta">{{ r().created_at | date: 'd MMM yyyy, HH:mm' }}</div></li>
                @for (u of r().updates; track u.id) {
                  <li [class.internal]="u.is_internal">
                    <div>@if (u.status_to && u.status_to !== u.status_from) { <b>{{ u.status_from | label }} → {{ u.status_to | label }}</b> }
                      @if (u.is_internal) { <span class="badge badge-amber">Internal</span> }</div>
                    @if (u.message) { <div style="white-space:pre-line">{{ u.message }}</div> }
                    <div class="meta">{{ u.author_name }} · {{ u.created_at | date: 'd MMM yyyy, HH:mm' }}</div>
                  </li>
                }
              </ul>
              @if (canManage()) {
                <form (ngSubmit)="addNote()" class="mt">
                  <label class="field"><span>Add a note</span><textarea name="n" rows="2" [(ngModel)]="note.message"></textarea></label>
                  <div class="row-between"><label class="check" style="margin:0"><input type="checkbox" name="i" [(ngModel)]="note.is_internal"> Internal only (hidden from tenant)</label>
                    <button class="btn btn-sm" [disabled]="!note.message">Add note</button></div>
                </form>
              }
            </div>
          </div>
        </div>
        <aside class="stack">
          @if (canManage()) {
            <form class="card card-pad" (ngSubmit)="changeStatus()">
              <h3>Update status</h3>
              <label class="field"><span>Status</span><select name="s" [(ngModel)]="st.status">@for (s of statuses; track s) { <option [value]="s">{{ s | label }}</option> }</select></label>
              <label class="field"><span>Message</span><textarea name="m" rows="2" [(ngModel)]="st.message" placeholder="e.g. Plumber will visit tomorrow at 10am"></textarea></label>
              @if (st.status === 'completed' || st.status === 'closed') {
                <label class="field"><span>Resolution notes (shown to tenant)</span><textarea name="rn" rows="2" [(ngModel)]="st.resolution_notes"></textarea></label>
              }
              <label class="check"><input type="checkbox" name="i" [(ngModel)]="st.is_internal"> Internal update – do not notify tenant</label>
              <button class="btn btn-primary btn-block" [disabled]="busy()">Save update</button>
            </form>
            <div class="card card-pad">
              <h3>Assignment & priority</h3>
              <label class="field"><span>Assigned to</span><select [(ngModel)]="assign.assigned_to" (ngModelChange)="saveAssign()"><option [ngValue]="null">— Unassigned —</option>
                @for (s of staff(); track s.id) { <option [ngValue]="s.id">{{ s.full_name }} ({{ s.role }})</option> }</select></label>
              <label class="field"><span>Urgency</span><select [(ngModel)]="assign.urgency" (ngModelChange)="saveAssign()"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="emergency">Emergency</option></select></label>
            </div>
          }
          <div class="card card-pad">
            <dl class="kv">
              <dt>Tenant</dt><dd>@if (r().tenant) { <a [routerLink]="['/management/tenants', r().tenant]">{{ r().tenant_name }}</a><br><a [href]="'tel:' + r().tenant_phone">{{ r().tenant_phone }}</a> } @else { — }</dd>
              <dt>Assigned</dt><dd>{{ r().assigned_to_name || '—' }}</dd>
              <dt>Completed</dt><dd>{{ r().completed_at ? (r().completed_at | date: 'medium') : '—' }}</dd>
              @if (r().resolution_notes) { <dt>Resolution</dt><dd>{{ r().resolution_notes }}</dd> }
            </dl>
          </div>
        </aside>
      </div>
    }`,
  styles: `.legend { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); margin-right: 4px; }`,
})
export class MaintenanceDetailPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  id = input.required<string>();
  r = signal<any>(null);
  staff = signal<any[]>([]);
  busy = signal(false);
  statuses = MR_STATUSES;
  st: any = {};
  note: any = { message: '', is_internal: true };
  assign: any = {};

  canManage() {
    return this.auth.can('manage_maintenance');
  }

  async ngOnInit() {
    await this.load();
    if (this.canManage()) this.staff.set(await this.api.getP('staff-options/', { property: this.r().property }));
  }

  async load() {
    const r = await this.api.getP(`maintenance/${this.id()}/`);
    this.r.set(r);
    this.st = { status: r.status, message: '', is_internal: false, resolution_notes: r.resolution_notes };
    this.assign = { assigned_to: r.assigned_to, urgency: r.urgency };
  }

  private async run(fn: () => Promise<any>, msg: string) {
    this.busy.set(true);
    try {
      this.r.set(await fn());
      this.ui.toast(msg);
      await this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
      await this.load();
    } finally {
      this.busy.set(false);
    }
  }

  changeStatus() {
    return this.run(() => this.api.postP(`maintenance/${this.id()}/status/`, this.st), this.st.is_internal ? 'Updated.' : 'Updated – tenant notified.');
  }
  async addNote() {
    await this.run(() => this.api.postP(`maintenance/${this.id()}/note/`, this.note), 'Note added.');
    this.note = { message: '', is_internal: true };
  }
  saveAssign() {
    return this.run(() => this.api.patchP(`maintenance/${this.id()}/`, this.assign), 'Saved.');
  }
  async attach(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (f) await this.run(() => this.api.postP(`maintenance/${this.id()}/attachments/`, toFormData({ file: f, is_internal: false })), 'File added.');
  }
}
