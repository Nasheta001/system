import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, RouterLink, DatePipe, LabelPipe, Badge, Empty, Icon, Loading, PageHeader, Pager],
  template: `
    <app-page-header title="Announcements" subtitle="Notices to tenants by property, building or individual – with read and acknowledgement tracking.">
      @if (auth.can('manage_announcements')) { <a class="btn btn-primary" routerLink="/management/announcements/new"><app-icon name="plus" /> New announcement</a> }
    </app-page-header>
    <div class="tabs">
      @for (t of tabs; track t[0]) { <button class="tab" [class.active]="tab() === t[0]" (click)="setTab(t[0])">{{ t[1] }}</button> }
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search notices…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
        <select [(ngModel)]="list.filters['properties']" (change)="list.load(true)"><option value="">All properties</option>
          @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
      </div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) {
        <app-empty icon="megaphone" [title]="tab() === 'templates' ? 'No reusable notices' : 'No announcements here'"
          [text]="tab() === 'templates' ? 'Save frequently used notices as templates (e.g. water interruption, garbage schedule).' : 'Create a notice and choose exactly who should receive it.'">
          @if (auth.can('manage_announcements')) { <a class="btn btn-primary" routerLink="/management/announcements/new">New announcement</a> }
        </app-empty>
      } @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Title</th><th>Audience</th><th>Priority</th><th>Status</th><th>Reach</th><th></th></tr></thead>
          <tbody>@for (a of list.items(); track a.id) {
            <tr class="clickable" [routerLink]="['/management/announcements', a.id]">
              <td data-label="Title"><b>{{ a.title }}</b><span class="sub">by {{ a.author_name || '—' }} · {{ (a.published_at || a.created_at) | date: 'd MMM yyyy' }}</span></td>
              <td data-label="Audience">{{ a.audience | label }}<span class="sub">{{ a.property_names.join(', ') }}</span></td>
              <td data-label="Priority"><app-badge [value]="a.priority" /></td>
              <td data-label="Status"><app-badge [value]="a.status" />@if (a.status === 'scheduled') { <span class="sub">{{ a.publish_at | date: 'd MMM HH:mm' }}</span> }</td>
              <td data-label="Reach">@if (a.stats.recipients) { {{ a.stats.recipients }} · {{ a.stats.opened }} opened @if (a.requires_acknowledgement) { · {{ a.stats.acknowledged }} ack. } } @else { — }</td>
              <td class="actions" (click)="$event.stopPropagation()">@if (a.is_template && auth.can('manage_announcements')) { <button class="btn btn-sm" (click)="useTemplate(a)">Use template</button> }</td>
            </tr>
          }</tbody></table></div>
        <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
      }
    </div>`,
})
export class AnnouncementsPage {
  private api = inject(Api);
  private ui = inject(Ui);
  private router = inject(Router);
  auth = inject(Auth);
  tabs = [['', 'All'], ['published', 'Published'], ['scheduled', 'Scheduled'], ['draft', 'Drafts'], ['archived', 'Archived'], ['templates', 'Reusable notices']];
  tab = signal('');
  list = new ListState(this.api, 'announcements/', { search: '', status: '', is_template: 'false', properties: '' });

  constructor() {
    this.list.load();
  }

  setTab(t: string) {
    this.tab.set(t);
    this.list.filters['is_template'] = t === 'templates' ? 'true' : 'false';
    this.list.filters['status'] = t === 'templates' ? '' : t;
    this.list.load(true);
  }

  async useTemplate(a: any) {
    try {
      const copy = await this.api.postP(`announcements/${a.id}/duplicate/`);
      this.router.navigate(['/management/announcements', copy.id, 'edit']);
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
