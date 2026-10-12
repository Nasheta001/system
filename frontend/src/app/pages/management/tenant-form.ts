import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { KesPipe, today } from '../../core/format';
import { Ui } from '../../core/ui.service';
import { PageHeader } from '../../shared/ui';

@Component({
  imports: [FormsModule, PageHeader, KesPipe],
  template: `
    <app-page-header title="Register a tenant" subtitle="Create the tenant record and, optionally, move them into a vacant unit." back="/management/tenants" backLabel="Tenants" />
    <form class="card card-pad" (ngSubmit)="save()" style="max-width:900px">
      @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
      <div class="form-section"><h3>Personal details</h3>
        <div class="form-grid">
          <label class="field" [class.invalid]="fe()['first_name']"><span>First name *</span><input name="fn" [(ngModel)]="t.first_name" required></label>
          <label class="field" [class.invalid]="fe()['last_name']"><span>Last name *</span><input name="ln" [(ngModel)]="t.last_name" required></label>
          <label class="field" [class.invalid]="fe()['phone']"><span>Phone *</span><input name="ph" type="tel" [(ngModel)]="t.phone" required placeholder="07XX XXX XXX"></label>
          <label class="field" [class.invalid]="fe()['email']"><span>Email</span><input name="em" type="email" [(ngModel)]="t.email">
            @if (fe()['email']) { <small class="error-text">{{ fe()['email'] }}</small> }</label>
          <label class="field"><span>National ID / passport</span><input name="id" [(ngModel)]="t.id_number"><small>Restricted – visible to managers only.</small></label>
          <label class="field"><span>Occupation</span><input name="oc" [(ngModel)]="t.occupation"></label>
        </div>
      </div>
      <div class="form-section"><h3>Emergency contact</h3>
        <div class="form-grid-3">
          <label class="field"><span>Name</span><input name="ecn" [(ngModel)]="t.emergency_contact_name"></label>
          <label class="field"><span>Phone</span><input name="ecp" [(ngModel)]="t.emergency_contact_phone"></label>
          <label class="field"><span>Relationship</span><input name="ecr" [(ngModel)]="t.emergency_contact_relationship"></label>
        </div>
      </div>
      <div class="form-section"><h3>Communication</h3>
        <div class="row"><label class="check"><input type="checkbox" name="ns" [(ngModel)]="t.notify_sms"> SMS</label>
          <label class="check"><input type="checkbox" name="ne" [(ngModel)]="t.notify_email"> Email</label>
          <label class="check"><input type="checkbox" name="nw" [(ngModel)]="t.notify_whatsapp"> WhatsApp</label></div>
        <label class="check"><input type="checkbox" name="pa" [(ngModel)]="t.create_portal_account" [disabled]="!t.unit"> Email a tenant portal invitation (requires email and a unit below)</label>
        @if (!t.unit) { <p class="muted small">Portal invitations are only sent to tenants with a current tenancy. Assign a unit, or invite them from their page after move-in.</p> }
      </div>
      <div class="form-section"><h3>Assign to a unit (optional)</h3>
        <div class="form-grid">
          <label class="field"><span>Property</span><select name="prop" [(ngModel)]="propertyId" (ngModelChange)="loadUnits()"><option value="">— Do not assign now —</option>
            @for (p of auth.me()?.assigned_properties; track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></label>
          <label class="field"><span>Vacant unit</span><select name="unit" [(ngModel)]="t.unit" (ngModelChange)="unitChanged()" [disabled]="!propertyId">
            <option [ngValue]="null">— Select —</option>
            @for (u of units(); track u.id) { <option [ngValue]="u.id">{{ u.label }} · {{ u.unit_type_name }} · {{ u.rent_amount | kes }}</option> }</select>
            @if (propertyId && !units().length) { <small>No available units in this property.</small> }</label>
          @if (t.unit) {
            <label class="field"><span>Tenancy start date *</span><input type="date" name="sd" [(ngModel)]="t.start_date" required></label>
            <label class="field"><span>Expected end date</span><input type="date" name="ed" [(ngModel)]="t.expected_end_date"></label>
            <label class="field"><span>Monthly rent (KES)</span><input type="number" name="mr" [(ngModel)]="t.monthly_rent"></label>
            <label class="field"><span>Deposit (KES)</span><input type="number" name="dp" [(ngModel)]="t.deposit_amount"></label>
            <label class="field"><span>Rent due day</span><input type="number" min="1" max="28" name="dd" [(ngModel)]="t.rent_due_day"></label>
          }
        </div>
        @if (t.unit) { <p class="muted small">Rent is charged monthly from the start date; the deposit is added to the tenant's account. Reserved units must be converted from the Applications page.</p> }
      </div>
      <label class="check"><input type="checkbox" name="consent" [(ngModel)]="consent"> The tenant has been informed how their personal data will be used (privacy notice).</label>
      <div class="form-actions"><button type="button" class="btn" (click)="router.navigate(['/management/tenants'])">Cancel</button>
        <button class="btn btn-primary" [disabled]="busy() || !t.first_name || !t.last_name || !t.phone">{{ busy() ? 'Saving…' : 'Register tenant' }}</button></div>
    </form>`,
})
export class TenantFormPage {
  private api = inject(Api);
  private ui = inject(Ui);
  router = inject(Router);
  auth = inject(Auth);
  busy = signal(false);
  error = signal('');
  fe = signal<Record<string, string>>({});
  units = signal<any[]>([]);
  propertyId = '';
  consent = true;
  t: any = {
    first_name: '', last_name: '', phone: '', email: '', id_number: '', occupation: '', emergency_contact_name: '',
    emergency_contact_phone: '', emergency_contact_relationship: '', notify_sms: true, notify_email: true,
    notify_whatsapp: false, create_portal_account: true, unit: null, start_date: today(), expected_end_date: null,
    monthly_rent: null, deposit_amount: null, rent_due_day: null,
  };

