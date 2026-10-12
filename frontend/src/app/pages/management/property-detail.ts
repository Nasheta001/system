import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { toFormData } from '../../shared/list';
import { Badge, Empty, Icon, Loading, Modal, PageHeader, Stat } from '../../shared/ui';

const UNIT_STATUSES = ['available', 'maintenance', 'unavailable'];

@Component({
  imports: [FormsModule, RouterLink, DatePipe, KesPipe, Badge, Empty, Icon, Loading, Modal, PageHeader, Stat],
  template: `
    @if (!p()) { <app-loading /> } @else {
      <app-page-header [title]="p().name" [subtitle]="p().address + ', ' + p().town + ', ' + p().county" back="/management/properties" backLabel="Properties">
        @if (canEdit()) {
          @if (p().status === 'active') {
            @if (p().is_published) { <button class="btn" (click)="act('unpublish', 'Property hidden from the website.')"><app-icon name="eye" /> Unpublish</button> }
            @else { <button class="btn" (click)="act('publish', 'Property published on the website.')"><app-icon name="eye" /> Publish</button> }
            <a class="btn" [routerLink]="['/management/properties', p().id, 'edit']"><app-icon name="edit" /> Edit</a>
            @if (auth.can('create_properties')) { <button class="btn btn-ghost" (click)="archive()"><app-icon name="archive" /> Archive</button> }
          } @else {
            <button class="btn" (click)="act('restore', 'Property restored.')">Restore</button>
          }
        }
      </app-page-header>

      <div class="row mb">
        @if (p().status === 'archived') { <app-badge value="archived" /> }
        @else if (p().is_published) { <app-badge value="published" text="Live on website" /> <a [href]="'/properties/' + p().slug" target="_blank" class="small">View public page ↗</a> }
        @else { <app-badge value="draft" text="Not on website" /> }
      </div>

      <div class="grid-4 mb">
        <app-stat label="Units" [value]="p().stats.total_units" icon="layers" />
        <app-stat label="Occupied" [value]="p().stats.occupied" [hint]="p().stats.occupancy_rate + '% occupancy'" icon="users" tone="blue" />
        <app-stat label="Available" [value]="p().stats.available" [hint]="p().stats.reserved + ' reserved'" icon="door" tone="amber" />
        <app-stat label="Maintenance / unavailable" [value]="p().stats.maintenance + p().stats.unavailable" icon="wrench" tone="clay" />
      </div>

      <div class="tabs" role="tablist">
        @for (t of tabs; track t[0]) {
          <button class="tab" [class.active]="tab() === t[0]" (click)="tab.set(t[0])" role="tab">{{ t[1] }}
            @if (t[0] === 'units') { <span class="count">{{ units().length }}</span> }
            @if (t[0] === 'buildings') { <span class="count">{{ p().buildings.length }}</span> }
            @if (t[0] === 'photos') { <span class="count">{{ p().photos.length }}</span> }</button>
        }
      </div>

      @switch (tab()) {
        @case ('units') {
          <div class="card">
            <div class="toolbar">
              <select [ngModel]="unitFilter()" (ngModelChange)="unitFilter.set($event)" aria-label="Status filter"><option value="">All statuses</option>
                @for (s of ['available','reserved','occupied','maintenance','unavailable']; track s) { <option [value]="s">{{ s }}</option> }</select>
              @if (p().buildings.length) {
                <select [ngModel]="buildingFilter()" (ngModelChange)="buildingFilter.set($event)" aria-label="Building filter"><option value="">All buildings</option>
                  @for (b of p().buildings; track b.id) { <option [value]="b.id">{{ b.name }}</option> }</select>
              }
              <label class="check small" style="margin:0"><input type="checkbox" [(ngModel)]="showArchived" (change)="loadUnits()"> Show archived</label>
              <span style="flex:1"></span>
              @if (canEdit() && p().status === 'active') { <button class="btn btn-primary btn-sm" (click)="editUnit(null)"><app-icon name="plus" /> Add unit</button> }
            </div>
            @if (!filteredUnits().length) {
              <app-empty icon="door" title="No units yet" text="Add units with their rent, deposit and due day. Then mark them as listed to advertise vacancies.">
                @if (canEdit()) { <button class="btn btn-primary" (click)="editUnit(null)">Add first unit</button> }
              </app-empty>
            } @else {
              <div class="table-wrap"><table class="table responsive">
                <thead><tr><th>Unit</th><th>Type</th><th class="num">Rent</th><th class="num">Deposit</th><th>Status</th><th>Tenant</th><th>Website</th><th></th></tr></thead>
                <tbody>@for (u of filteredUnits(); track u.id) {
                  <tr>
                    <td data-label="Unit" class="strong">{{ u.label }}<span class="sub">Floor {{ u.floor }}</span></td>
                    <td data-label="Type">{{ u.unit_type_name }}<span class="sub">{{ u.bedrooms }} bd · {{ u.bathrooms }} ba</span></td>
                    <td data-label="Rent" class="num">{{ u.rent_amount | kes }}<span class="sub">due day {{ u.rent_due_day }}</span></td>
                    <td data-label="Deposit" class="num">{{ u.deposit_amount | kes }}</td>
                    <td data-label="Status">@if (u.is_archived) { <app-badge value="archived" /> } @else { <app-badge [value]="u.status" /> }</td>
                    <td data-label="Tenant">@if (u.current_tenant) { <a [routerLink]="['/management/tenants', u.current_tenant.tenant_id]">{{ u.current_tenant.name }}</a> } @else { <span class="muted">—</span> }</td>
                    <td data-label="Website">@if (u.is_listed && u.status === 'available' && p().is_published) { <app-badge value="published" text="Listed" /> } @else if (u.is_listed) { <span class="muted small">Listed when vacant</span> } @else { <span class="muted small">Hidden</span> }</td>
                    <td class="actions">
                      @if (canEdit()) {
                        <button class="btn btn-sm btn-ghost" (click)="editUnit(u)">Edit</button>
                        @if (!u.is_archived && u.status !== 'occupied' && u.status !== 'reserved') { <button class="btn btn-sm btn-ghost" (click)="archiveUnit(u)">Archive</button> }
                        @if (u.is_archived) { <button class="btn btn-sm btn-ghost" (click)="restoreUnit(u)">Restore</button> }
                      }
                    </td>
                  </tr>
                }</tbody></table></div>
            }
          </div>
        }
        @case ('buildings') {
          <div class="card">
            <div class="card-head"><h2>Buildings & blocks</h2>@if (canEdit()) { <button class="btn btn-sm btn-primary" (click)="editBuilding(null)"><app-icon name="plus" /> Add building</button> }</div>
            @if (!p().buildings.length) { <app-empty icon="building" title="No buildings" text="Optional: use buildings or blocks if this property has more than one structure." /> }
            @else {
              <ul class="list">@for (b of p().buildings; track b.id) {
                <li class="row-between"><span><b>{{ b.name }}</b> <span class="muted small">· {{ b.floors }} floor(s) · {{ b.unit_count }} units</span> @if (b.is_archived) { <app-badge value="archived" /> }</span>
                  @if (canEdit()) { <span><button class="btn btn-sm btn-ghost" (click)="editBuilding(b)">Edit</button>
                    @if (!b.unit_count) { <button class="btn btn-sm btn-ghost" (click)="deleteBuilding(b)">Delete</button> }</span> }</li>
              }</ul>
            }
          </div>
        }
        @case ('photos') {
          <div class="card card-pad">
            @if (canEdit()) {
              <div class="row mb"><label class="btn"><app-icon name="upload" /> Upload photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden (change)="upload($event)"></label>
                <span class="muted small">JPG, PNG or WEBP up to 10 MB. The cover photo is shown first on the website.</span></div>
            }
            @if (!p().photos.length) { <app-empty icon="building" title="No photos yet" text="Good photos help vacancies let faster." /> }
            <div class="photo-grid">@for (ph of p().photos; track ph.id) {
              <figure><img [src]="ph.url" [alt]="ph.caption">
                <figcaption>@if (ph.is_cover) { <app-badge value="active" text="Cover" /> }
                  @if (canEdit()) { @if (!ph.is_cover) { <button class="btn btn-sm btn-ghost" (click)="cover(ph)">Make cover</button> }
                    <button class="btn btn-sm btn-ghost" (click)="deletePhoto(ph)">Delete</button> }</figcaption></figure>
            }</div>
          </div>
        }
        @case ('ownership') {
          <div class="card">
            <div class="card-head"><h2>Ownership & management history</h2>@if (auth.can('create_properties')) { <button class="btn btn-sm btn-primary" (click)="owner = { arrangement: 'owned', start_date: '' }; ownerOpen.set(true)"><app-icon name="plus" /> Add record</button> }</div>
            @if (!p().ownership_records.length) { <app-empty icon="key" title="No ownership records" /> }
            <div class="table-wrap"><table class="table responsive">
              @if (p().ownership_records.length) { <thead><tr><th>Owner</th><th>Arrangement</th><th>From</th><th>To</th><th>Fee</th></tr></thead> }
              <tbody>@for (o of p().ownership_records; track o.id) {
                <tr><td data-label="Owner">{{ o.owner_name }}<span class="sub">{{ o.owner_phone }} {{ o.owner_email }}</span></td><td data-label="Arrangement">{{ o.arrangement }}</td>
                  <td data-label="From">{{ o.start_date | date: 'mediumDate' }}</td><td data-label="To">{{ o.end_date ? (o.end_date | date: 'mediumDate') : 'Current' }}</td>
                  <td data-label="Fee">{{ o.management_fee_percent ? o.management_fee_percent + '%' : '—' }}</td></tr>
              }</tbody></table></div>
          </div>
        }
        @case ('overview') {
          <div class="grid-2">
            <div class="card card-pad"><h3>Description</h3><p style="white-space:pre-line">{{ p().description || '—' }}</p>
              <h3>Amenities</h3><div class="chips">@for (a of p().amenities; track a.id) { <span class="chip">{{ a.name }}</span> } @empty { <span class="muted">None listed</span> }</div></div>
            <div class="card card-pad"><dl class="kv">
              <dt>Type</dt><dd>{{ p().property_type }}</dd><dt>Neighbourhood</dt><dd>{{ p().neighbourhood || '—' }}</dd>
              <dt>Contact phone</dt><dd>{{ p().contact_phone || '—' }}</dd><dt>Contact email</dt><dd>{{ p().contact_email || '—' }}</dd>
              <dt>WhatsApp</dt><dd>{{ p().whatsapp || '—' }}</dd><dt>Map</dt><dd>@if (p().map_url) { <a [href]="p().map_url" target="_blank" rel="noopener">Open map</a> } @else { — }</dd>
              <dt>Rent terms</dt><dd style="white-space:pre-line">{{ p().rent_terms || '—' }}</dd><dt>Created</dt><dd>{{ p().created_at | date: 'mediumDate' }}</dd>
            </dl></div>
          </div>
        }
      }

      <app-modal [(open)]="unitOpen" [title]="unit.id ? 'Edit unit ' + unit.unit_number : 'Add unit'" [wide]="true">
        <form (ngSubmit)="saveUnit()">
          @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
          <div class="form-grid-3">
            <label class="field"><span>Unit number *</span><input name="un" [(ngModel)]="unit.unit_number" required></label>
            <label class="field"><span>Building / block</span><select name="b" [(ngModel)]="unit.building"><option [ngValue]="null">— None —</option>
              @for (b of p().buildings; track b.id) { <option [ngValue]="b.id">{{ b.name }}</option> }</select></label>
            <label class="field"><span>Unit type *</span><select name="ut" [(ngModel)]="unit.unit_type" (ngModelChange)="typeChanged($event)" required>
              @for (t of unitTypes(); track t.id) { <option [ngValue]="t.id">{{ t.name }}</option> }</select></label>
            <label class="field"><span>Floor</span><input type="number" name="fl" [(ngModel)]="unit.floor"></label>
            <label class="field"><span>Bedrooms</span><input type="number" min="0" name="bd" [(ngModel)]="unit.bedrooms"></label>
            <label class="field"><span>Bathrooms</span><input type="number" min="0" name="ba" [(ngModel)]="unit.bathrooms"></label>
            <label class="field"><span>Monthly rent (KES) *</span><input type="number" min="0" name="r" [(ngModel)]="unit.rent_amount" required></label>
            <label class="field"><span>Deposit (KES)</span><input type="number" min="0" name="d" [(ngModel)]="unit.deposit_amount"></label>
            <label class="field"><span>Service charge (KES/month)</span><input type="number" min="0" name="sc" [(ngModel)]="unit.service_charge"></label>
            <label class="field"><span>Rent due day (1–28)</span><input type="number" min="1" max="28" name="dd" [(ngModel)]="unit.rent_due_day"></label>
            <label class="field"><span>Size (m²)</span><input type="number" min="0" name="sz" [(ngModel)]="unit.size_sqm"></label>
            <label class="field"><span>Status</span>
              @if (unit.status === 'occupied' || unit.status === 'reserved') { <input [value]="unit.status" disabled><small>Managed by tenancy / reservation workflows</small> }
              @else { <select name="st" [(ngModel)]="unit.status">@for (s of statuses; track s) { <option [value]="s">{{ s }}</option> }</select> }</label>
            <label class="field span-3"><span>Payment terms</span><input name="pt" [(ngModel)]="unit.payment_terms"></label>
            <label class="field span-3"><span>Listing description (public)</span><textarea rows="2" name="ld" [(ngModel)]="unit.listing_description"></textarea></label>
            <label class="field"><span>Available from</span><input type="date" name="af" [(ngModel)]="unit.available_from"></label>
          </div>
          <label class="check"><input type="checkbox" name="il" [(ngModel)]="unit.is_listed"> Approved for public listing (shown on the website whenever it is available)</label>
          <div class="form-actions"><button type="button" class="btn" (click)="unitOpen.set(false)">Cancel</button><button class="btn btn-primary" [disabled]="busy()">Save unit</button></div>
        </form>
      </app-modal>

      <app-modal [(open)]="buildingOpen" [title]="building.id ? 'Edit building' : 'Add building'">
        <form (ngSubmit)="saveBuilding()">
          @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
          <label class="field"><span>Name *</span><input name="n" [(ngModel)]="building.name" placeholder="e.g. Block A" required></label>
          <label class="field"><span>Floors</span><input type="number" min="1" name="f" [(ngModel)]="building.floors"></label>
          <label class="field"><span>Description</span><textarea name="d" rows="2" [(ngModel)]="building.description"></textarea></label>
          @if (building.id) { <label class="check"><input type="checkbox" name="a" [(ngModel)]="building.is_archived"> Archived</label> }
          <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
        </form>
      </app-modal>

      <app-modal [(open)]="ownerOpen" title="Ownership record">
        <form (ngSubmit)="saveOwner()">
          @if (formErr()) { <div class="alert alert-error">{{ formErr() }}</div> }
          <div class="form-grid">
            <label class="field span-2"><span>Owner name *</span><input name="on" [(ngModel)]="owner.owner_name" required></label>
            <label class="field"><span>Phone</span><input name="op" [(ngModel)]="owner.owner_phone"></label>
            <label class="field"><span>Email</span><input name="oe" type="email" [(ngModel)]="owner.owner_email"></label>
            <label class="field"><span>Arrangement</span><select name="ar" [(ngModel)]="owner.arrangement"><option value="owned">Owned by company</option><option value="managed">Managed for owner</option><option value="leased">Head-leased</option></select></label>
            <label class="field"><span>Management fee %</span><input type="number" step="0.01" name="mf" [(ngModel)]="owner.management_fee_percent"></label>
            <label class="field"><span>Start date *</span><input type="date" name="sd" [(ngModel)]="owner.start_date" required></label>
            <label class="field"><span>End date</span><input type="date" name="ed" [(ngModel)]="owner.end_date"></label>
          </div>
          <div class="form-actions"><button class="btn btn-primary" [disabled]="busy()">Save</button></div>
        </form>
      </app-modal>
    }`,
  styles: `
    .photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }
    figure { margin: 0; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
    figure img { width: 100%; aspect-ratio: 3/2; object-fit: cover; }
    figcaption { display: flex; gap: 4px; align-items: center; padding: 6px; flex-wrap: wrap; }
  `,
})
export class PropertyDetailPage {
  private api = inject(Api);
  private ui = inject(Ui);
  private router = inject(Router);
  auth = inject(Auth);
  id = input.required<string>();
  p = signal<any>(null);
  units = signal<any[]>([]);
  unitTypes = signal<any[]>([]);
  tab = signal('units');
  tabs = [['units', 'Units'], ['buildings', 'Buildings'], ['photos', 'Photos'], ['ownership', 'Ownership'], ['overview', 'Details']];
  statuses = UNIT_STATUSES;
  unitFilter = signal('');
  buildingFilter = signal('');
  showArchived = false;
  busy = signal(false);
  formErr = signal('');
  unitOpen = signal(false);
  buildingOpen = signal(false);
  ownerOpen = signal(false);
  unit: any = {};
  building: any = {};
  owner: any = {};
  canEdit = computed(() => this.auth.can('manage_properties'));
  filteredUnits = computed(() =>
    this.units().filter((u) => (!this.unitFilter() || u.status === this.unitFilter())
      && (!this.buildingFilter() || String(u.building) === String(this.buildingFilter()))));

