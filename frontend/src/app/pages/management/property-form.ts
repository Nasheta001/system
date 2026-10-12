import { Component, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { Ui } from '../../core/ui.service';
import { Loading, PageHeader } from '../../shared/ui';

@Component({
  imports: [ReactiveFormsModule, PageHeader, Loading],
  template: `
    <app-page-header [title]="id() ? 'Edit property' : 'Add a property'" [back]="id() ? ['/management/properties', id()] : '/management/properties'" />
    @if (loading()) { <app-loading /> } @else {
    <form class="card card-pad" [formGroup]="form" (ngSubmit)="save()" novalidate style="max-width:900px">
      @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
      <div class="form-section">
        <h3>Basic details</h3>
        <div class="form-grid">
          <label class="field" [class.invalid]="err('name')"><span>Property name *</span><input formControlName="name">
            @if (err('name')) { <small class="error-text">{{ err('name') }}</small> }</label>
          <label class="field"><span>Property type</span>
            <select formControlName="property_type">
              @for (t of types; track t[0]) { <option [value]="t[0]">{{ t[1] }}</option> }
            </select></label>
          <label class="field span-2"><span>Description (shown on the public website)</span><textarea rows="4" formControlName="description"></textarea></label>
        </div>
      </div>
      <div class="form-section">
        <h3>Location</h3>
        <div class="form-grid">
          <label class="field span-2" [class.invalid]="err('address')"><span>Street address *</span><input formControlName="address">
            @if (err('address')) { <small class="error-text">{{ err('address') }}</small> }</label>
          <label class="field" [class.invalid]="err('county')"><span>County *</span><input formControlName="county" list="counties"></label>
          <label class="field" [class.invalid]="err('town')"><span>Town *</span><input formControlName="town"></label>
          <label class="field"><span>Neighbourhood / estate</span><input formControlName="neighbourhood"></label>
          <label class="field" [class.invalid]="err('map_url')"><span>Google Maps link</span><input formControlName="map_url" placeholder="https://maps.google.com/…">
            @if (err('map_url')) { <small class="error-text">{{ err('map_url') }}</small> }</label>
          <label class="field"><span>Latitude</span><input type="number" step="any" formControlName="latitude"></label>
          <label class="field"><span>Longitude</span><input type="number" step="any" formControlName="longitude"></label>
        </div>
        <datalist id="counties">@for (c of counties; track c) { <option [value]="c"></option> }</datalist>
      </div>
      <div class="form-section">
        <h3>Contact & terms</h3>
        <div class="form-grid">
          <label class="field"><span>Contact phone</span><input formControlName="contact_phone"></label>
          <label class="field"><span>Contact email</span><input type="email" formControlName="contact_email"></label>
          <label class="field"><span>WhatsApp number</span><input formControlName="whatsapp" placeholder="2547XXXXXXXX"></label>
          <label class="check" style="align-self:end"><input type="checkbox" formControlName="is_featured"> Feature on the homepage</label>
          <label class="field span-2"><span>Rent terms (public)</span><textarea rows="3" formControlName="rent_terms" placeholder="Deposit, due date, utilities…"></textarea></label>
        </div>
      </div>
      <div class="form-section">
        <h3>Amenities</h3>
        <div class="chips">
          @for (a of amenities(); track a.id) {
            <span class="chip" [class.selected]="selected().has(a.id)" (click)="toggle(a.id)" role="checkbox" [attr.aria-checked]="selected().has(a.id)" tabindex="0" (keydown.enter)="toggle(a.id)">{{ a.name }}</span>
          }
        </div>
        @if (auth.can('manage_properties')) {
          <div class="row mt"><input #na placeholder="Add a new amenity" style="max-width:260px"><button type="button" class="btn btn-sm" (click)="addAmenity(na.value); na.value=''">Add</button></div>
        }
      </div>
      <div class="form-actions">
        <button type="button" class="btn" (click)="cancel()">Cancel</button>
        <button class="btn btn-primary" [disabled]="busy()">{{ busy() ? 'Saving…' : (id() ? 'Save changes' : 'Create property') }}</button>
      </div>
    </form>
    }`,
})
export class PropertyFormPage {
  private api = inject(Api);
  private router = inject(Router);
  private ui = inject(Ui);
  auth = inject(Auth);
  id = input<string>();
  loading = signal(false);
  busy = signal(false);
  error = signal('');
  fieldErrors = signal<Record<string, string>>({});
  amenities = signal<any[]>([]);
  selected = signal(new Set<number>());
  types = [['apartments', 'Apartment block'], ['bedsitters', 'Bedsitter / studio block'], ['mixed_use', 'Mixed-use'],
    ['maisonettes', 'Maisonettes / townhouses'], ['commercial', 'Commercial']];
  counties = ['Nairobi', 'Mombasa', 'Kiambu', 'Nakuru', 'Kisumu', 'Machakos', 'Kajiado', 'Uasin Gishu', 'Kilifi', 'Nyeri',
    'Meru', 'Kakamega', 'Murang\'a', 'Embu', 'Laikipia', 'Kwale', 'Bungoma', 'Kericho', 'Kisii', 'Nyandarua'];
  form = inject(FormBuilder).group({
    name: ['', Validators.required], property_type: ['apartments'], description: [''],
    address: ['', Validators.required], county: ['', Validators.required], town: ['', Validators.required],
    neighbourhood: [''], map_url: [''], latitude: [null as number | null], longitude: [null as number | null],
    contact_phone: [''], contact_email: [''], whatsapp: [''], rent_terms: [''], is_featured: [false],
  });

  async ngOnInit() {
    this.amenities.set(await this.api.getP('amenities/'));
    if (this.id()) {
      this.loading.set(true);
      const p = await this.api.getP(`properties/${this.id()}/`);
      this.form.patchValue(p);
      this.selected.set(new Set(p.amenities.map((a: any) => a.id)));
      this.loading.set(false);
    }
  }

  err(name: string) {
    const c = this.form.get(name);
    if (this.fieldErrors()[name]) return this.fieldErrors()[name];
    return c && c.invalid && c.touched ? 'This field is required.' : '';
  }

  toggle(id: number) {
    const s = new Set(this.selected());
    s.has(id) ? s.delete(id) : s.add(id);
    this.selected.set(s);
  }

  async addAmenity(name: string) {
    if (!name.trim()) return;
    try {
      const a = await this.api.postP('amenities/', { name: name.trim() });
      this.amenities.update((l) => [...l, a]);
      this.toggle(a.id);
    } catch (e) {
      this.ui.error(parseError(e).message);
    }
  }

  cancel() {
    this.router.navigate(this.id() ? ['/management/properties', this.id()] : ['/management/properties']);
  }

  async save() {
    this.form.markAllAsTouched();
    if (this.form.invalid) return;
    this.busy.set(true);
    this.error.set('');
    this.fieldErrors.set({});
    const v: any = { ...this.form.getRawValue(), amenity_ids: [...this.selected()] };
    for (const k of ['latitude', 'longitude']) if (v[k] === '' || v[k] === undefined) v[k] = null;
    try {
      const p = this.id() ? await this.api.patchP(`properties/${this.id()}/`, v) : await this.api.postP('properties/', v);
      this.ui.toast(this.id() ? 'Property updated.' : 'Property created. Now add buildings and units.');
      this.router.navigate(['/management/properties', p.id]);
    } catch (e) {
      const err = parseError(e);
      this.fieldErrors.set(err.fields);
      this.error.set(err.message);
    } finally {
      this.busy.set(false);
    }
  }
}
