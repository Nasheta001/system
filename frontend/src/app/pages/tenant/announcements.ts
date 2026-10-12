import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Api, parseError } from '../../core/api.service';
import { Ui } from '../../core/ui.service';
import { Badge, Empty, Icon, Loading } from '../../shared/ui';

@Component({
  imports: [DatePipe, Badge, Empty, Icon, Loading],
  template: `
    <h1>Notices</h1>
    @if (!loaded()) { <app-loading /> }
    @else if (!items().length) { <div class="card"><app-empty icon="megaphone" title="No notices" text="Announcements from management will appear here." /></div> }
    @else {
      <div class="stack">
        @for (n of items(); track n.id) {
          <article class="card notice" [class.unread]="!n.opened_at">
            <button class="notice-head" (click)="toggle(n)" [attr.aria-expanded]="openId() === n.id">
              <div><div class="row" style="gap:6px">@if (!n.opened_at) { <span class="dot"></span> }<b>{{ n.title }}</b></div>
                <div class="row small muted" style="gap:6px;margin-top:4px">{{ n.published_at | date: 'd MMM yyyy' }}
                  @if (n.priority === 'high' || n.priority === 'urgent') { <app-badge [value]="n.priority" /> }
                  @if (n.requires_acknowledgement) { @if (n.acknowledged_at) { <app-badge value="done" text="Acknowledged" /> } @else { <app-badge value="pending" text="Acknowledgement needed" /> } }</div></div>
              <app-icon [name]="openId() === n.id ? 'x' : 'right'" [size]="16" />
            </button>
            @if (openId() === n.id) {
              <div class="card-body">
                <p style="white-space:pre-line">{{ n.body }}</p>
                @if (n.action_text) { <div class="alert alert-info">{{ n.action_text }}</div> }
                @for (f of n.attachments; track f.id) {
                  <div><button class="btn-link" (click)="api.download('announcement-attachments/' + f.id + '/download/')"><app-icon name="file" [size]="15" /> {{ f.original_name }}</button></div>
                }
                @if (n.requires_acknowledgement && !n.acknowledged_at) {
                  <button class="btn btn-primary mt" (click)="ack(n)"><app-icon name="check" /> I have read and understood this notice</button>
                }
              </div>
            }
          </article>
        }
      </div>
    }`,
  styles: `
    .notice-head { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 18px; border: 0; background: none; text-align: left; font: inherit; cursor: pointer; color: inherit; }
    .notice.unread { border-left: 3px solid var(--brand); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--brand); display: inline-block; }
  `,
})
export class TenantAnnouncementsPage {
  api = inject(Api);
  private ui = inject(Ui);
  items = signal<any[]>([]);
  loaded = signal(false);
  openId = signal<number | null>(null);

  constructor() {
    this.load();
  }

  async load() {
    const r = await this.api.getP('portal/announcements/', { page_size: 100 });
    this.items.set(r.results);
    this.loaded.set(true);
  }

  async toggle(n: any) {
    if (this.openId() === n.id) {
      this.openId.set(null);
      return;
    }
    this.openId.set(n.id);
    if (!n.opened_at) {
      const r = await this.api.getP(`portal/announcements/${n.id}/`);
      this.items.update((l) => l.map((x) => (x.id === n.id ? r : x)));
    }
  }

  async ack(n: any) {
    try {
      const r = await this.api.postP(`portal/announcements/${n.id}/acknowledge/`);
      this.items.update((l) => l.map((x) => (x.id === n.id ? r : x)));
      this.ui.toast('Thank you – acknowledgement recorded.');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
