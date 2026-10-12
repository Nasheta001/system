import { Component, inject, input, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { BotGuard } from '../../shared/bot-guard';
import { Icon } from '../../shared/ui';

@Component({
  imports: [ReactiveFormsModule, RouterLink, Icon, BotGuard],
  template: `
    <div class="pub-wrap narrow-page wide">
      @if (p()) { <a [routerLink]="['/properties', p()]" class="back-link"><app-icon name="left" [size]="16" /> Back to property</a> }
      <div class="card card-pad">
        @if (reference()) {
          <div class="success-box">
            <span class="f-icon"><app-icon name="check" /></span>
            <h1>Application received</h1>
            <p>Your reference number is</p>
            <div class="ref">{{ reference() }}</div>
            <p class="muted">Keep this reference. You can check your application status at any time using it and your email address.
              Submitting an application does not reserve the unit – our team will contact you.</p>
            <div class="row" style="justify-content:center">
              <a class="btn btn-primary" routerLink="/application-status" [queryParams]="{ ref: reference() }">Check status</a>
              <a class="btn" routerLink="/properties">Browse more homes</a>
            </div>
          </div>
        } @else {
          <h1>Rental application</h1>
          <p class="muted">Tell us a little about yourself. We only use this information to assess your application.</p>
          @if (error()) { <div class="alert alert-error">{{ error() }}</div> }
          <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
            <div class="form-grid">
              <label class="field span-2" [class.invalid]="bad('full_name')"><span>Full name *</span><input formControlName="full_name" autocomplete="name"></label>
              <label class="field" [class.invalid]="bad('email')"><span>Email *</span><input type="email" formControlName="email" autocomplete="email">
                @if (bad('email')) { <small class="error-text">Enter a valid email.</small> }</label>
              <label class="field" [class.invalid]="bad('phone')"><span>Phone *</span><input type="tel" formControlName="phone" autocomplete="tel"></label>
              <label class="field"><span>Occupation</span><input formControlName="occupation"></label>
              <label class="field"><span>Employer / business</span><input formControlName="employer"></label>
              <label class="field"><span>Household size</span><input type="number" min="1" formControlName="household_size"></label>
              <label class="field"><span>Preferred move-in date</span><input type="date" formControlName="desired_move_in"></label>
              <label class="field span-2"><span>Anything else we should know?</span><textarea rows="3" formControlName="message"></textarea></label>
            </div>
            <label class="check" [class.text-red]="bad('consent_given')"><input type="checkbox" formControlName="consent_given">
              <span class="small">I consent to my personal data being processed to assess this application, as described in the <a routerLink="/privacy" target="_blank">privacy notice</a>.</span></label>
            <app-bot-guard (token)="captcha = $event" (honeypot)="website = $event" [resetKey]="attempts()" />
            @if (fieldErr()['unit']) { <div class="alert alert-error">{{ fieldErr()['unit'] }}</div> }
            <div class="form-actions"><button class="btn btn-primary btn-lg" [disabled]="busy()">{{ busy() ? 'Submitting…' : 'Submit application' }}</button></div>
          </form>
        }
      </div>
    </div>`,
})
export class ApplyPage {
  private api = inject(Api);
  unitId = input.required<string>();
  p = input<string>('');
  busy = signal(false);
  error = signal('');
  fieldErr = signal<Record<string, string>>({});
  reference = signal('');
  attempts = signal(0);
  captcha = '';
  website = '';
  form = inject(FormBuilder).nonNullable.group({
    full_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    phone: ['', [Validators.required, Validators.minLength(9)]],
    occupation: [''],
    employer: [''],
    household_size: [1],
    desired_move_in: [''],
    message: [''],
    consent_given: [false, Validators.requiredTrue],
  });

  bad(name: keyof typeof this.form.controls) {
    const c = this.form.controls[name];
    return c.invalid && c.touched;
  }

  async submit() {
    this.form.markAllAsTouched();
    if (this.form.invalid) {
      this.error.set('Please complete the required fields and accept the privacy notice.');
      return;
    }
    this.busy.set(true);
    this.error.set('');
    const v = this.form.getRawValue();
    try {
      const r = await this.api.postP('public/applications/', { ...v, desired_move_in: v.desired_move_in || null, unit: +this.unitId(), captcha_token: this.captcha, website: this.website });
      this.reference.set(r.reference);
    } catch (e) {
      const err = parseError(e);
      this.fieldErr.set(err.fields);
      this.error.set(err.message);
      this.attempts.update((n) => n + 1);
    } finally {
      this.busy.set(false);
    }
  }
}
