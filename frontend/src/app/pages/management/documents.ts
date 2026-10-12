import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { Ui } from '../../core/ui.service';
import { ListState, toFormData } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal, PageHeader, Pager } from '../../shared/ui';

export const DOC_CATEGORIES = [
  ['tenancy_agreement', 'Tenancy agreement'], ['rules', 'Building rules'], ['waste', 'Waste disposal'], ['water', 'Water arrangements'],
  ['security', 'Security procedures'], ['emergency', 'Emergency contacts'], ['notice', 'General notice'], ['inspection', 'Inspection record'],
  ['move_in', 'Move-in document'], ['move_out', 'Move-out document'], ['statement', 'Statement / receipt'], ['other', 'Other'],
];

@Component({
  imports: [FormsModule, RouterLink, DatePipe, Badge, Empty, Icon, Loading, Modal, PageHeader, Pager],
  template: `
    <app-page-header title="Documents & rules library" subtitle="Approved rules, notices and tenancy documents – each version is kept.">
      @if (auth.can('manage_documents')) { <button class="btn btn-primary" (click)="openUpload()"><app-icon name="upload" /> Upload document</button> }
    </app-page-header>
    <div class="tabs">
      <button class="tab" [class.active]="tab() === 'library'" (click)="setTab('library')">Rules & notices library</button>
      <button class="tab" [class.active]="tab() === 'all'" (click)="setTab('all')">All documents</button>
      <button class="tab" [class.active]="tab() === 'signatures'" (click)="setTab('signatures')">Signatures</button>
    </div>
    @if (tab() !== 'signatures') {
      <div class="card">
        <div class="toolbar">
          <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search documents…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
          <select [(ngModel)]="list.filters['property']" (change)="list.load(true)"><option value="">Any property</option>
            @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
          <select [(ngModel)]="list.filters['category']" (change)="list.load(true)"><option value="">Any category</option>
            @for (c of categories; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select>
          <select [(ngModel)]="list.filters['status']" (change)="list.load(true)"><option value="">Any status</option><option value="approved">Approved</option><option value="draft">Draft</option><option value="archived">Archived</option></select>
        </div>
        @if (list.loading() && !list.loaded()) { <app-loading /> }
        @else if (!list.items().length) {
          <app-empty icon="file" title="No documents yet" text="Upload building rules, waste schedules, water arrangements and emergency contacts once – new tenants will find them in their portal.">
            @if (auth.can('manage_documents')) { <button class="btn btn-primary" (click)="openUpload()">Upload document</button> }
          </app-empty>
        } @else {
          <div class="table-wrap"><table class="table responsive">
            <thead><tr><th>Document</th><th>Category</th><th>Applies to</th><th>Workflow</th><th>Version</th><th>Status</th></tr></thead>
            <tbody>@for (d of list.items(); track d.id) {
              <tr class="clickable" [routerLink]="['/management/documents', d.id]">
                <td data-label="Document"><b>{{ d.title }}</b><span class="sub">Updated {{ d.updated_at | date: 'd MMM yyyy' }}</span></td>
                <td data-label="Category">{{ d.category_label }}</td>
                <td data-label="Applies to">@for (x of d.assignments; track x.id) { <span class="sub" style="display:block;color:inherit">{{ x.target }}</span> } @empty { <span class="muted small">Not assigned</span> }</td>
                <td data-label="Workflow"><app-badge [value]="d.workflow" /></td>
                <td data-label="Version">v{{ d.current_version_info?.version }}</td>
                <td data-label="Status"><app-badge [value]="d.status" /></td>
              </tr>
            }</tbody></table></div>
          <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
        }
      </div>
    } @else {
      <div class="card">
        <div class="toolbar"><select [(ngModel)]="sigs.filters['status']" (change)="sigs.load(true)"><option value="">Any status</option><option value="pending">Awaiting signature</option><option value="submitted">Submitted – needs review</option><option value="verified">Verified</option><option value="rejected">Rejected</option></select>
          <span class="muted small">Tenants download, sign and upload a copy. Staff verify each signed copy.</span></div>
        @if (!sigs.items().length) { <app-empty icon="edit" title="No signature requests" /> }
        <div class="table-wrap"><table class="table responsive">
          @if (sigs.items().length) { <thead><tr><th>Document</th><th>Tenant</th><th>Due</th><th>Status</th><th></th></tr></thead> }
          <tbody>@for (s of sigs.items(); track s.id) {
            <tr><td data-label="Document"><a [routerLink]="['/management/documents', s.document]">{{ s.document_title }}</a><span class="sub">v{{ s.version_number }}</span></td>
              <td data-label="Tenant">{{ s.tenant_name }}</td><td data-label="Due">{{ s.due_date ? (s.due_date | date: 'd MMM') : '—' }}</td>
              <td data-label="Status"><app-badge [value]="s.status" />@if (s.review_notes) { <span class="sub">{{ s.review_notes }}</span> }</td>
              <td class="actions">@if (s.has_signed_file) { <button class="btn btn-sm btn-ghost" (click)="api.download('signature-requests/' + s.id + '/signed-file/')">Signed copy</button> }
                @if (s.status === 'submitted' && auth.can('manage_documents')) { <button class="btn btn-sm" (click)="review(s, 'verify')">Verify</button><button class="btn btn-sm btn-ghost" (click)="review(s, 'reject')">Reject</button> }</td></tr>
          }</tbody></table></div>
      </div>
    }

    <app-modal [(open)]="uploadOpen" title="Upload document" [wide]="true">
      <form (ngSubmit)="upload()">
        @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
        <div class="form-grid">
          <label class="field span-2"><span>Title *</span><input name="t" [(ngModel)]="doc.title"></label>
          <label class="field"><span>Category</span><select name="c" [(ngModel)]="doc.category">@for (c of categories; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select></label>
          <label class="field"><span>Workflow</span><select name="w" [(ngModel)]="doc.workflow"><option value="info">Information only</option><option value="acknowledge">Tenants must acknowledge</option><option value="signature">Signature required</option></select></label>
          <label class="field"><span>Property</span><select name="p" [(ngModel)]="doc.property"><option value="">{{ auth.me()?.portfolio_access ? 'Company-wide' : '— Select —' }}</option>
            @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></label>
          <label class="field"><span>For a specific tenant (optional)</span><select name="tn" [(ngModel)]="doc.tenant"><option value="">— Not tenant-specific —</option>
            @for (t of tenants(); track t.id) { <option [value]="t.id">{{ t.full_name }} – {{ t.current_tenancy?.unit_label }}</option> }</select></label>
          <label class="field span-2"><span>Description</span><textarea name="d" rows="2" [(ngModel)]="doc.description"></textarea></label>
          <label class="field span-2"><span>File * (PDF, DOCX, JPG, PNG – max 10 MB)</span><input type="file" accept=".pdf,.docx,.doc,.jpg,.jpeg,.png" (change)="file = $any($event.target).files[0]"></label>
        </div>
        <label class="check"><input type="checkbox" name="lib" [(ngModel)]="doc.is_library"> Add to the standard rules & notices library</label>
        @if (doc.workflow === 'signature') { <div class="alert alert-info small">Signature workflow: tenants download, sign (by hand or with their own legally recognised e-signature tool) and upload the signed copy. Staff then verify it. This system does not itself create legally binding e-signatures.</div> }
        <p class="muted small">New documents start as drafts. Approve them to make them visible to their audience.</p>
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !doc.title || !file">Upload</button></div>
      </form>
    </app-modal>`,
})
export class DocumentsPage {
  api = inject(Api);
  auth = inject(Auth);
  private ui = inject(Ui);
  private router = inject(Router);
  categories = DOC_CATEGORIES;
  tab = signal('library');
  list = new ListState(this.api, 'documents/', { search: '', category: '', status: '', property: '', is_library: 'true' });
  sigs = new ListState(this.api, 'signature-requests/', { status: '' });
  uploadOpen = signal(false);
  busy = signal(false);
  formErr = signal('');
  tenants = signal<any[]>([]);
  doc: any = {};
  file: File | null = null;

