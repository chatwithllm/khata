/**
 * Khata design tokens — ported from the web app's CSS custom properties
 * (`src/khata/static/assets/ledger.css` + `app.css`, the default `:root` theme).
 *
 * The web app is a warm "paper & ink" ledger aesthetic: cream paper background,
 * dark-brown ink text, burnt-orange primary, ledger green/red for money signs.
 * Keeping these exact hex values is what gives the mobile app visual parity.
 */
export const colors = {
  paper: '#F7F1E6', // app background
  paper2: '#F1E8D7', // sunken / secondary surface
  card: '#FFFDF8', // raised card surface
  ink: '#241B16', // primary text
  inkSoft: '#4A4035', // secondary text
  inkFaint: '#8C8068', // muted / captions
  line: '#DBCDB0', // borders / dividers
  line2: '#E7DCC6', // subtle dividers
  primary: '#C05E1B', // burnt orange — brand / CTAs
  primaryDeep: '#9C4711', // pressed / emphasis
  pos: '#1F6B53', // gains / money in (green)
  posSoft: '#2E8C6E',
  neg: '#A6321F', // losses / money out (red)
  accent: '#1F6F86', // teal accent
  glow: 'rgba(192,94,27,0.12)', // color-mix(primary 12%) flattened
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16, // --r
  pill: 999,
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const font = {
  // Web uses a system serif/sans stack; RN defaults are fine for parity v1.
  size: { xs: 12, sm: 13, md: 15, lg: 18, xl: 22, xxl: 28 },
  weight: { regular: '400', medium: '500', semibold: '600', bold: '700' },
} as const;

export const shadow = {
  card: {
    shadowColor: '#1C1813',
    shadowOpacity: 0.12,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
} as const;

export type Colors = typeof colors;