  constructor() {
    const q = inject(ActivatedRoute).snapshot.queryParams;
    if (q['property']) {
      this.propertyId = q['property'];
      this.loadUnits().then(() => {
        if (q['unit']) {
          this.t.unit = +q['unit'];
          this.unitChanged();
        }
      });
    }
  }

  async loadUnits() {
    this.t.unit = null;
    this.units.set(this.propertyId ? await this.api.all('units/', { property: this.propertyId, status: 'available' }) : []);
  }

  unitChanged() {
    const u = this.units().find((x) => x.id === this.t.unit);
    if (u) {
      this.t.monthly_rent = u.rent_amount;
      this.t.deposit_amount = u.deposit_amount;
      this.t.rent_due_day = u.rent_due_day;
    }
  }

  async save() {
    this.busy.set(true);
    this.error.set('');
    this.fe.set({});
    const body: any = { ...this.t, data_consent_at: this.consent ? new Date().toISOString() : null };
    if (!body.unit) for (const k of ['unit', 'start_date', 'expected_end_date', 'monthly_rent', 'deposit_amount', 'rent_due_day']) delete body[k];
    for (const k of Object.keys(body)) if (body[k] === null || body[k] === '') if (['expected_end_date', 'monthly_rent', 'deposit_amount', 'rent_due_day'].includes(k)) delete body[k];
    if (!body.create_portal_account || !body.unit) body.create_portal_account = false;
    try {
      const r = await this.api.postP('tenants/', body);
      this.ui.toast(body.unit ? 'Tenant registered and moved in.' : 'Tenant registered.');
      this.router.navigate(['/management/tenants', r.id]);
    } catch (e) {
      const err = parseError(e);
      this.fe.set(err.fields);
      this.error.set(err.message);
    } finally {
      this.busy.set(false);
    }
  }
}
