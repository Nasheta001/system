import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Title } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';
import { Api, parseError } from '../../core/api.service';
import { CompanyStore } from '../../core/company.service';
import { KesPipe } from '../../core/format';
import { BotGuard } from '../../shared/bot-guard';
import { Empty, Icon, Loading, Modal } from '../../shared/ui';

@Component({
  imports: [RouterLink, KesPipe, Icon, Loading, Empty, Modal, FormsModule, BotGuard],
  template: `
    @if (loading()) { <app-loading /> }
    @else if (!p()) {
      <div class="pub-wrap"><app-empty icon="building" title="Property not found" text="It may no longer be listed."><a class="btn" routerLink="/properties">Browse properties</a></app-empty></div>
    } @else {
      <div class="pub-wrap detail">
        <a routerLink="/properties" class="back-link"><app-icon name="left" [size]="16" /> All properties</a>
        <div class="row-between">
          <div>
            <h1 class="display">{{ p().name }}</h1>
            <p class="muted row" style="gap:4px"><app-icon name="pin" [size]="15" /> {{ p().address }}, {{ p().neighbourhood ? p().neighbourhood + ', ' : '' }}{{ p().town }}, {{ p().county }}</p>
          </div>
          <div class="row">
            <button class="btn" (click)="openViewing(null)"><app-icon name="calendar" /> Request a viewing</button>
            @if (waLink()) { <a class="btn btn-primary" [href]="waLink()" target="_blank" rel="noopener"><app-icon name="chat" /> WhatsApp</a> }
          </div>
        </div>

        <div class="gallery">
          @if (p().photos.length) {
            <img class="main-photo" [src]="p().photos[photo()].url" [alt]="p().photos[photo()].caption || p().name">
            <div class="thumbs">
              @for (ph of p().photos; track ph.id; let i = $index) {
                <button type="button" [class.active]="i === photo()" (click)="photo.set(i)"><img [src]="ph.url" [alt]="ph.caption" loading="lazy"></button>
              }
            </div>
          } @else { <div class="main-photo noimg"><app-icon name="building" [size]="48" /></div> }
        </div>

        <div class="split mt">
          <div class="stack">
            <div class="card card-pad">
              <h2>About this property</h2>
              <p style="white-space:pre-line">{{ p().description }}</p>
              @if (p().amenities.length) {
                <h3 class="mt">Amenities</h3>
                <ul class="amenities">@for (a of p().amenities; track a) { <li><app-icon name="check" [size]="15" /> {{ a }}</li> }</ul>
              }
            </div>
            <div class="card">
              <div class="card-head"><h2>Available units</h2><span class="muted small">{{ p().units.length }} available</span></div>
              @if (!p().units.length) {
                <app-empty icon="door" title="No units available right now" text="Request a viewing or contact us and we'll let you know when something opens up." />
              } @else {
                <ul class="list">
                  @for (u of p().units; track u.id) {
                    <li class="unit-row">
                      <div>
                        <div class="strong">{{ u.unit_type }} · Unit {{ u.unit_number }} @if (u.building) { <span class="muted">({{ u.building }})</span> }</div>
                        <div class="muted small">{{ u.bedrooms }} bed · {{ u.bathrooms }} bath @if (u.size_sqm) { · {{ u.size_sqm }} m² } @if (u.available_from) { · from {{ u.available_from }} }</div>
                        @if (u.listing_description) { <div class="small">{{ u.listing_description }}</div> }
                      </div>
                      <div class="unit-price">
                        <div class="price">{{ u.rent_amount | kes }}<small>/mo</small></div>
                        <div class="muted small">Deposit {{ u.deposit_amount | kes }}@if (+u.service_charge) { · Service {{ u.service_charge | kes }} }</div>
                        <div class="row" style="justify-content:flex-end;margin-top:6px">
                          <button class="btn btn-sm" (click)="openViewing(u)">View</button>
                          <a class="btn btn-sm btn-primary" [routerLink]="['/apply', u.id]" [queryParams]="{ p: p().slug }">Apply</a>
                        </div>
                      </div>
                    </li>
                  }
                </ul>
              }
            </div>
          </div>
          <aside class="stack">
            <div class="card card-pad">
              <h3>Rent terms</h3>
              <p class="small" style="white-space:pre-line">{{ p().rent_terms || 'Contact us for deposit and payment terms.' }}</p>
            </div>
            <div class="card card-pad contact-card">
              <h3>Contact the lettings team</h3>
              @if (p().contact_phone) { <a [href]="'tel:' + p().contact_phone"><app-icon name="phone" [size]="16" /> {{ p().contact_phone }}</a> }
              @if (p().contact_email) { <a [href]="'mailto:' + p().contact_email"><app-icon name="mail" [size]="16" /> {{ p().contact_email }}</a> }
              @if (waLink()) { <a [href]="waLink()" target="_blank" rel="noopener"><app-icon name="chat" [size]="16" /> Chat on WhatsApp</a> }
              @if (p().map_url) { <a [href]="p().map_url" target="_blank" rel="noopener"><app-icon name="pin" [size]="16" /> Open in Google Maps</a> }
            </div>
          </aside>
        </div>
      </div>

      <app-modal [(open)]="viewingOpen" title="Request a viewing">
        @if (viewingDone()) {
          <div class="alert alert-success">Thank you! Our team will contact you to confirm a time.</div>
          <div class="form-actions"><button class="btn" (click)="viewingOpen.set(false)">Close</button></div>
        } @else {
          <form (ngSubmit)="sendViewing()">
            @if (viewingUnit()) { <p class="muted">Unit {{ viewingUnit().unit_number }} – {{ viewingUnit().unit_type }}</p> }
            @if (vErr()) { <div class="alert alert-error">{{ vErr() }}</div> }
            <div class="form-grid">
              <label class="field span-2"><span>Full name</span><input name="n" [(ngModel)]="v.full_name" required></label>
              <label class="field"><span>Phone</span><input name="ph" type="tel" [(ngModel)]="v.phone" required></label>
              <label class="field"><span>Email (optional)</span><input name="e" type="email" [(ngModel)]="v.email"></label>
              <label class="field span-2"><span>Preferred date</span><input name="d" type="date" [(ngModel)]="v.preferred_date"></label>
              <label class="field span-2"><span>Message</span><textarea name="m" rows="3" [(ngModel)]="v.message"></textarea></label>
            </div>
            <label class="check small"><input type="checkbox" name="c" [(ngModel)]="v.consent_given"> I agree that my details are used to arrange this viewing, as described in the <a routerLink="/privacy" target="_blank">privacy notice</a>.</label>
            <app-bot-guard (token)="v.captcha_token = $event" (honeypot)="v.website = $event" [resetKey]="attempts()" />
            <div class="form-actions"><button class="btn btn-primary" [disabled]="busy() || !v.full_name || !v.phone || !v.consent_given">Send request</button></div>
          </form>
        }
      </app-modal>
    }`,
})
export class PublicPropertyDetail {
  private api = inject(Api);
  private title = inject(Title);
  private company = inject(CompanyStore);
  slug = input.required<string>();
  p = signal<any>(null);
  loading = signal(true);
  photo = signal(0);
  viewingOpen = signal(false);
  viewingUnit = signal<any>(null);
  viewingDone = signal(false);
  busy = signal(false);
  vErr = signal('');
  attempts = signal(0);
  v: any = {};

  ngOnInit() {
    this.api.get(`public/properties/${this.slug()}/`).subscribe({
      next: (r) => { this.p.set(r); this.title.setTitle(r.name); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  waLink() {
    const p = this.p();
    return p ? this.company.whatsappLink(p.whatsapp, `Hello, I'm interested in ${p.name}.`) : '';
  }

  openViewing(unit: any) {
    this.viewingUnit.set(unit);
    this.viewingDone.set(false);
    this.vErr.set('');
    this.v = { full_name: '', phone: '', email: '', preferred_date: '', message: '', consent_given: false };
    this.viewingOpen.set(true);
  }

  async sendViewing() {
    this.busy.set(true);
    this.vErr.set('');
    try {
      await this.api.postP('public/viewing-requests/', {
        ...this.v, preferred_date: this.v.preferred_date || null, property: this.p().slug, unit: this.viewingUnit()?.id ?? null,
      });
      this.viewingDone.set(true);
    } catch (e) {
      this.vErr.set(parseError(e).message);
      this.attempts.update((n) => n + 1);
    } finally {
      this.busy.set(false);
    }
  }
}
