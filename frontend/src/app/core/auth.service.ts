import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from './api.service';

export interface Me {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string;
  role: 'admin' | 'landlord' | 'manager' | 'caretaker' | 'tenant';
  capabilities: string[];
  assigned_properties: { id: number; name: string; town: string }[];
  portfolio_access: boolean;
  tenant_id: number | null;
  must_change_password: boolean;
}

export const ROLE_LABELS: Record<string, string> = {
  admin: 'Company administrator',
  landlord: 'Landlord / owner',
  manager: 'Property manager',
  caretaker: 'Caretaker',
  tenant: 'Tenant',
};

@Injectable({ providedIn: 'root' })
export class Auth {
  private api = inject(Api);
  private router = inject(Router);
  readonly me = signal<Me | null>(null);
  readonly loaded = signal(false);
  readonly isStaff = computed(() => !!this.me() && this.me()!.role !== 'tenant');
  readonly isTenant = computed(() => this.me()?.role === 'tenant');

  async load(): Promise<Me | null> {
    if (this.loaded()) return this.me();
    try {
      this.me.set(await this.api.getP<Me>('auth/me/'));
    } catch {
      this.me.set(null);
    }
    this.loaded.set(true);
    return this.me();
  }

  async refresh() {
    this.loaded.set(false);
    return this.load();
  }

  async login(email: string, password: string, portal: 'management' | 'tenant', remember = true) {
    const me = await this.api.postP<Me>('auth/login/', { email, password, portal, remember });
    this.me.set(me);
    this.loaded.set(true);
    return me;
  }

  async logout() {
    const wasTenant = this.isTenant();
    try {
      await this.api.postP('auth/logout/');
    } catch {
      /* ignore */
    }
    this.me.set(null);
    await this.api.getP('auth/csrf/').catch(() => null);
    this.router.navigateByUrl(wasTenant ? '/tenant/login' : '/management/login');
  }

  can(cap: string): boolean {
    return this.me()?.capabilities.includes(cap) ?? false;
  }

  clear() {
    this.me.set(null);
  }
}
