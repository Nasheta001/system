import { Pipe, PipeTransform } from '@angular/core';

const kes = new Intl.NumberFormat('en-KE', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

export function formatKes(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  return `${n < 0 ? '−' : ''}KES ${kes.format(Math.abs(n))}`;
}

@Pipe({ name: 'kes' })
export class KesPipe implements PipeTransform {
  transform(value: number | string | null | undefined): string {
    return formatKes(value);
  }
}

export const STATUS_LABELS: Record<string, string> = {
  available: 'Available', reserved: 'Reserved', occupied: 'Occupied', maintenance: 'Under maintenance',
  unavailable: 'Unavailable', active: 'Active', archived: 'Archived', notice: 'Notice given', ended: 'Ended',
  cancelled: 'Cancelled', former: 'Former', inactive: 'Inactive', pending: 'Pending', under_review: 'Under review',
  approved: 'Approved', rejected: 'Rejected', withdrawn: 'Withdrawn', converted: 'Converted', expired: 'Expired',
  verified: 'Verified', success: 'Successful', failed: 'Failed', timeout: 'Timed out', draft: 'Draft',
  scheduled: 'Scheduled', published: 'Published', submitted: 'Submitted', reviewed: 'Reviewed', assigned: 'Assigned',
  in_progress: 'In progress', awaiting_parts: 'Awaiting parts', completed: 'Completed', closed: 'Closed',
  new: 'New', contacted: 'Contacted', credit: 'In credit', paid: 'Paid up', upcoming: 'Upcoming', due: 'Due',
  overdue: 'Overdue', queued: 'Queued', sent: 'Sent to provider', delivered: 'Delivered', logged: 'Logged only',
  skipped: 'Skipped', open: 'Open', done: 'Done', dismissed: 'Dismissed', low: 'Low', normal: 'Normal', high: 'High',
  urgent: 'Urgent', emergency: 'Emergency', info: 'Information only', acknowledge: 'Acknowledgement',
  signature: 'Signature', all_tenants: 'All active tenants', properties: 'Selected properties',
  buildings: 'Selected buildings', tenants: 'Specific tenants', staff: 'Staff members', in_app: 'In-app',
  email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp', admin: 'Administrator', landlord: 'Landlord',
  manager: 'Property manager', caretaker: 'Caretaker', tenant: 'Tenant',
};

@Pipe({ name: 'label' })
export class LabelPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '—';
    return STATUS_LABELS[value] ?? value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  }
}

export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function monthStart(): string {
  return today().slice(0, 8) + '01';
}
