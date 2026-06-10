/**
 * Currency formatting ported verbatim from the web app
 * (`src/khata/static/app.html` indGroup/usGroup/sym/fmt). Amounts travel as
 * integer minor units (×100). INR uses Indian lakh/crore grouping (12,40,000),
 * USD uses Western grouping. Symbol is ₹ / $.
 */
export type Currency = 'INR' | 'USD';

export function sym(ccy: string): string {
  return ccy === 'INR' ? '₹' : '$';
}

function indGroup(n: number): string {
  n = Math.round(n);
  let s = Math.abs(n).toString();
  if (s.length > 3) {
    const l = s.slice(-3);
    const r = s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
    s = r + ',' + l;
  }
  return (n < 0 ? '-' : '') + s;
}

function usGroup(n: number): string {
  return Math.round(n).toLocaleString('en-US');
}

/** Grouped number string only (sign included), no symbol. */
export function fmtNum(minor: number | null | undefined, ccy: string): string {
  if (minor === null || minor === undefined) return '—';
  const v = minor / 100;
  return ccy === 'INR' ? indGroup(v) : usGroup(v);
}

/** Full amount including symbol, e.g. "-₹12,40,000". */
export function fmt(minor: number | null | undefined, ccy: string): string {
  if (minor === null || minor === undefined) return '—';
  const neg = minor < 0;
  const n = fmtNum(Math.abs(minor), ccy);
  return (neg ? '-' : '') + sym(ccy) + n;
}
