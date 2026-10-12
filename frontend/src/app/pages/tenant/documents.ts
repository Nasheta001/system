import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Api, parseError } from '../../core/api.service';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Empty, Icon, Loading } from '../../shared/ui';

@Component({
  imports: [DatePipe, Badge, Empty, Icon, Loading],
  template: `
    <h1>Documents</h1>
    <p class="muted">Your tenancy documents, house rules and other information from management.</p>
    @if (!loaded()) { <app-loading /> }
    @else if (!docs().length) { <div class="card"><app-empty icon="file" title="No documents yet" /></div> }
    @else {
      <div class="card">
        <ul class="list">@for (d of docs(); track d.id) {
          <li>
            <div class="row-between">
              <div><b>{{ d.title }}</b><div class="muted small">{{ d.category_label }} · v{{ d.version }} · {{ d.updated | date: 'd MMM yyyy' }}</div>
                @if (d.description) { <div class="small">{{ d.description }}</div> }</div>
              <button class="btn btn-sm" (click)="download(d)"><app-icon name="download" [size]="14" /> Download</button>
            </div>
            @if (d.workflow === 'acknowledge') {
              <div class="action-line">@if (d.acknowledged_at) { <app-badge value="done" [text]="'Acknowledged ' + (d.acknowledged_at | date: 'd MMM')" /> }
                @else { <span class="small">Please read this document, then confirm.</span><button class="btn btn-sm btn-primary" (click)="ack(d)">I have read this</button> }</div>
            }
            @if (d.workflow === 'signature') {
              <div class="action-line">
                @switch (d.signature?.status) {
                  @case ('verified') { <app-badge value="verified" text="Signed copy verified" /> }
                  @case ('submitted') { <app-badge value="submitted" text="Signed copy received – awaiting review" /> }
                  @default {
                    @if (d.signature?.status === 'rejected') { <span class="small text-red">Returned: {{ d.signature.review_notes }}</span> }
                    @else { <span class="small">Download, sign by hand, then upload a scan or clear photo of every page.</span> }
                    @if (d.signature) { <label class="btn btn-sm btn-primary"><app-icon name="upload" [size]="14" /> Upload signed copy<input type="file" hidden accept=".pdf,.jpg,.jpeg,.png" (change)="upload(d, $event)"></label> }
                  }
                }
              </div>
            }
          </li>
        }</ul>
      </div>
    }`,
  styles: `.action-line { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 8px; padding: 8px 10px; background: var(--surface-2); border-radius: 8px; }`,
})
export class TenantDocumentsPage {
  private api = inject(Api);
  private ui = inject(Ui);
  docs = signal<any[]>([]);
  loaded = signal(false);

  constructor() {
    this.load();
  }

  async load() {
    this.docs.set(await this.api.getP('portal/documents/'));
    this.loaded.set(true);
  }

  download(d: any) {
    this.api.download(`portal/documents/${d.id}/download/`, {}, d.file_name).catch((e) => this.ui.error(parseError(e).message));
  }

  async ack(d: any) {
    try {
      await this.api.postP(`portal/documents/${d.id}/acknowledge/`);
      this.ui.toast('Acknowledgement recorded.');
      this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async upload(d: any, ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (!f) return;
    try {
      await this.api.postP(`portal/signature-requests/${d.signature.id}/upload/`, toFormData({ file: f }));
      this.ui.toast('Signed copy uploaded. Management will verify it.');
      this.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
