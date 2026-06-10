import { api } from './client';
import type { AuthResponse, MeResponse, User } from './types';

export function login(email: string, password: string) {
  return api<AuthResponse>('/api/auth/login', { method: 'POST', body: { email, password } });
}

export function register(email: string, display_name: string, password: string) {
  return api<AuthResponse>('/api/auth/register', {
    method: 'POST',
    body: { email, display_name, password },
  });
}

export function loginWithGoogle(credential: string) {
  return api<AuthResponse>('/api/auth/google', { method: 'POST', body: { credential } });
}

export function me() {
  return api<MeResponse>('/api/auth/me');
}

export function getAuthConfig() {
  return api<{ google_client_id: string | null }>('/api/auth/config');
}

export function logout() {
  return api<{ ok: boolean }>('/api/auth/logout', { method: 'POST' });
}

export function updateProfile(display_name: string) {
  return api<{ user: User }>('/api/auth/profile', { method: 'POST', body: { display_name } });
}

/** avatar: a `data:image/...;base64,...` URL (≤200 KB), or null to clear. */
export function setAvatar(avatar: string | null) {
  return api<{ user: User }>('/api/auth/avatar', { method: 'POST', body: { avatar } });
}
