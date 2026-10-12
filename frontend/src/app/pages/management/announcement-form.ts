import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { Ui } from '../../core/ui.service';
import { Loading, PageHeader } from '../../shared/ui';

@Component({
  imports: [FormsModule, PageHeader, Loading],
  template: `
    <app-page-header [title]="id() ? 'Edit announcement' : 'New announcement'" [back]="id() ? ['/management/announcements', id()] : '/management/announcements'" backLabel="Announcements" />
    @if (loading()) { <app-loading /> } @else {
    <form class="split" (ngSubmit)="save(false)">
      <div class="card card-pad">
        @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
        <label class="field"><span>Title *</span><input name="t" [(ngModel)]="a.title" maxlength="200" required></label>
        <label class="field"><span>Message *</span><textarea name="b" rows="9" [(ngModel)]="a.body" required></textarea>
          <small>SMS and WhatsApp recipients get a short alert with a secure link – the full message stays in the portal.</small></label>
        <div class="form-grid">
          <label class="field"><span>Priority</span><select name="p" [(ngModel)]="a.priority"><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
          <label class="field"><span>Related document (optional)</span><select name="rd" [(ngModel)]="a.related_document"><option [ngValue]="null">— None —</option>
            @for (d of documents(); track d.id) { <option [ngValue]="d.id">{{ d.title }}</option> }</select></label>
        </div>
        <label class="check"><input type="checkbox" name="ra" [(ngModel)]="a.requires_acknowledgement"> Tenants must acknowledge this notice</label>
        @if (a.requires_acknowledgement || a.related_document) {
          <label class="field"><span>Action required (shown to tenants)</span><input name="at" [(ngModel)]="a.action_text" placeholder="e.g. Please read and acknowledge the updated house rules"></label>
        }
        <div class="form-grid">
          <label class="field"><span>Publish at (blank = when you click Publish)</span><input type="datetime-local" name="pa" [(ngModel)]="a.publish_at"></label>
          <label class="field"><span>Expires (hidden from portal after)</span><input type="datetime-local" name="ex" [(ngModel)]="a.expires_at"></label>
        </div>
        <label class="check"><input type="checkbox" name="it" [(ngModel)]="a.is_template"> Save as a reusable notice (template)</label>
      </div>

      <div class="stack">
        <div class="card card-pad">
          <h3>Who should receive this?</h3>
          @for (o of audienceOptions(); track o[0]) {
            <label class="check"><input type="radio" name="aud" [value]="o[0]" [(ngModel)]="a.audience"> {{ o[1] }}</label>
          }
          @switch (a.audience) {
            @case ('properties') {
              <div class="pick">@for (p of auth.me()?.assigned_properties; track p.id) {
                <label class="check"><input type="checkbox" [checked]="has('property_ids', p.id)" (change)="toggle('property_ids', p.id)"> {{ p.name }}</label> }</div>
            }
            @case ('buildings') {
              <div class="pick">@for (b of buildings(); track b.id) {
                <label class="check"><input type="checkbox" [checked]="has('building_ids', b.id)" (change)="toggle('building_ids', b.id)"> {{ b.property_name }} – {{ b.name }}</label> }
                @if (!buildings().length) { <p class="muted small">No buildings defined.</p> }</div>
            }
            @case ('tenants') {
              <input placeholder="Filter tenants…" [ngModel]="tenantFilter()" (ngModelChange)="tenantFilter.set($event)" name="tf">
              <div class="pick">@for (t of filteredTenants(); track t.id) {
                <label class="check"><input type="checkbox" [checked]="has('tenant_ids', t.id)" (change)="toggle('tenant_ids', t.id)"> {{ t.full_name }} <span class="muted small">{{ t.current_tenancy?.unit_label }} {{ t.current_tenancy?.property_name }}</span></label> }</div>
              <small class="muted">{{ a.tenant_ids.length }} selected</small>
            }
            @case ('staff') {
              <div class="pick">@for (s of staff(); track s.id) {
                <label class="check"><input type="checkbox" [checked]="has('staff_ids', s.id)" (change)="toggle('staff_ids', s.id)"> {{ s.full_name }} <span class="muted small">{{ s.role }}</span></label> }</div>
            }
          }
          @if (a.audience === 'all_tenants') { <div class="alert alert-warn small">Every active tenant in the portfolio will receive this notice.</div> }
        </div>
        <div class="card card-pad">
          <h3>Delivery channels</h3>
          <label class="check"><input type="checkbox" checked disabled> Tenant portal (always)</label>
          <label class="check"><input type="checkbox" name="se" [(ngModel)]="a.send_email"> Email</label>
          <label class="check"><input type="checkbox" name="ss" [(ngModel)]="a.send_sms"> SMS (short alert + link)</label>
          <label class="check"><input type="checkbox" name="sw" [(ngModel)]="a.send_whatsapp"> WhatsApp (short alert + link)</label>
          <small class="muted">Tenants' own communication preferences are respected. Channels without a configured provider are logged only.</small>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn" [disabled]="busy()">Save draft</button>
          @if (!a.is_template) { <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="save(true)">{{ a.publish_at ? 'Schedule' : 'Publish now' }}</button> }
        </div>
      </div>
    </form>
    }`,
  styles: `.pick { max-height: 260px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin: 8px 0; }`,
})
export class AnnouncementFormPage {
  private api = inject(Api);
  private ui = inject(Ui);
  private router = inject(Router);
  auth = inject(Auth);
  id = input<string>();
  loading = signal(false);
  busy = signal(false);
  error = signal('');
  buildings = signal<any[]>([]);
  tenants = signal<any[]>([]);
  staff = signal<any[]>([]);
  documents = signal<any[]>([]);
  tenantFilter = signal('');
  filteredTenants = computed(() => {
    const f = this.tenantFilter().toLowerCase();
    return this.tenants().filter((t) => !f || `${t.full_name} ${t.current_tenancy?.unit_label ?? ''} ${t.current_tenancy?.property_name ?? ''}`.toLowerCase().includes(f));
  });
  audienceOptions = computed(() => {
    const opts = [['properties', 'Tenants in selected properties'], ['buildings', 'Tenants in selected buildings / blocks'],
      ['tenants', 'Specific tenants'], ['staff', 'Selected staff members']];
    return this.auth.me()?.portfolio_access ? [['all_tenants', 'All active tenants (whole portfolio)'], ...opts] : opts;
  });
  a: any = {
    title: '', body: '', priority: 'normal', audience: 'properties', property_ids: [], building_ids: [], tenant_ids: [], staff_ids: [],
    requires_acknowledgement: false, action_text: '', related_document: null, send_email: true, send_sms: false, send_whatsapp: false,
    publish_at: '', expires_at: '', is_template: false,
  };