  ngOnInit() {
    this.reload();
    this.api.get('unit-types/').subscribe((r) => this.unitTypes.set(r));
  }

  async reload() {
    try {
      this.p.set(await this.api.getP(`properties/${this.id()}/`));
      await this.loadUnits();
    } catch (e) {
      this.ui.error(parseError(e).message);
      this.router.navigate(['/management/properties']);
    }
  }

  async loadUnits() {
    const rows = await this.api.all('units/', { property: this.id(), is_archived: this.showArchived ? '' : 'false' });
    this.units.set(rows);
  }

  async act(action: string, msg: string) {
    try {
      this.p.set(await this.api.postP(`properties/${this.id()}/${action}/`));
      this.ui.toast(msg);
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async archive() {
    const ok = await this.ui.confirm({
      title: 'Archive this property?',
      message: 'It will be hidden from the website and active lists. All tenancy and payment history is kept. Current tenants must be moved out first.',
      confirmText: 'Archive', danger: true,
    });
    if (ok) await this.act('archive', 'Property archived.');
  }

  editUnit(u: any) {
    this.formErr.set('');
    this.unit = u ? { ...u } : {
      property: +this.id(), building: this.p().buildings[0]?.id ?? null, unit_type: this.unitTypes()[2]?.id ?? this.unitTypes()[0]?.id,
      unit_number: '', floor: 0, bedrooms: 1, bathrooms: 1, rent_amount: null, deposit_amount: null, service_charge: 0,
      rent_due_day: 5, status: 'available', is_listed: true, listing_description: '', payment_terms: '', available_from: null,
    };
    this.unitOpen.set(true);
  }

  typeChanged(id: number) {
    const t = this.unitTypes().find((x) => x.id === id);
    if (t && !this.unit.id) this.unit.bedrooms = t.bedrooms;
  }

  async saveUnit() {
    this.busy.set(true);
    this.formErr.set('');
    const body = { ...this.unit };
    if (body.deposit_amount === null || body.deposit_amount === '') body.deposit_amount = body.rent_amount;
    for (const k of ['available_from', 'size_sqm']) if (body[k] === '') body[k] = null;
    if (body.status === 'occupied' || body.status === 'reserved') delete body.status;
    delete body.current_tenant;
    try {
      if (body.id) await this.api.patchP(`units/${body.id}/`, body);
      else await this.api.postP('units/', body);
      this.unitOpen.set(false);
      this.ui.toast('Unit saved.');
      this.reload();
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async archiveUnit(u: any) {
    if (!(await this.ui.confirm({ title: `Archive unit ${u.label}?`, message: 'It will be removed from listings. History is kept.', confirmText: 'Archive', danger: true }))) return;
    try {
      await this.api.postP(`units/${u.id}/archive/`);
      this.ui.toast('Unit archived.');
      this.reload();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async restoreUnit(u: any) {
    await this.api.postP(`units/${u.id}/restore/`);
    this.ui.toast('Unit restored. Set its status to available when ready.');
    this.reload();
  }

  editBuilding(b: any) {
    this.formErr.set('');
    this.building = b ? { ...b } : { property: +this.id(), name: '', floors: 1, description: '' };
    this.buildingOpen.set(true);
  }

  async saveBuilding() {
    this.busy.set(true);
    try {
      if (this.building.id) await this.api.patchP(`buildings/${this.building.id}/`, this.building);
      else await this.api.postP('buildings/', this.building);
      this.buildingOpen.set(false);
      this.ui.toast('Building saved.');
      this.reload();
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }

  async deleteBuilding(b: any) {
    if (!(await this.ui.confirm({ title: `Delete ${b.name}?`, message: 'This building has no units.', danger: true, confirmText: 'Delete' }))) return;
    try {
      await this.api.deleteP(`buildings/${b.id}/`);
      this.reload();
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  async upload(ev: Event) {
    const files = Array.from((ev.target as HTMLInputElement).files ?? []);
    for (const [i, f] of files.entries()) {
      try {
        await this.api.postP('property-photos/', toFormData({ property: this.id(), image: f, is_cover: !this.p().photos.length && i === 0 }));
      } catch (e) {
        this.ui.error(`${f.name}: ${parseError(e).message}`);
      }
    }
    (ev.target as HTMLInputElement).value = '';
    this.ui.toast('Upload complete.');
    this.reload();
  }

  async cover(ph: any) {
    await this.api.patchP(`property-photos/${ph.id}/`, { is_cover: true });
    this.reload();
  }

  async deletePhoto(ph: any) {
    if (!(await this.ui.confirm({ title: 'Delete photo?', message: 'This cannot be undone.', danger: true, confirmText: 'Delete' }))) return;
    await this.api.deleteP(`property-photos/${ph.id}/`);
    this.reload();
  }

  async saveOwner() {
    this.busy.set(true);
    this.formErr.set('');
    const body = { ...this.owner, property: +this.id() };
    if (!body.end_date) body.end_date = null;
    if (body.management_fee_percent === '' || body.management_fee_percent === undefined) body.management_fee_percent = null;
    try {
      await this.api.postP('ownership-records/', body);
      this.ownerOpen.set(false);
      this.reload();
    } catch (e) {
      this.formErr.set(parseError(e).message);
    } finally {
      this.busy.set(false);
    }
  }
}
