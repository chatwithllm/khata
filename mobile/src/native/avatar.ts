/**
 * Pick + crop + shrink an avatar to a data URL the API accepts.
 * The backend caps the avatar at ~200 KB and requires a `data:image/` URL, so
 * we square-crop on pick, downscale to 256px, and JPEG-compress until it fits.
 */
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';

const MAX_LEN = 190_000; // server cap is 200 KB of data-URL text; stay under it

export type AvatarPickResult =
  | { ok: true; dataUrl: string }
  | { ok: false; reason: 'cancelled' | 'permission' | 'too_large' };

export async function pickAvatar(): Promise<AvatarPickResult> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) return { ok: false, reason: 'permission' };

  const picked = await ImagePicker.launchImageLibraryAsync({
    allowsEditing: true,
    aspect: [1, 1],
    quality: 1,
  });
  if (picked.canceled || !picked.assets?.[0]) return { ok: false, reason: 'cancelled' };

  const uri = picked.assets[0].uri;

  // Downscale to 256px, then step compression down until under the size cap.
  for (const compress of [0.7, 0.5, 0.35, 0.2]) {
    const out = await ImageManipulator.manipulateAsync(uri, [{ resize: { width: 256, height: 256 } }], {
      compress,
      format: ImageManipulator.SaveFormat.JPEG,
      base64: true,
    });
    const dataUrl = `data:image/jpeg;base64,${out.base64}`;
    if (dataUrl.length <= MAX_LEN) return { ok: true, dataUrl };
  }
  return { ok: false, reason: 'too_large' };
}
