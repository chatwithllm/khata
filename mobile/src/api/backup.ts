import { api } from './client';

/** Whole-instance snapshot (operator-only). Returns the backup object. */
export function exportBackup() {
  return api<Record<string, any>>('/api/backup');
}

/** Merge a backup object into the instance (operator-only). */
export function restoreBackup(data: Record<string, any>) {
  return api<{ ok: boolean; stats: Record<string, any>; pre_restore_saved: boolean }>('/api/restore', {
    method: 'POST',
    body: data,
  });
}
