import { inject } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot } from '@angular/router';
import { Auth } from './auth.service';

/** UI guards only improve navigation; the API enforces every permission. */
export const staffGuard: CanActivateFn = async (_r, state: RouterStateSnapshot) => {
  const auth = inject(Auth);
  const router = inject(Router);
  const me = await auth.load();
  if (me && me.role !== 'tenant') return true;
  if (me?.role === 'tenant') return router.parseUrl('/tenant/dashboard');
  return router.createUrlTree(['/management/login'], { queryParams: { next: state.url } });
};

export const tenantGuard: CanActivateFn = async (_r, state: RouterStateSnapshot) => {
  const auth = inject(Auth);
  const router = inject(Router);
  const me = await auth.load();
  if (me?.role === 'tenant') return true;
  if (me) return router.parseUrl('/management/dashboard');
  return router.createUrlTree(['/tenant/login'], { queryParams: { next: state.url } });
};

export const capGuard: CanActivateFn = async (route: ActivatedRouteSnapshot) => {
  const auth = inject(Auth);
  const router = inject(Router);
  await auth.load();
  const cap = route.data['cap'] as string | undefined;
  return !cap || auth.can(cap) ? true : router.parseUrl('/management/dashboard');
};
