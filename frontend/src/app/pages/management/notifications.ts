import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '../../core/api.service';
import { Empty, PageHeader } from '../../shared/ui';

/** In-app notifications for the signed-in user (used by staff and tenants). */
@Component({
  selector: 'app-inbox',
  imports: [DatePipe, Empty, PageHeader],
  template: `
    <app-page-header title="Notifications">
      @if (unread() > 0) { <button class="btn" (click)="markAll()">Mark all as read</button> }
    </app-page-header>
    <div class="card">
      @if (!items().length) { <app-empty icon="bell" title="You're all caught up" text="Alerts about tenants, payments and maintenance appear here." /> }
      <ul class="list">@for (n of items(); track n.id) {
        <li class="note" [class.unread]="!n.read_at" (click)="open(n)">
          <div class="row-between"><b>{{ n.subject }}</b><span class="muted small">{{ n.created_at | date: 'd MMM, HH:mm' }}</span></div>
          <div class="muted small" style="white-space:pre-line">{{ n.body.slice(0, 220) }}</div>
        </li>
      }</ul>
    </div>`,
  styles: `.note { cursor: pointer; } .note.unread { background: var(--brand-50); } .note:hover { background: var(--surface-2); }`,
})
export class StaffNotificationsPage {
  private api = inject(Api);
  private router = inject(Router);
  items = signal<any[]>([]);
  unread = signal(0);

  constructor() {
    this.load();
  }

  async load() {
    const r = await this.api.getP('my-notifications/');
    this.items.set(r.results);
    this.unread.set(r.unread);
  }

  async open(n: any) {
    if (!n.read_at) await this.api.postP('my-notifications/', { ids: [n.id] });
    if (n.link) this.router.navigateByUrl(n.link);
    else this.load();
  }

  async markAll() {
    await this.api.postP('my-notifications/', { all: true });
    this.load();
  }
}
