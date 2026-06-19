/**
 * Device-side backup I/O. Export writes the instance snapshot to a cache file
 * and opens the iOS share sheet (save to Files, AirDrop, etc.). Restore lets the
 * user pick a .json backup and returns its parsed contents to POST to /restore.
 */
import * as DocumentPicker from 'expo-document-picker';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

export async function shareBackup(data: Record<string, any>): Promise<boolean> {
  const stamp = new Date().toISOString().slice(0, 10);
  const file = new File(Paths.cache, `khata-backup-${stamp}.json`);
  if (file.exists) file.delete();
  file.create();
  file.write(JSON.stringify(data));

  if (!(await Sharing.isAvailableAsync())) return false;
  await Sharing.shareAsync(file.uri, {
    mimeType: 'application/json',
    UTI: 'public.json',
    dialogTitle: 'Save Khata backup',
  });
  return true;
}

export async function pickBackupFile(): Promise<Record<string, any> | null> {
  const res = await DocumentPicker.getDocumentAsync({
    type: 'application/json',
    copyToCacheDirectory: true,
  });
  if (res.canceled || !res.assets?.[0]) return null;
  const text = await new File(res.assets[0].uri).text();
  return JSON.parse(text);
}