  constructor() {
    this.setTab(inject(ActivatedRoute).snapshot.queryParams['tab'] || 'library');
  }

  setTab(t: string) {
    this.tab.set(t);
    if (t === 'signatures') {
      this.sigs.filters['status'] = this.sigs.filters['status'] || '';
      this.sigs.load(true);
    } else {
      this.list.filters['is_library'] = t === 'library' ? 'true' : '';
      this.list.load(true);
    }
  }

  async openUpload() {
    this.formErr.set('');
    this.file = null;
    this.doc = { title: '', category: 'rules', workflow: 'info', property: '', tenant: '', description: '', is_library: this.tab() === 'library' };
    this.uploadOpen.set(true);
    this.tenants.set(await this.api.all('tenants/', { status: 'active' }));
  }

  async upload() {
    this.busy.set(true);
    this.formErr.set('');
    try {
      const body: any = { ...this.doc, file: this.file };
      for (const k of ['property', 'tenant']) if (!body[k]) delete body[k];
      const d = await this.api.postP('documents/', toFormData(body));
      this.uploadOpen.set(false);
      this.ui.toast('Uploaded as draft. Review and approve it to publish.');
      this.router.navigate(['/management/documents', d.id]);
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async review(s: any, action: 'verify' | 'reject') {
    let notes: any = '';
    if (action === 'reject') {
      notes = await this.ui.confirm({ title: 'Reject signed copy?', message: 'The tenant will be asked to upload again.', reasonLabel: 'What needs to be corrected?', danger: true, confirmText: 'Reject' });
      if (!notes) return;
    }
    try {
      await this.api.postP(`signature-requests/${s.id}/${action}/`, { notes });
      this.ui.toast(action === 'verify' ? 'Signature verified.' : 'Returned to tenant.');
      this.sigs.load();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
