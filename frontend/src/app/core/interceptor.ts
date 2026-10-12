import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { Auth } from './auth.service';

/** On 401 (session expired), send the user to the right login page. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const auth = inject(Auth);
  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      const isAuthCall = req.url.includes('/api/auth/');
      if (err.status === 401 && !isAuthCall) {
        const url = router.url;
        auth.clear();
        if (url.startsWith('/tenant')) router.navigate(['/tenant/login'], { queryParams: { next: url } });
        else if (url.startsWith('/management')) router.navigate(['/management/login'], { queryParams: { next: url } });
      }
      return throwError(() => err);
    }),
  );
};
