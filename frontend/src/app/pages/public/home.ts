import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { CompanyStore } from '../../core/company.service';
import { Icon } from '../../shared/ui';
import { PropertyCard, PublicProperty } from './property-list';

@Component({
  imports: [FormsModule, RouterLink, PropertyCard, Icon],
  template: `
    <!-- Full-bleed photo hero (cycles through featured properties) -->
    <section class="hx">
      @for (s of slides; track s.src; let i = $index) {
        <img class="hx-photo" [class.show]="i === slide()" [src]="s.src" [alt]="i === slide() ? s.alt : ''" [attr.aria-hidden]="i !== slide()"
             [attr.fetchpriority]="i === 0 ? 'high' : null" [attr.loading]="i === 0 ? null : 'lazy'">
      }
      <div class="hx-shade"></div>
      <div class="pub-wrap hx-inner">
        <span class="hx-logo"><app-icon name="home" [size]="22" /></span>
        <h1>Your dream home awaits: tailored just for you!</h1>
        <p>Discover well-managed homes across {{ townsLabel() }} – from a cosy bedsitter to a spacious family apartment. Request a viewing or apply online in minutes.</p>

        <form class="hx-search" (ngSubmit)="go()">
          <label><app-icon name="pin" [size]="16" />
            <select name="town" [(ngModel)]="town" aria-label="Location">
              <option value="">Any location</option>
              @for (t of filters()?.towns; track t) { <option [value]="t">{{ t }}</option> }
            </select></label>
          <label><app-icon name="bed" [size]="16" />
            <select name="bedrooms" [(ngModel)]="bedrooms" aria-label="Bedrooms">
              <option value="">Any size</option><option value="0">Studio / bedsitter</option>
              <option value="1">1 bedroom</option><option value="2">2 bedrooms</option><option value="3">3+ bedrooms</option>
            </select></label>
          <label><app-icon name="wallet" [size]="16" />
            <input type="number" name="max_rent" [(ngModel)]="maxRent" placeholder="Budget (KES / month)" min="0" aria-label="Budget"></label>
          <button type="submit"><app-icon name="search" [size]="16" /> Search</button>
        </form>

        <div class="hx-foot">
          <a routerLink="/properties">Browse all homes</a>
          <div class="dots" role="tablist" aria-label="Photos">
            @for (s of slides; track s.src; let i = $index) {
              <button type="button" role="tab" [class.on]="i === slide()" [attr.aria-selected]="i === slide()" [attr.aria-label]="'Photo ' + (i + 1)" (click)="pick(i)"></button>
            }
          </div>
          <button type="button" class="next" (click)="pick((slide() + 1) % slides.length)">Next <app-icon name="right" [size]="15" /></button>
        </div>
      </div>
    </section>

    <!-- Feed -->
    <section class="pub-wrap feed">
      <div class="type-chips" role="list">
        <a role="listitem" class="chip-x on" routerLink="/properties">All homes</a>
        @for (t of filters()?.unit_types; track t.id) {
          <a role="listitem" class="chip-x" routerLink="/properties" [queryParams]="{ unit_type: t.id }">{{ t.name }}</a>
        }
      </div>

      <div class="feed-head"><h2>Homes for you</h2><a routerLink="/properties">See all</a></div>
      <div class="rail">@for (p of featured(); track p.id) { <div class="rail-item"><app-property-card [p]="p" /></div> }</div>

      @if (others().length) {
        <div class="feed-head"><h2>More homes available</h2><a routerLink="/properties" [queryParams]="{ available_only: true }">See all</a></div>
        <div class="pgrid">@for (p of others(); track p.id) { <app-property-card [p]="p" /> }</div>
      }
    </section>

    <section class="pub-wrap section">
      <div class="features">
        <div><span class="f-icon"><app-icon name="wallet" /></span><h3>Pay rent by M-Pesa</h3><p>Tenants pay from their phone and get a receipt once the payment is confirmed.</p></div>
        <div><span class="f-icon"><app-icon name="wrench" /></span><h3>Responsive maintenance</h3><p>Report repairs online and follow every update until it is fixed.</p></div>
        <div><span class="f-icon"><app-icon name="shield" /></span><h3>Secure & transparent</h3><p>Clear rent statements and private access to your own documents.</p></div>
      </div>
    </section>

    <section class="pub-wrap section contact-band">
      <div>
        <h2>Looking for something specific?</h2>
        <p>Talk to our lettings team – we will let you know as soon as a suitable unit is available.</p>
      </div>
      <div class="row">
        @if (company.company()?.phone) { <a class="btn btn-lg" [href]="'tel:' + company.company()?.phone"><app-icon name="phone" /> Call us</a> }
        @if (company.whatsappLink()) { <a class="btn btn-lg btn-primary" [href]="company.whatsappLink('', 'Hello, I am looking for a house to rent.')" target="_blank" rel="noopener"><app-icon name="chat" /> WhatsApp</a> }
        @if (company.company()?.email) { <a class="btn btn-lg" [href]="'mailto:' + company.company()?.email"><app-icon name="mail" /> Email</a> }
      </div>
    </section>`,
  styles: `
    .hx { position: relative; min-height: min(86vh, 760px); display: flex; align-items: flex-end; overflow: hidden; background: #10231e; color: #e8efec; }
    .hx-photo { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transform: scale(1.04); transition: opacity 1s ease, transform 7s ease; }
    .hx-photo.show { opacity: 1; transform: scale(1); }
    .hx-shade { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(8,14,12,.15) 0%, rgba(8,14,12,.35) 40%, rgba(8,14,12,.92) 100%); }
    .hx-inner { position: relative; z-index: 1; width: 100%; padding-top: 120px; padding-bottom: 34px; }
    .hx-logo { width: 46px; height: 46px; border-radius: 12px; display: grid; place-items: center; background: rgba(20,24,22,.75); color: #fff; border: 1px solid rgba(255,255,255,.15); margin-bottom: 16px; }
    .hx h1 { margin: 0; max-width: 720px; color: #fff; font-family: var(--font-display); font-weight: 650; font-size: clamp(2rem, 5.2vw, 3.6rem); line-height: 1.06; letter-spacing: -.01em; }
    .hx p { max-width: 560px; margin: 14px 0 22px; color: rgba(255,255,255,.78); font-size: 1.05rem; }

    .hx-search { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)) auto; gap: 8px; max-width: 900px; padding: 8px; border-radius: 16px;
      background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.18); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
    .hx-search label { display: flex; align-items: center; gap: 8px; height: 46px; padding: 0 12px; border-radius: 11px; background: #fff; color: var(--muted); }
    .hx-search select, .hx-search input { flex: 1; min-width: 0; height: 100%; border: 0; padding: 0; background: transparent; box-shadow: none; color: var(--ink); font: inherit; }
    .hx-search select:focus, .hx-search input:focus { outline: none; box-shadow: none; }
    .hx-search label:focus-within { box-shadow: 0 0 0 3px rgba(185,119,58,.45); }
    .hx-search button { display: inline-flex; align-items: center; gap: 8px; height: 46px; padding: 0 22px; border: 0; border-radius: 11px; cursor: pointer;
      background: var(--accent); color: #fff; font: inherit; font-weight: 700; }
    .hx-search button:hover { filter: brightness(1.07); }

    .hx-foot { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 26px; font-size: .92rem; }
    .hx-foot a { color: #c8b8ff; font-weight: 600; text-decoration: none; }
    .hx-foot a:hover { color: #fff; }
    .next { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: 0; background: none; cursor: pointer; color: #c8b8ff; font: inherit; font-weight: 600; }
    .next:hover { color: #fff; }
    .dots { display: flex; gap: 6px; }
    .dots button { width: 8px; height: 8px; padding: 0; border: 0; border-radius: 999px; background: rgba(255,255,255,.4); cursor: pointer; transition: width .3s, background .3s; }
    .dots button.on { width: 22px; background: #fff; }

    .feed { margin-top: 26px; }
    .type-chips { display: flex; flex-wrap: nowrap; gap: 8px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: none; }
    .type-chips::-webkit-scrollbar { display: none; }
    .chip-x { flex: none; padding: 8px 16px; border-radius: 10px; border: 1px solid var(--line); background: #fff; color: var(--ink-2); font-size: .88rem; font-weight: 550; text-decoration: none; white-space: nowrap; }
    .chip-x:hover { border-color: var(--ink-2); color: var(--ink); }
    .chip-x.on { background: var(--ink); border-color: var(--ink); color: #fff; }

    .feed-head { display: flex; justify-content: space-between; align-items: baseline; margin: 26px 0 12px; }
    .feed-head h2 { margin: 0; font-size: 1.3rem; font-weight: 700; }
    .feed-head a { color: #5b4fd6; font-weight: 600; font-size: .92rem; text-decoration: none; }
    .rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(280px, 340px); gap: 18px; overflow-x: auto; scroll-snap-type: x mandatory; padding: 4px 2px 14px; scrollbar-width: thin; }
    .rail-item { scroll-snap-align: start; }
    .rail-item > * { height: 100%; }

    @media (max-width: 760px) {
      .hx { min-height: 88vh; }
      .hx-inner { padding-top: 90px; }
      .hx-search { grid-template-columns: 1fr; }
      .hx-search button { justify-content: center; }
      .rail { grid-auto-columns: 82%; }
    }
    @media (prefers-reduced-motion: reduce) { .hx-photo { transition: opacity .2s; transform: none; } }
  `,
})
export class HomePage {
  private api = inject(Api);
  private router = inject(Router);
  company = inject(CompanyStore);
  filters = signal<any>(null);
  all = signal<PublicProperty[]>([]);
  slide = signal(0);
  featured = computed(() => {
    const list = this.all();
    const f = list.filter((p) => p.is_featured);
    return (f.length ? f : list).slice(0, 8);
  });
  others = computed(() => {
    const ids = new Set(this.featured().map((p) => p.id));
    return this.all().filter((p) => !ids.has(p.id)).slice(0, 6);
  });
  /** Hero photos served from frontend/public/hero/. Replace or add files there to change them. */
  slides = [
    { src: '/hero/hero-2.jpg', alt: 'White apartment blocks around a swimming pool' },
    { src: '/hero/hero-3.jpg', alt: 'Glass residential towers beside a pool at sunset' },
    { src: '/hero/hero-1.jpg', alt: 'Cream apartment building with curved balconies' },
    { src: '/hero/hero-4.jpg', alt: 'Modern high-rise apartments behind trees' },
  ];
  townsLabel = computed(() => {
    const t: string[] = this.filters()?.towns ?? [];
    return t.length ? (t.length > 1 ? `${t.slice(0, -1).join(', ')} and ${t[t.length - 1]}` : t[0]) : 'Kenya';
  });
  town = '';
  bedrooms = '';
  maxRent = '';
  private timer: any;

  constructor() {
    this.api.get('public/filters/').subscribe((r) => this.filters.set(r));
    this.api.get<PublicProperty[]>('public/properties/').subscribe((r) => this.all.set(r));
    const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) this.timer = setInterval(() => this.advance(), 6000);
    inject(DestroyRef).onDestroy(() => clearInterval(this.timer));
  }

  private advance() {
    const n = this.slides.length;
    if (n > 1) this.slide.set((this.slide() + 1) % n);
  }

  pick(i: number) {
    this.slide.set(i);
    clearInterval(this.timer);
  }

  go() {
    const q: any = {};
    if (this.town) q.town = this.town;
    if (this.bedrooms !== '') q.bedrooms = this.bedrooms;
    if (this.maxRent) q.max_rent = this.maxRent;
    this.router.navigate(['/properties'], { queryParams: q });
  }
}
