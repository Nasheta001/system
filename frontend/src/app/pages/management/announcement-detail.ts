import { DatePipe } from '@angular/common';
import { Component, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Empty, Icon, Loading, PageHeader, Stat } from '../../shared/ui';

@Component({
  imports: [RouterLink, DatePipe, LabelPipe, Badge, Empty, Icon, Loading, PageHeader, Stat],
  template: `
    @if (!a()) { <app-loading /> } @else {
      <app-page-header [title]="a().title" back="/management/announcements" backLabel="Announcements">
        @if (auth.can('manage_announcements')) {
          @if (a().status === 'draft' || a().status === 'scheduled') {
            <a class="btn" [routerLink]="['/management/announcements', a().id, 'edit']"><app-icon name="edit" /> Edit</a>
            @if (!a().is_template) { <button class="btn btn-primary" (click)="publish()"><app-icon name="send" /> {{ a().status === 'scheduled' ? 'Publish now' : 'Publish' }}</button> }
            @if (a().status === 'scheduled') { <button class="btn" (click)="act('unschedule', 'Moved back to draft.')">Unschedule</button> }
            @if (a().status === 'draft') { <button class="btn btn-ghost" (click)="remove()">Delete</button> }
          }
          <button class="btn" (click)="duplicate()"><app-icon name="copy" /> Duplicate</button>
          @if (a().status === 'published') { <button class="btn btn-ghost" (click)="act('archive', 'Archived.')"><app-icon name="archive" /> Archive</button> }
        }
      </app-page-header>
      <div class="row mb"><app-badge [value]="a().status" /><app-badge [value]="a().priority" />
        @if (a().is_template) { <app-badge value="info" text="Reusable notice" /> }
        <span class="muted small">{{ a().audience | label }} {{ a().property_names.length ? '· ' + a().property_names.join(', ') : '' }}</span></div>

      @if (a().status === 'published' || a().status === 'archived') {
        <div class="grid-4 mb">
          <app-stat label="Recipients" [value]="a().stats.recipients" icon="users" />
          <app-stat label="Opened in portal" [value]="a().stats.opened" [hint]="pct(a().stats.opened) + '%'" icon="eye" tone="blue" />
          <app-stat label="Acknowledged" [value]="a().requires_acknowledgement ? a().stats.acknowledged : '—'" [hint]="a().requires_acknowledgement ? pct(a().stats.acknowledged) + '%' : 'Not required'" icon="check" />
          <app-stat label="Published" [value]="a().published_at | date: 'd MMM'" [hint]="(a().published_at | date: 'HH:mm') ?? ''" icon="calendar" tone="clay" />
        </div>
      }

      <div class="split">
        <div class="stack">
          <div class="card card-pad">
            <p style="white-space:pre-line">{{ a().body }}</p>
            @if (a().action_text) { <div class="alert alert-info">{{ a().action_text }}</div> }
            @if (a().related_document_title) { <p class="small">Related document: <a [routerLink]="['/management/documents', a().related_document]">{{ a().related_document_title }}</a></p> }
            <div class="divider"></div>
            <h3>Attachments</h3>
            @for (f of a().attachments; track f.id) {
              <div><button class="btn-link" (click)="api.download('announcement-attachments/' + f.id + '/download/')"><app-icon name="file" [size]="15" /> {{ f.original_name }}</button></div>
            } @empty { <p class="muted small">None</p> }
            @if (auth.can('manage_announcements') && a().status !== 'archived') {
              <label class="btn btn-sm mt"><app-icon name="upload" [size]="15" /> Attach file<input type="file" hidden accept=".pdf,.jpg,.jpeg,.png,.docx" (change)="attach($event)"></label>
            }
          </div>
          @if (a().status === 'published' || a().status === 'archived') {
            <div class="card">
              <div class="card-head"><h2>Recipients</h2><span class="muted small">Portal open & acknowledgement are tracked; email/SMS "sent" means accepted by the provider, not read.</span></div>
              @if (!recipients().length) { <app-empty icon="users" title="No recipients" text="No current tenants matched the audience when this was published." /> }
              <div class="table-wrap"><table class="table responsive">
                @if (recipients().length) { <thead><tr><th>Recipient</th><th>Delivery</th><th>Opened</th><th>Acknowledged</th></tr></thead> }
                <tbody>@for (r of recipients(); track r.id) {
                  <tr><td data-label="Recipient">{{ r.name }}<span class="sub">{{ r.property_name }}</span></td>
                    <td data-label="Delivery"><div class="row" style="gap:4px">@for (d of r.deliveries; track d.channel) { <app-badge [value]="d.status" [text]="(d.channel | label) + ': ' + (d.status | label)" /> }</div></td>
                    <td data-label="Opened">{{ r.opened_at ? (r.opened_at | date: 'd MMM HH:mm') : '—' }}</td>
                    <td data-label="Acknowledged">{{ r.acknowledged_at ? (r.acknowledged_at | date: 'd MMM HH:mm') : (a().requires_acknowledgement ? 'Pending' : '—') }}</td></tr>
                }</tbody></table></div>
            </div>
          }
        </div>
        <aside class="card card-pad">
          <dl class="kv">
            <dt>Author</dt><dd>{{ a().author_name || '—' }}</dd>
            <dt>Created</dt><dd>{{ a().created_at | date: 'medium' }}</dd>
            @if (a().publish_at) { <dt>Publish at</dt><dd>{{ a().publish_at | date: 'medium' }}</dd> }
            @if (a().expires_at) { <dt>Expires</dt><dd>{{ a().expires_at | date: 'medium' }}</dd> }
            <dt>Channels</dt><dd>Portal{{ a().send_email ? ', email' : '' }}{{ a().send_sms ? ', SMS' : '' }}{{ a().send_whatsapp ? ', WhatsApp' : '' }}</dd>
            <dt>Acknowledgement</dt><dd>{{ a().requires_acknowledgement ? 'Required' : 'Not required' }}</dd>
          </dl>
          @if (a().status === 'draft' && preview()) {
            <div class="alert alert-info mt small">If published now: {{ preview().tenants }} tenant(s){{ preview().staff ? ', ' + preview().staff + ' staff' : '' }}.
              @if (preview().sample.length) { <br>e.g. {{ preview().sample.slice(0, 5).join(', ') }} }</div>
          }
        </aside>
      </div>
    }`,
})
export class AnnouncementDetailPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  private router = inject(Router);
  id = input.required<string>();
  a = signal<any>(null);
  recipients = signal<any[]>([]);
  preview = signal<any>(null);

  ngOnInit() {
    this.load();
  }

  async load() {
    const a = await this.api.getP(`announcements/${this.id()}/`);
    this.a.set(a);
    if (a.status === 'published' || a.status === 'archived') this.recipients.set(await this.api.getP(`announcements/${a.id}/recipients/`));
    if (a.status === 'draft' || a.status === 'scheduled') this.preview.set(await this.api.getP(`announcements/${a.id}/audience-preview/`));
  }

  pct(n: number) {
    const total = this.a()?.stats.recipients || 0;
    return total ? Math.round((100 * n) / total) : 0;
  }

  async act(action: string, msg: string) {
    try {
      await this.api.postP(`announcements/${this.id()}/${action}/`);
      this.ui.toast(msg);
      this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async publish() {
    const p = this.preview();
    if (await this.ui.confirm({ title: 'Publish this notice?', message: `It will be delivered to ${p?.tenants ?? 0} tenant(s)${p?.staff ? ' and ' + p.staff + ' staff' : ''}. Published notices cannot be edited.`, confirmText: 'Publish' })) {
      await this.act('publish', 'Published.');
    }
  }

  async duplicate() {
    const copy = await this.api.postP(`announcements/${this.id()}/duplicate/`);
    this.router.navigate(['/management/announcements', copy.id, 'edit']);
  }

  async remove() {
    if (!(await this.ui.confirm({ title: 'Delete draft?', message: 'This draft will be removed.', danger: true, confirmText: 'Delete' }))) return;
    await this.api.deleteP(`announcements/${this.id()}/`);
    this.router.navigate(['/management/announcements']);
  }

  async attach(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (!f) return;
    try {
      await this.api.postP(`announcements/${this.id()}/attachments/`, toFormData({ file: f }));
      this.ui.toast('File attached.');
      this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
