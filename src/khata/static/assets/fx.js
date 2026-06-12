// FX snapshot helpers (spec docs/specs/2026-06-11-fx-snapshot-design.md §8).
// Server stores fx_rate_micro = counter-per-entry ×1e6 and derives
// counter_value_minor; these helpers only FORMAT — no money math beyond display.
(function(){
  const SYM = { INR: '₹', USD: '$' };

  // small mono line under a ledger amount: "$568.18 @ ₹88.00/$".
  // lr: serialized ledger row; entryCcy: the plan/entry currency (page BASE).
  // Returns an element, or null when the row has no snapshot.
  window.fxLine = function(lr, entryCcy){
    if(!lr || !lr.fx_rate_micro || !lr.fx_counter_currency || lr.counter_value_minor==null) return null;
    const es = SYM[(entryCcy||'').toUpperCase()] || entryCcy;
    const cs = SYM[lr.fx_counter_currency] || lr.fx_counter_currency;
    const v = Math.abs(lr.counter_value_minor);
    const val = cs + Math.floor(v/100).toLocaleString('en-US') + '.' + String(v%100).padStart(2,'0');
    // rate in natural direction — quote the side that is ≥ 1 (₹88.00/$, never $0.0114/₹)
    const r = lr.fx_rate_micro / 1e6;
    const rate = r >= 1 ? (cs + r.toFixed(2) + '/' + es) : (es + (1/r).toFixed(2) + '/' + cs);
    const line = document.createElement('span');
    line.textContent = val + ' @ ' + rate;
    line.style.cssText = 'display:block;font-family:"JetBrains Mono";font-weight:500;'
      + 'font-size:10.5px;color:var(--ink-faint);margin-top:3px;letter-spacing:.01em';
    return line;
  };

  // edit-form helpers: the form always shows the NATURAL rate (INR per USD, ≥1)
  // regardless of entry currency; storage is entry→counter micro.
  window.fxNaturalFromMicro = function(rateMicro, entryCcy){
    if(!rateMicro) return '';
    const r = (entryCcy === 'USD') ? rateMicro/1e6 : 1e6/rateMicro;
    return String(Math.round(r*10000)/10000);
  };
  window.fxMicroFromNatural = function(val, entryCcy){
    const r = parseFloat(String(val||'').replace(/,/g,''));
    if(!isFinite(r) || r <= 0) return null;
    return (entryCcy === 'USD') ? Math.round(r*1e6) : Math.round(1e6/r);
  };
})();
