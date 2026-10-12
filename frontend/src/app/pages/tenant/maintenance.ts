import { DatePipe } from '@angular/common';
import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { LabelPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal } from '../../shared/ui';
import { MR_CATEGORIES } from '../management/maintenance';

@Component({
  imports: [FormsModule, RouterLink, DatePipe, LabelPipe, Badge, Empty, Icon, Loading, Modal],
  template: `
    <div class="row-between mb"><h1 style="margin:0">Maintenance</h1><button class="btn btn-primary" (click)="openNew()"><app-icon name="plus" /> Report an issue</button></div>
    @if (!loaded()) { <app-loading /> }
    @else if (!items().length) { <div class="card"><app-empty icon="wrench" title="No requests yet" text="Something needs fixing? Report it here and follow the progress." /></div> }
    @else {
      <div class="card"><ul class="list">@for (r of items(); track r.id) {
        <li><a class="row-between" [routerLink]="['/tenant/maintenance', r.id]" style="color:inherit;text-decoration:none">
          <span><b>{{ r.title }}</b><span class="muted small" style="display:block">{{ r.reference }} · {{ r.category | label }} · {{ r.created_at | date: 'd MMM yyyy' }}</span></span>
          <app-badge [value]="r.status" /></a></li>
      }</ul></div>
    }
    <app-modal [(open)]="newOpen" title="Report a maintenance issue">
      <form (ngSubmit)="submit()">
        @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
        <label class="field"><span>What is the problem? *</span><input name="t" [(ngModel)]="req.title" maxlength="150" placeholder="e.g. Kitchen sink is leaking"></label>
        <label class="field"><span>Details *</span><textarea name="d" rows="4" [(ngModel)]="req.description" placeholder="Where exactly, since when, anything we should know to get access…"></textarea></label>
        <div class="form-grid">
          <label class="field"><span>Category</span><select name="c" [(ngModel)]="req.category">@for (c of categories; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select></label>
          <label class="field"><span>How urgent?</span><select name="u" [(ngModel)]="req.urgency"><option value="low">Low – when convenient</option><option value="normal">Normal</option><option value="high">High – affecting daily life</option><option value="emergency">Emergency – safety risk / flooding</option></select></label>
        </div>
        <label class="field"><span>Photo (optional)</span><input type="file" accept="image/jpeg,image/png,.pdf" (change)="file = $any($event.target).files[0]"></label>
        @if (req.urgency === 'emergency') { <div class="alert alert-warn small">For fire, gas leaks or immediate danger, call emergency services (999 / 112) and the caretaker first.</div> }
        <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !req.title || !req.description">Submit request</button></div>
      </form>
    </app-modal>`,
})
export class TenantMaintenancePage {
  private api = inject(Api);
  private ui = inject(Ui);
  private router = inject(Router);
  categories = MR_CATEGORIES;
  items = signal<any[]>([]);
  loaded = signal(false);
  newOpen = signal(false);
  busy = signal(false);
  error = signal('');
  req: any = {};
  file: File | null = null;

  constructor() {
    this.load();
  }

  async load() {
    const r = await this.api.getP('portal/maintenance/', { page_size: 100 });
    this.items.set(r.results);
    this.loaded.set(true);
  }

  openNew() {
    this.error.set('');
    this.file = null;
    this.req = { title: '', description: '', category: 'plumbing', urgency: 'normal' };
    this.newOpen.set(true);
  }

  async submit() {
    this.busy.set(true);
    this.error.set('');
    try {
      const r = await this.api.postP('portal/maintenance/', toFormData({ ...this.req, file: this.file }));
      this.newOpen.set(false);
      this.ui.toast(`Request ${r.reference} submitted. We'll keep you updated.`);
      this.router.navigate(['/tenant/maintenance', r.id]);
    } catch (e) {
      this.error.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }
}

@Component({
  imports: [FormsModule, RouterLink, DatePipe, LabelPipe, Badge, Icon, Loading],
  template: `
    <a routerLink="/tenant/maintenance" class="back-link"><app-icon name="left" [size]="16" /> All requests</a>
    @if (!r()) { <app-loading /> } @else {
      <div class="row-between"><h1 style="margin:0">{{ r().title }}</h1><app-badge [value]="r().status" /></div>
      <p class="muted">{{ r().reference }} · {{ r().unit_label }}, {{ r().property_name }} · {{ r().category | label }} · {{ r().urgency | label }} urgency</p>
      <div class="card card-pad mb"><p style="white-space:pre-line;margin:0">{{ r().description }}</p>
        @for (a of r().attachments; track a.id) {
          <div class="mt"><button class="btn-link" (click)="api.download('portal/maintenance/' + r().id + '/attachments/' + a.id + '/')"><app-icon name="file" [size]="15" /> {{ a.original_name }}</button></div>
        }
        @if (r().resolution_notes) { <div class="alert alert-success mt">{{ r().resolution_notes }}</div> }
      </div>
      <div class="card">
        <div class="card-head"><h2>Updates</h2></div>
        <div class="card-body">
          <ul class="timeline">
            <li><b>Submitted</b><div class="meta">{{ r().created_at | date: 'd MMM yyyy, HH:mm' }}</div></li>
            @for (u of r().updates; track u.id) {
              <li>@if (u.status_to && u.status_to !== u.status_from) { <b>{{ u.status_to | label }}</b> }
                @if (u.message) { <div style="white-space:pre-line">{{ u.message }}</div> }
                <div class="meta">{{ u.author_name }} · {{ u.created_at | date: 'd MMM yyyy, HH:mm' }}</div></li>
            }
          </ul>
          @if (r().status !== 'closed' && r().status !== 'cancelled') {
            <form (ngSubmit)="comment()" class="mt">
              <label class="field"><span>Add a message</span><textarea name="m" rows="2" [(ngModel)]="message"></textarea></label>
              <div class="row-between">
                <label class="btn btn-sm"><app-icon name="upload" [size]="14" /> Add photo<input type="file" hidden accept="image/jpeg,image/png,.pdf" (change)="attach($event)"></label>
                <button class="btn btn-primary btn-sm" [disabled]="!message.trim()">Send</button></div>
            </form>
          }
        </div>
      </div>
    }`,
})
export class TenantMaintenanceDetailPage {
  api = inject(Api);
  private ui = inject(Ui);
  id = input.required<string>();
  r = signal<any>(null);
  message = '';

  ngOnInit() {
    this.api.getP(`portal/maintenance/${this.id()}/`).then((r) => this.r.set(r)).catch((e) => this.ui.error(parseError(e).message));
  }

  async comment() {
    try {
      this.r.set(await this.api.postP(`portal/maintenance/${this.id()}/comment/`, { message: this.message }));
      this.message = '';
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async attach(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (!f) return;
    try {
      this.r.set(await this.api.postP(`portal/maintenance/${this.id()}/attachments/`, toFormData({ file: f })));
      this.ui.toast('Photo added.');
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }
}
