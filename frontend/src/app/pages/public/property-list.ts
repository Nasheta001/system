import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { KesPipe } from '../../core/format';
import { Empty, Icon, Loading } from '../../shared/ui';

export interface PublicProperty {
  id: number;
  name: string;
  slug: string;
  town: string;
  county: string;
  neighbourhood: string;
  cover_photo: string | null;
  min_rent: string | null;
  max_rent: string | null;
  available_count: number;
  unit_types: string[];
  bedrooms: number[];
  is_featured: boolean;
}

@Component({
  selector: 'app-property-card',
  imports: [RouterLink, KesPipe, Icon],
  template: `
    <a class="pcard" [routerLink]="['/properties', p().slug]">
      <div class="pcard-img">
        @if (p().cover_photo) { <img [src]="p().cover_photo" [alt]="p().name" loading="lazy"> }
        @else { <div class="noimg"><app-icon name="building" [size]="34" /></div> }
        @if (p().is_featured) { <span class="tag">Popular</span> }
        <button type="button" class="fav" [class.on]="saved()" (click)="toggleSave($event)" [attr.aria-label]="saved() ? 'Remove from saved' : 'Save home'" [attr.aria-pressed]="saved()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20s-7-4.4-9.2-8.6C1.3 8.4 3 5 6.4 5c2 0 3.3 1.1 4 2.2.3.4.9.4 1.2 0C12.3 6.1 13.6 5 15.6 5 19 5 20.7 8.4 19.2 11.4 17 15.6 12 20 12 20z"/></svg>
        </button>
      </div>
      <div class="specs">
        <span><app-icon name="bed" [size]="15" /> {{ bedsLabel() }}</span>
        <span><app-icon name="door" [size]="15" /> {{ p().available_count > 0 ? p().available_count + ' available' : 'Fully let' }}</span>
        <span><app-icon name="layers" [size]="15" /> {{ p().unit_types.length || 0 }} {{ p().unit_types.length === 1 ? 'type' : 'types' }}</span>
      </div>
      <div class="pcard-body">
        @if (p().min_rent) {
          <div class="price">{{ p().min_rent | kes }}@if (p().max_rent !== p().min_rent) { <span class="muted"> – {{ p().max_rent | kes }}</span> }<small>/ month</small></div>
        } @else { <div class="price muted">Enquire for rent</div> }
        <h3>{{ p().name }}</h3>
        <div class="addr"><app-icon name="pin" [size]="13" /> {{ p().neighbourhood ? p().neighbourhood + ', ' : '' }}{{ p().town }}</div>
      </div>
    </a>`,
})
export class PropertyCard {
  p = input.required<PublicProperty>();
  saved = signal(false);

  ngOnInit() {
    this.saved.set(savedHomes().includes(this.p().slug));
  }

  bedsLabel() {
    const b = [...new Set(this.p().bedrooms)].sort();
    if (!b.length) return 'Units';
    const fmt = (n: number) => (n === 0 ? 'Studio' : `${n} bed`);
    return b.length === 1 ? fmt(b[0]) : `${fmt(b[0])}–${b[b.length - 1]} bed`;
  }

  /** Saved homes are a per-browser convenience only (no account needed). */
  toggleSave(e: Event) {
    e.preventDefault();
    e.stopPropagation();
    const slug = this.p().slug;
    const list = savedHomes().filter((s) => s !== slug);
    if (!this.saved()) list.push(slug);
    try { localStorage.setItem('saved-homes', JSON.stringify(list)); } catch { /* storage unavailable */ }
    this.saved.set(!this.saved());
  }
}

function savedHomes(): string[] {
  try { return JSON.parse(localStorage.getItem('saved-homes') || '[]'); } catch { return []; }
}

@Component({
  imports: [FormsModule, PropertyCard, Loading, Empty, RouterLink],
  template: `
    <section class="list-hero">
      <div class="pub-wrap">
        <h1>Homes available to let</h1>
        <form class="search-bar" (ngSubmit)="search()">
          <select name="town" [(ngModel)]="f.town" aria-label="Location">
            <option value="">All locations</option>
            @for (t of filters()?.towns; track t) { <option [value]="t">{{ t }}</option> }
          </select>
          <select name="unit_type" [(ngModel)]="f.unit_type" aria-label="Unit type">
            <option value="">Any type</option>
            @for (t of filters()?.unit_types; track t.id) { <option [value]="t.id">{{ t.name }}</option> }
          </select>
          <select name="bedrooms" [(ngModel)]="f.bedrooms" aria-label="Bedrooms">
            <option value="">Any bedrooms</option>
            <option value="0">Studio / bedsitter</option><option value="1">1 bedroom</option>
            <option value="2">2 bedrooms</option><option value="3">3+ bedrooms</option>
          </select>
          <input type="number" name="max_rent" [(ngModel)]="f.max_rent" placeholder="Max rent (KES)" min="0" aria-label="Maximum rent">
          <button class="btn btn-primary" type="submit">Search</button>
        </form>
        <label class="check small" style="margin-top:10px"><input type="checkbox" name="avail" [(ngModel)]="f.available_only" (change)="search()"> Only show properties with vacancies</label>
      </div>
    </section>
    <div class="pub-wrap">
      @if (loading()) { <app-loading /> }
      @else if (!items().length) {
        <app-empty icon="search" title="No matching homes" text="Try a different location or budget, or contact us – new units become available regularly.">
          <a class="btn" routerLink="/about">Contact us</a>
        </app-empty>
      } @else {
        <p class="muted">{{ items().length }} propert{{ items().length === 1 ? 'y' : 'ies' }}</p>
        <div class="pgrid">@for (p of items(); track p.id) { <app-property-card [p]="p" /> }</div>
      }
    </div>`,
})
export class PublicPropertyList {
  private api = inject(Api);
  private router = inject(Router);
  loading = signal(true);
  items = signal<PublicProperty[]>([]);
  filters = signal<any>(null);
  f: any = { town: '', unit_type: '', bedrooms: '', max_rent: '', available_only: false };

  constructor() {
    const q = inject(ActivatedRoute).snapshot.queryParams;
    this.f = { ...this.f, ...q, available_only: q['available_only'] === 'true' };
    this.api.get('public/filters/').subscribe((r) => this.filters.set(r));
    this.load();
  }

  search() {
    const params: any = {};
    for (const [k, v] of Object.entries(this.f)) if (v !== '' && v !== false && v !== null) params[k] = v;
    this.router.navigate([], { queryParams: params, replaceUrl: true });
    this.load();
  }

  load() {
    this.loading.set(true);
    this.api.get<PublicProperty[]>('public/properties/', { ...this.f, available_only: this.f.available_only ? 'true' : '' })
      .subscribe({ next: (r) => { this.items.set(r); this.loading.set(false); }, error: () => this.loading.set(false) });
  }
}
