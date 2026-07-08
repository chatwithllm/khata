// Money-in-transit panel + chain timeline for payment chains.
// Mounts into a container on plan detail pages:
//   KhataTransfers.mount(document.getElementById('transit-panel'), PID,
//                        {me: USER_ID, base: 'INR', fmt: fmtNum, sym: sym, onChange: boot})
// fmt(minor, ccy) -> grouped number string; sym(ccy) -> currency symbol.
window.KhataTransfers = (function(){
  let _el=null,_pid=null,_opts={},_data=null;

  function _fmt(minor){
    const f=_opts.fmt || function(m){ return (m/100).toLocaleString(); };
    return (_opts.sym ? _opts.sym(_opts.base||'INR') : '') + f(minor, _opts.base||'INR');
  }
  function _e(tag, cls, text){
    const n=document.createElement(tag);
    if(cls) n.className=cls;
    if(text!==undefined && text!==null) n.textContent=text;
    return n;
  }
  async function _load(){
    try{
      const r = await fetch('/api/plans/'+_pid+'/hops');
      if(!r.ok) return {in_transit_minor:0, chains:[]};
      return await r.json();
    }catch(e){ return {in_transit_minor:0, chains:[]}; }
  }
  async function _post(url, body){
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify(body||{})});
    if(!r.ok){
      const e = await r.json().catch(()=>({}));
      alert(e.detail || e.error || 'Action failed.');
      return false;
    }
    return true;
  }
  async function _act(url, body){
    if(await _post(url, body)){ await refresh(); if(_opts.onChange) _opts.onChange(); }
  }

  function _badge(h){
    if(h.is_terminal) return ['delivered','pos'];
    if(h.resolution==='returned') return ['returned',''];
    if(h.resolution==='fee') return ['fee','neg'];
    if(h.outstanding_minor>0) return ['holding '+_fmt(h.outstanding_minor)+' · '+h.days_held+'d','warn'];
    return ['forwarded',''];
  }

  function _hopRow(h){
    const row=_e('div');
    row.style.cssText='display:flex;flex-direction:column;gap:4px;padding:10px 0;border-bottom:1px solid var(--line)';
    const top=_e('div');
    top.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';
    top.appendChild(_e('span','', (h.from.display||'?')+' → '+(h.to.display||'?')));
    const amt=_e('span','', _fmt(h.amount_minor));
    amt.style.cssText='font-family:JetBrains Mono,monospace;font-weight:600;margin-left:auto';
    top.appendChild(amt);
    row.appendChild(top);

    const meta=_e('div');
    meta.style.cssText='display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--ink-faint);flex-wrap:wrap';
    const d=new Date(h.occurred_at);
    meta.appendChild(_e('span','', isNaN(d.getTime())?'':d.toLocaleDateString()));
    if(h.method) meta.appendChild(_e('span','', h.method));
    const [btxt,btone]=_badge(h);
    const badge=_e('span','', btxt);
    badge.style.cssText='padding:1px 8px;border-radius:999px;border:1px solid var(--line);font-weight:600'+
      (btone==='pos'?';color:var(--pos)':btone==='neg'?';color:var(--neg)':btone==='warn'?';color:var(--primary)':'');
    meta.appendChild(badge);
    if(h.receipt_status==='pending') meta.appendChild(_e('span','', 'receipt pending'));
    if(h.receipt_status==='countered') meta.appendChild(_e('span','', 'countered '+_fmt(h.counter_amount_minor||0)));
    if(h.note) meta.appendChild(_e('span','', h.note));
    row.appendChild(meta);

    const acts=_e('div');
    acts.style.cssText='display:flex;gap:10px;font-size:12px';
    const mkBtn=(label, fn)=>{
      const b=_e('span','', label);
      b.style.cssText='color:var(--primary);font-weight:600;cursor:pointer';
      b.addEventListener('click', fn);
      acts.appendChild(b);
    };
    // receipt controls: only the receiving user acts
    if(h.receipt_status==='pending' && h.to.user_id===_opts.me){
      mkBtn('Confirm receipt', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'confirm'}));
      mkBtn('Counter…', ()=>{
        const v=prompt('Amount actually received:');
        if(v) _act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'counter', amount:v});
      });
    }
    // logger accepts a counter
    if(h.receipt_status==='countered' && h.logged_by_user_id===_opts.me){
      mkBtn('Accept counter', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'accept'}));
    }
    // resolve controls on open remainders
    if(h.outstanding_minor>0 && !h.is_terminal){
      mkBtn('Return', ()=>{
        if(confirm('Return the outstanding '+_fmt(h.outstanding_minor)+' to '+(h.from.display||'sender')+'?'))
          _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', {action:'return'});
      });
      mkBtn('Mark fee…', ()=>{
        const v=prompt('Fee amount (blank = full outstanding '+_fmt(h.outstanding_minor)+'):');
        if(v===null) return;
        const note=prompt('Fee note (e.g. agent commission):')||undefined;
        const body={action:'fee', note:note};
        if(v.trim()) body.amount=v;
        _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', body);
      });
    }
    if(acts.children.length) row.appendChild(acts);
    return row;
  }

  async function refresh(){
    if(!_el) return;
    _data = await _load();
    _el.textContent='';
    if(!_data.chains.length){ _el.style.display='none'; return; }
    _el.style.display='';
    const head=_e('div');
    head.style.cssText='display:flex;align-items:baseline;gap:10px;margin-bottom:4px';
    head.appendChild(_e('div','eyebrow','Money in transit'));
    const kpi=_e('span','', _fmt(_data.in_transit_minor));
    kpi.style.cssText='font-family:JetBrains Mono,monospace;font-weight:700;margin-left:auto';
    head.appendChild(kpi);
    _el.appendChild(head);
    for(const ch of _data.chains){
      const card=_e('div');
      card.style.cssText='margin-top:6px';
      const lbl=_e('div','', 'Chain #'+ch.chain_id+(ch.closed?' · closed':''));
      lbl.style.cssText='font-size:11px;color:var(--ink-faint);text-transform:uppercase;letter-spacing:.4px';
      card.appendChild(lbl);
      for(const h of ch.hops) card.appendChild(_hopRow(h));
      _el.appendChild(card);
    }
  }

  function openHops(){
    if(!_data) return [];
    const out=[];
    for(const ch of _data.chains)
      for(const h of ch.hops)
        if(h.outstanding_minor>0 && !h.is_terminal) out.push(h);
    return out;
  }

  function mount(el, pid, opts){ _el=el; _pid=pid; _opts=opts||{}; refresh(); }
  return {mount, refresh, openHops};
})();