  async ngOnInit() {
    this.loading.set(true);
    const [buildings, tenants, staff, docs] = await Promise.all([
      this.api.all('buildings/', { is_archived: 'false' }), this.api.all('tenants/', { status: 'active' }),
      this.api.getP('staff-options/'), this.api.all('documents/', { status: 'approved' }),
    ]);
    const props = new Map((this.auth.me()?.assigned_properties ?? []).map((p) => [p.id, p.name]));
    this.buildings.set(buildings.map((b: any) => ({ ...b, property_name: props.get(b.property) ?? '' })));
    this.tenants.set(tenants);
    this.staff.set(staff);
    this.documents.set(docs);
    if (this.id()) {
      const a = await this.api.getP(`announcements/${this.id()}/`);
      if (a.status === 'published' || a.status === 'archived') {
        this.ui.error('Published notices cannot be edited. Duplicate it instead.');
        this.router.navigate(['/management/announcements', this.id()]);
        return;
      }
      this.a = { ...a, publish_at: a.publish_at ? a.publish_at.slice(0, 16) : '', expires_at: a.expires_at ? a.expires_at.slice(0, 16) : '' };
    }
    this.loading.set(false);
  }

  has(key: string, id: number) {
    return this.a[key].includes(id);
  }
  toggle(key: string, id: number) {
    this.a[key] = this.has(key, id) ? this.a[key].filter((x: number) => x !== id) : [...this.a[key], id];
  }

  async save(publish: boolean) {
    this.busy.set(true);
    this.error.set('');
    const body: any = {
      title: this.a.title, body: this.a.body, priority: this.a.priority, audience: this.a.audience,
      property_ids: this.a.property_ids, building_ids: this.a.building_ids, tenant_ids: this.a.tenant_ids, staff_ids: this.a.staff_ids,
      requires_acknowledgement: this.a.requires_acknowledgement, action_text: this.a.action_text, related_document: this.a.related_document,
      send_email: this.a.send_email, send_sms: this.a.send_sms, send_whatsapp: this.a.send_whatsapp, is_template: this.a.is_template,
      publish_at: this.a.publish_at ? new Date(this.a.publish_at).toISOString() : null,
      expires_at: this.a.expires_at ? new Date(this.a.expires_at).toISOString() : null,
    };
    try {
      const saved = this.id() ? await this.api.patchP(`announcements/${this.id()}/`, body) : await this.api.postP('announcements/', body);
      if (publish) {
        const ok = await this.ui.confirm({
          title: body.publish_at ? 'Schedule this notice?' : 'Publish now?',
          message: body.publish_at ? 'It will be sent automatically at the scheduled time.' : 'Recipients will be notified immediately. Published notices cannot be edited.',
          confirmText: body.publish_at ? 'Schedule' : 'Publish',
        });
        if (ok) {
          const r = await this.api.postP(`announcements/${saved.id}/publish/`);
          this.ui.toast(r.status === 'scheduled' ? 'Notice scheduled.' : `Published to ${r.stats.recipients} recipient(s).`);
        }
      } else {
        this.ui.toast('Saved.');
      }
      this.router.navigate(['/management/announcements', saved.id]);
    } catch (e) {
      this.error.set(parseError(e).message);
      window.scrollTo({ top: 0 });
    } finally {
      this.busy.set(false);
    }
  }
}
