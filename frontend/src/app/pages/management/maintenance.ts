import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal, PageHeader, Pager } from '../../shared/ui';

export const MR_CATEGORIES = [['plumbing', 'Plumbing'], ['electrical', 'Electrical'], ['water', 'Water supply'], ['security', 'Security / locks'],
  ['structural', 'Structural / walls / roof'], ['appliances', 'Fixtures & appliances'], ['cleaning', 'Cleaning / waste'], ['pest', 'Pest control'], ['other', 'Other']];
export const MR_STATUSES = ['submitted', 'reviewed', 'assigned', 'in_progress', 'awaiting_parts', 'completed', 'closed', 'cancelled'];

@Component({
  imports: [FormsModule, RouterLink, DatePipe, LabelPipe, Badge, Empty, Icon, Loading, Modal, PageHeader, Pager],
  template: `
    <app-page-header title="Maintenance" subtitle="Requests from tenants and staff, from report to completion.">
      @if (auth.can('manage_maintenance')) { <button class="btn btn-primary" (click)="openNew()"><app-icon name="plus" /> Log request</button> }
    </app-page-header>
    <div class="card">
      <div class="toolbar">
        <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Reference, title, unit, tenant…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
        <select [(ngModel)]="list.filters['property']" (change)="list.load(true)"><option value="">All properties</option>
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
        <select [(ngModel)]="statusSel" (change)="applyStatus()"><option value="open">Open requests</option><option value="">All</option>
          @for (s of statuses; track s) { <option [value]="s">{{ s | label }}</option> }</select>
        <select [(ngModel)]="list.filters['urgency']" (change)="list.load(true)"><option value="">Any urgency</option><option value="emergency">Emergency</option><option value="high">High</option><option value="normal">Normal</option><option value="low">Low</option></select>
        <label class="check small" style="margin:0"><input type="checkbox" [(ngModel)]="mine" (change)="list.filters['mine'] = mine ? 'true' : ''; list.load(true)"> Assigned to me</label>
      </div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) { <app-empty icon="wrench" title="No maintenance requests" text="Requests submitted by tenants or logged by staff appear here." /> }
      @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Request</th><th>Location</th><th>Urgency</th><th>Status</th><th>Assigned</th><th>Reported</th></tr></thead>
          <tbody>@for (r of list.items(); track r.id) {
            <tr class="clickable" [routerLink]="['/management/maintenance', r.id]">
              <td data-label="Request"><b>{{ r.title }}</b><span class="sub mono">{{ r.reference }} · {{ r.category | label }}</span></td>
              <td data-label="Location">{{ r.unit_label || '—' }}<span class="sub">{{ r.property_name }}</span></td>
              <td data-label="Urgency"><app-badge [value]="r.urgency" /></td>
              <td data-label="Status"><app-badge [value]="r.status" /></td>
              <td data-label="Assigned">{{ r.assigned_to_name || '—' }}</td>
              <td data-label="Reported">{{ r.created_at | date: 'd MMM yyyy' }}<span class="sub">{{ r.tenant_name }}</span></td>
            </tr>
          }</tbody></table></div>
        <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
      }
    </div>

    <app-modal [(open)]="newOpen" title="Log a maintenance request" [wide]="true">
      <form (ngSubmit)="create()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field"><span>Property *</span><select name="p" [(ngModel)]="req.property" (ngModelChange)="loadUnits()">@for (p of auth.me()?.assigned_properties; track p.id) { <option [ngValue]="p.id">{{ p.name }}</option> }</select></label>
          <label class="field"><span>Unit (blank = common area)</span><select name="u" [(ngModel)]="req.unit"><option [ngValue]="null">Common area</option>@for (u of units(); track u.id) { <option [ngValue]="u.id">{{ u.label }}</option> }</select></label>
          <label class="field span-2"><span>Title *</span><input name="t" [(ngModel)]="req.title"></label>
          <label class="field span-2"><span>Description *</span><textarea name="d" rows="3" [(ngModel)]="req.description"></textarea></label>
          <label class="field"><span>Category</span><select name="c" [(ngModel)]="req.category">@for (c of categories; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select></label>
          <label class="field"><span>Urgency</span><select name="ur" [(ngModel)]="req.urgency"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="emergency">Emergency</option></select></label>
        </div>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !req.property || !req.title || !req.description">Create</button></div>
      </form>
    </app-modal>`,
})
export class MaintenancePage {
  private api = inject(Api);
  private ui = inject(Ui);
  private router = inject(Router);
  auth = inject(Auth);
  categories = MR_CATEGORIES;
  statuses = MR_STATUSES;
  statusSel = 'open';
  mine = false;
  list = new ListState(this.api, 'maintenance/', { search: '', property: '', urgency: '', status: '', open: 'true', mine: '', ordering: '-created_at' });
  newOpen = signal(false);
  busy = signal(false);
  formErr = signal('');
  units = signal<any[]>([]);
  req: any = {};

  constructor() {
    this.list.load();
  }

  applyStatus() {
    this.list.filters['open'] = this.statusSel === 'open' ? 'true' : '';
    this.list.filters['status'] = this.statusSel === 'open' ? '' : this.statusSel;
    this.list.load(true);
  }

  openNew() {
    this.formErr.set('');
    this.req = { property: this.auth.me()?.assigned_properties[0]?.id, unit: null, title: '', description: '', category: 'plumbing', urgency: 'normal' };
    this.loadUnits();
    this.newOpen.set(true);
  }

  async loadUnits() {
    this.units.set(this.req.property ? await this.api.all('units/', { property: this.req.property }) : []);
  }

  async create() {
    this.busy.set(true);
    try {
      const r = await this.api.postP('maintenance/', this.req);
      this.newOpen.set(false);
      this.ui.toast(`Request ${r.reference} created.`);
      this.router.navigate(['/management/maintenance', r.id]);
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }
}
