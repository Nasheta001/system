import { DatePipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { ListState } from '../../shared/list';
import { Empty, Icon, Loading, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, DatePipe, Empty, Icon, Loading, PageHeader, Pager],
  template: `
    <app-page-header title="Audit log" subtitle="Important administrative actions, who did them and when. Entries cannot be edited." />
    <div class="card">
      <div class="toolbar"><div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search action, summary or user…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div></div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) { <app-empty icon="shield" title="No entries" /> }
      @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>When</th><th>User</th><th>Action</th><th>Summary</th><th>Property</th><th>IP</th></tr></thead>
          <tbody>@for (e of list.items(); track e.id) {
            <tr><td data-label="When" class="nowrap">{{ e.created_at | date: 'd MMM yyyy, HH:mm' }}</td><td data-label="User">{{ e.actor_name }}</td>
              <td data-label="Action" class="mono">{{ e.action }}</td><td data-label="Summary">{{ e.summary }}</td>
              <td data-label="Property">{{ e.property_name || '—' }}</td><td data-label="IP" class="mono small">{{ e.ip_address || '' }}</td></tr>
          }</tbody></table></div>
        <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" [pageSize]="50" />
      }
    </div>`,
})
export class AuditPage {
  list = new ListState(inject(Api), 'audit-logs/', { search: '' }, 50);
  constructor() {
    this.list.load();
  }
}
