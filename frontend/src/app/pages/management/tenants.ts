import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe } from '../../core/format';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, RouterLink, KesPipe, Badge, Empty, Icon, Loading, PageHeader, Pager],
  template: `
    <app-page-header title="Tenants" subtitle="Current and former tenants in your properties.">
      @if (auth.can('manage_tenants')) { <a class="btn btn-primary" routerLink="/management/tenants/new"><app-icon name="plus" /> Register tenant</a> }
    </app-page-header>
    <div class="card">
      <div class="toolbar">
        <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search name, phone, email, unit…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
        <select [(ngModel)]="list.filters['property']" (change)="list.load(true)"><option value="">All properties</option>
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
        <select [(ngModel)]="list.filters['status']" (change)="list.load(true)"><option value="active">Current tenants</option><option value="former">Former tenants</option><option value="">All</option></select>
        @if (auth.can('view_payments')) {
          <select [(ngModel)]="list.filters['account_status']" (change)="list.load(true)"><option value="">Any balance</option><option value="overdue">Overdue</option><option value="due">Due</option><option value="paid">Paid up</option><option value="credit">In credit</option></select>
        }
      </div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) {
        <app-empty icon="users" title="No tenants found" text="Register a tenant and assign them to a unit to start tracking rent.">
          @if (auth.can('manage_tenants')) { <a class="btn btn-primary" routerLink="/management/tenants/new">Register tenant</a> }
        </app-empty>
      } @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Name</th><th>Contact</th><th>Unit</th>@if (auth.can('view_payments')) { <th class="num">Balance</th><th>Account</th> }<th>Portal</th></tr></thead>
          <tbody>@for (t of list.items(); track t.id) {
            <tr class="clickable" [routerLink]="['/management/tenants', t.id]">
              <td data-label="Name" class="strong">{{ t.full_name }} @if (t.status !== 'active') { <app-badge [value]="t.status" /> }</td>
              <td data-label="Contact">{{ t.phone }}<span class="sub">{{ t.email }}</span></td>
              <td data-label="Unit">@if (t.current_tenancy) { {{ t.current_tenancy.unit_label }}<span class="sub">{{ t.current_tenancy.property_name }}</span> } @else { <span class="muted">No current unit</span> }</td>
              @if (auth.can('view_payments')) {
                <td data-label="Balance" class="num" [class.text-red]="+t.balance > 0">{{ t.balance === null ? '—' : (t.balance | kes) }}</td>
                <td data-label="Account">@if (t.account_status) { <app-badge [value]="t.account_status" /> }</td>
              }
              <td data-label="Portal">@if (t.has_portal_account === false) { <span class="muted small">No account</span> } @else if (t.has_portal_account) { <app-icon name="check" [size]="16" /> }</td>
            </tr>
          }</tbody></table></div>
        <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
      }
    </div>`,
})
export class TenantsPage {
  auth = inject(Auth);
  list = new ListState(inject(Api), 'tenants/', { search: '', property: '', status: 'active', account_status: '' });
  constructor() {
    const q = inject(ActivatedRoute).snapshot.queryParams;
    Object.assign(this.list.filters, q);
    this.list.load();
  }
}
