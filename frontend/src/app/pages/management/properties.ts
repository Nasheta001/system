import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { Auth } from '../../core/auth.service';
import { ListState } from '../../shared/list';
import { Badge, Empty, Icon, Loading, PageHeader, Pager } from '../../shared/ui';

@Component({
  imports: [FormsModule, RouterLink, Badge, Empty, Icon, Loading, PageHeader, Pager],
  template: `
    <app-page-header title="Properties" subtitle="Your portfolio, occupancy and public listings.">
      @if (auth.can('create_properties')) { <a class="btn btn-primary" routerLink="/management/properties/new"><app-icon name="plus" /> Add property</a> }
    </app-page-header>
    <div class="card">
      <div class="toolbar">
        <div class="search"><app-icon name="search" [size]="16" /><input placeholder="Search name, town, county…" [(ngModel)]="list.filters['search']" (input)="list.search()"></div>
        <select [(ngModel)]="list.filters['status']" (change)="list.load(true)">
          <option value="active">Active</option><option value="archived">Archived</option>
        </select>
        <select [(ngModel)]="list.filters['is_published']" (change)="list.load(true)">
          <option value="">Published & hidden</option><option value="true">Published</option><option value="false">Not published</option>
        </select>
      </div>
      @if (list.loading() && !list.loaded()) { <app-loading /> }
      @else if (!list.items().length) {
        <app-empty icon="building" title="No properties found"
          [text]="list.filters['search'] ? 'Try a different search.' : 'Add your first property to start managing units and tenants.'">
          @if (auth.can('create_properties') && !list.filters['search']) { <a class="btn btn-primary" routerLink="/management/properties/new">Add property</a> }
        </app-empty>
      } @else {
        <div class="table-wrap"><table class="table responsive">
          <thead><tr><th>Property</th><th>Location</th><th class="num">Units</th><th class="num">Occupied</th><th class="num">Vacant</th><th>Occupancy</th><th>Website</th></tr></thead>
          <tbody>
            @for (p of list.items(); track p.id) {
              <tr class="clickable" [routerLink]="['/management/properties', p.id]">
                <td data-label="Property"><div class="row" style="gap:10px;flex-wrap:nowrap">
                  @if (p.cover_photo) { <img [src]="p.cover_photo" alt="" class="thumb"> } @else { <span class="thumb noimg"><app-icon name="building" [size]="16" /></span> }
                  <span class="strong">{{ p.name }}</span></div></td>
                <td data-label="Location">{{ p.neighbourhood ? p.neighbourhood + ', ' : '' }}{{ p.town }}<span class="sub">{{ p.county }}</span></td>
                <td data-label="Units" class="num">{{ p.total_units }}</td>
                <td data-label="Occupied" class="num">{{ p.occupied_units }}</td>
                <td data-label="Vacant" class="num">{{ p.available_units }} @if (p.reserved_units) { <span class="sub">+{{ p.reserved_units }} reserved</span> }</td>
                <td data-label="Occupancy" style="min-width:130px"><div class="row" style="gap:8px;flex-wrap:nowrap"><div class="progress" style="flex:1"><span [style.width.%]="p.occupancy_rate"></span></div><span class="small">{{ p.occupancy_rate }}%</span></div></td>
                <td data-label="Website">@if (p.status === 'archived') { <app-badge value="archived" /> } @else if (p.is_published) { <app-badge value="published" /> } @else { <app-badge value="draft" text="Hidden" /> }</td>
              </tr>
            }
          </tbody>
        </table></div>
        <app-pager [count]="list.count()" [page]="list.page()" (pageChange)="list.go($event)" />
      }
    </div>`,
  styles: `.thumb { width: 44px; height: 32px; border-radius: 6px; object-fit: cover; display: inline-flex; align-items: center; justify-content: center; }`,
})
export class PropertiesPage {
  auth = inject(Auth);
  list = new ListState(inject(Api), 'properties/', { status: 'active', is_published: '', search: '' });
  constructor() {
    this.list.load();
  }
}
