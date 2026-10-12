import { Routes } from '@angular/router';
import { capGuard, staffGuard, tenantGuard } from './core/guards';

const m = (cap?: string) => (cap ? { canActivate: [capGuard], data: { cap } } : {});

export const routes: Routes = [
  // ------------------------------------------------------------- public website
  {
    path: '',
    loadComponent: () => import('./layouts/public-layout').then((c) => c.PublicLayout),
    children: [
      { path: '', loadComponent: () => import('./pages/public/home').then((c) => c.HomePage), title: 'Find your next home' },
      { path: 'properties', loadComponent: () => import('./pages/public/property-list').then((c) => c.PublicPropertyList), title: 'Properties' },
      { path: 'properties/:slug', loadComponent: () => import('./pages/public/property-detail').then((c) => c.PublicPropertyDetail) },
      { path: 'apply/:unitId', loadComponent: () => import('./pages/public/apply').then((c) => c.ApplyPage), title: 'Apply' },
      { path: 'application-status', loadComponent: () => import('./pages/public/application-status').then((c) => c.ApplicationStatusPage), title: 'Application status' },
      { path: 'about', loadComponent: () => import('./pages/public/about').then((c) => c.AboutPage), title: 'About & FAQ' },
      { path: 'privacy', loadComponent: () => import('./pages/public/about').then((c) => c.PrivacyPage), title: 'Privacy notice' },
      { path: 'account/forgot-password', loadComponent: () => import('./pages/auth/password').then((c) => c.ForgotPasswordPage), title: 'Forgot password' },
      { path: 'account/reset-password', loadComponent: () => import('./pages/auth/password').then((c) => c.ResetPasswordPage), title: 'Set password' },
      { path: 'login', loadComponent: () => import('./pages/auth/access').then((c) => c.LoginChooserPage), title: 'Sign in' },
      { path: 'account/accept-invite', loadComponent: () => import('./pages/auth/access').then((c) => c.AcceptInvitePage), title: 'Accept invitation' },
      { path: 'account/setup', loadComponent: () => import('./pages/auth/access').then((c) => c.InitialSetupPage), title: 'First-time setup' },
    ],
  },

  // ------------------------------------------------------------- management
  { path: 'management/login', loadComponent: () => import('./pages/auth/login').then((c) => c.ManagementLogin), title: 'Management sign in' },
  {
    path: 'management',
    canActivate: [staffGuard],
    loadComponent: () => import('./layouts/management-layout').then((c) => c.ManagementLayout),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', loadComponent: () => import('./pages/management/dashboard').then((c) => c.DashboardPage), title: 'Dashboard' },
      { path: 'properties', loadComponent: () => import('./pages/management/properties').then((c) => c.PropertiesPage), title: 'Properties' },
      { path: 'properties/new', ...m('create_properties'), loadComponent: () => import('./pages/management/property-form').then((c) => c.PropertyFormPage), title: 'New property' },
      { path: 'properties/:id', loadComponent: () => import('./pages/management/property-detail').then((c) => c.PropertyDetailPage), title: 'Property' },
      { path: 'properties/:id/edit', ...m('manage_properties'), loadComponent: () => import('./pages/management/property-form').then((c) => c.PropertyFormPage), title: 'Edit property' },
      { path: 'tenants', ...m('view_tenants'), loadComponent: () => import('./pages/management/tenants').then((c) => c.TenantsPage), title: 'Tenants' },
      { path: 'tenants/new', ...m('manage_tenants'), loadComponent: () => import('./pages/management/tenant-form').then((c) => c.TenantFormPage), title: 'Register tenant' },
      { path: 'tenants/:id', ...m('view_tenants'), loadComponent: () => import('./pages/management/tenant-detail').then((c) => c.TenantDetailPage), title: 'Tenant' },
      { path: 'payments', ...m('view_payments'), loadComponent: () => import('./pages/management/payments').then((c) => c.PaymentsPage), title: 'Payments' },
      { path: 'leasing', ...m('manage_applications'), loadComponent: () => import('./pages/management/leasing').then((c) => c.LeasingPage), title: 'Applications & vacancies' },
      { path: 'announcements', ...m('view_announcements'), loadComponent: () => import('./pages/management/announcements').then((c) => c.AnnouncementsPage), title: 'Announcements' },
      { path: 'announcements/new', ...m('manage_announcements'), loadComponent: () => import('./pages/management/announcement-form').then((c) => c.AnnouncementFormPage), title: 'New announcement' },
      { path: 'announcements/:id', ...m('view_announcements'), loadComponent: () => import('./pages/management/announcement-detail').then((c) => c.AnnouncementDetailPage), title: 'Announcement' },
      { path: 'announcements/:id/edit', ...m('manage_announcements'), loadComponent: () => import('./pages/management/announcement-form').then((c) => c.AnnouncementFormPage), title: 'Edit announcement' },
      { path: 'documents', ...m('view_documents'), loadComponent: () => import('./pages/management/documents').then((c) => c.DocumentsPage), title: 'Documents & rules library' },
      { path: 'documents/:id', ...m('view_documents'), loadComponent: () => import('./pages/management/document-detail').then((c) => c.DocumentDetailPage), title: 'Document' },
      { path: 'maintenance', ...m('view_maintenance'), loadComponent: () => import('./pages/management/maintenance').then((c) => c.MaintenancePage), title: 'Maintenance' },
      { path: 'maintenance/:id', ...m('view_maintenance'), loadComponent: () => import('./pages/management/maintenance-detail').then((c) => c.MaintenanceDetailPage), title: 'Maintenance request' },
      { path: 'reports', ...m('view_reports'), loadComponent: () => import('./pages/management/reports').then((c) => c.ReportsPage), title: 'Reports' },
      { path: 'staff', ...m('manage_staff'), loadComponent: () => import('./pages/management/staff').then((c) => c.StaffPage), title: 'Staff' },
      { path: 'settings', loadComponent: () => import('./pages/management/settings').then((c) => c.SettingsPage), title: 'Settings' },
      { path: 'audit', ...m('view_audit'), loadComponent: () => import('./pages/management/audit').then((c) => c.AuditPage), title: 'Audit log' },
      { path: 'notifications', loadComponent: () => import('./pages/management/notifications').then((c) => c.StaffNotificationsPage), title: 'Notifications' },
    ],
  },

  // ------------------------------------------------------------- tenant portal
  { path: 'tenant/login', loadComponent: () => import('./pages/auth/login').then((c) => c.TenantLogin), title: 'Tenant sign in' },
  {
    path: 'tenant',
    canActivate: [tenantGuard],
    loadComponent: () => import('./layouts/tenant-layout').then((c) => c.TenantLayout),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', loadComponent: () => import('./pages/tenant/dashboard').then((c) => c.TenantDashboardPage), title: 'My home' },
      { path: 'payments', loadComponent: () => import('./pages/tenant/payments').then((c) => c.TenantPaymentsPage), title: 'Rent & payments' },
      { path: 'announcements', loadComponent: () => import('./pages/tenant/announcements').then((c) => c.TenantAnnouncementsPage), title: 'Notices' },
      { path: 'documents', loadComponent: () => import('./pages/tenant/documents').then((c) => c.TenantDocumentsPage), title: 'Documents' },
      { path: 'maintenance', loadComponent: () => import('./pages/tenant/maintenance').then((c) => c.TenantMaintenancePage), title: 'Maintenance' },
      { path: 'maintenance/:id', loadComponent: () => import('./pages/tenant/maintenance').then((c) => c.TenantMaintenanceDetailPage), title: 'Maintenance request' },
      { path: 'profile', loadComponent: () => import('./pages/tenant/profile').then((c) => c.TenantProfilePage), title: 'My profile' },
    ],
  },
  { path: '**', loadComponent: () => import('./pages/public/not-found').then((c) => c.NotFoundPage), title: 'Not found' },
];
