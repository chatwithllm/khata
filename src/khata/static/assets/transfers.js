// Money-in-transit panel + chain timeline for payment chains.
// Mounts into a container on plan detail pages:
//   KhataTransfers.mount(document.getElementById('transit-panel'), PID,
//     {me: USER_ID, base: 'INR', fmt: fmtNum, sym: sym, onChange: boot, onEdit: openHopEdit})
// fmt(minor, ccy) -> grouped number string; sym(ccy) -> currency symbol.
// onEdit(hop) — optional; when given, an Edit action appears for the hop's
// logger / plan owner and delegates to the page (slide-over with attachments).
// Rendering follows the ledger idiom: .ph header, .lrow rows, .l1/.amt/.l2/.l2r, .pill chips.
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

  // status chip: text + tone class matching the ledger pill palette
  function _statusChip(h){
    if(h.is_terminal) return _e('span','pill f','delivered');
    if(h.resolution==='returned') return _e('span','pill','returned');
    if(h.resolution==='fee') return _e('span','pill m','fee');
    if(h.outstanding_minor>0){
      const c=_e('span','pill m','holding '+_fmt(h.outstanding_minor)+(h.days_held?' · '+h.days_held+'d':''));
      c.style.color='var(--accent-dk)'; c.style.fontWeight='700';
      return c;
    }
    return _e('span','pill','forwarded');
  }

  function _dateTxt(iso){
    const d=new Date(iso);
    if(isNaN(d.getTime())) return '';
    const M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return String(d.getDate()).padStart(2,'0')+' '+M[d.getMonth()]+' '+d.getFullYear();
  }

  function _link(label, fn){
    const b=_e('span','proof', label);
    b.style.cssText='cursor:pointer;user-select:none';
    b.tabIndex=0; b.setAttribute('role','button');
    b.addEventListener('click', fn);
    b.addEventListener('keydown', e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); fn(); } });
    return b;
  }

  function _hopRow(h, hopById){
    const row=_e('div','lrow');
    // l1 — who → whom (title line)
    row.append(_e('div','l1', (h.from.display||'?')+' → '+(h.to.display||'?')));

    // amt — mono, right aligned like ledger rows
    const amt=_e('div','amt');
    const s=_e('span','symword'); s.textContent=_opts.sym?_opts.sym(_opts.base||'INR'):'';
    const f=_opts.fmt || function(m){ return (m/100).toLocaleString(); };
    const n=_e('span'); n.textContent=f(h.amount_minor, _opts.base||'INR');
    amt.append(s,n);
    row.append(amt);

    // l2 — date · note
    const l2=_e('div','l2'); l2.style.cssText='display:flex;align-items:center;gap:6px;flex-wrap:wrap';
    l2.append(_e('span', null, _dateTxt(h.occurred_at)));
    if(h.note){ l2.append(_e('span',null,'·')); l2.append(_e('span', null, h.note)); }
    row.append(l2);

    // composition — a merged hop spells out whose money it carries:
    // "= $1,500 from Chamu + $500 Narshima's own"
    if((h.sources||[]).some(s=>s.source_hop_id!==null) && h.sources.length>=1){
      const parts=[];
      for(const s of h.sources){
        if(s.source_hop_id===null){
          parts.push(_fmt(s.amount_minor)+' '+(h.from.display||'own')+"'s own");
        }else{
          const up=hopById[s.source_hop_id];
          parts.push(_fmt(s.amount_minor)+' from '+((up&&up.from.display)||'chain'));
        }
      }
      const comp=_e('div','l2','= '+parts.join(' + '));
      comp.style.cssText='color:var(--accent-dk);font-weight:600';
      row.append(comp);
    }

    // l2r — chips + actions
    const l2r=_e('div','l2r');
    if(h.method) l2r.append(_e('span','pill m', h.method));
    l2r.append(_statusChip(h));
    if(h.receipt_status==='pending') l2r.append(_e('span','pill','receipt pending'));
    if(h.receipt_status==='countered') l2r.append(_e('span','pill','countered '+_fmt(h.counter_amount_minor||0)));
    if(h.has_proof) l2r.append(_e('span','pill f','proof'+(h.attachment_count>1?' ×'+h.attachment_count:'')));

    // receipt actions — the receiving user acts
    if(h.receipt_status==='pending' && h.to.user_id===_opts.me){
      l2r.append(_link('Confirm receipt', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'confirm'})));
      l2r.append(_link('Counter…', ()=>{
        const v=prompt('Amount actually received:');
        if(v) _act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'counter', amount:v});
      }));
    }
    // logger accepts a counter
    if(h.receipt_status==='countered' && h.logged_by_user_id===_opts.me){
      l2r.append(_link('Accept counter', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'accept'})));
    }
    // resolve actions on open remainders
    if(h.outstanding_minor>0 && !h.is_terminal){
      l2r.append(_link('Return', ()=>{
        if(confirm('Return the outstanding '+_fmt(h.outstanding_minor)+' to '+(h.from.display||'sender')+'?'))
          _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', {action:'return'});
      }));
      l2r.append(_link('Mark fee…', ()=>{
        const v=prompt('Fee amount (blank = full outstanding '+_fmt(h.outstanding_minor)+'):');
        if(v===null) return;
        const note=prompt('Fee note (e.g. agent commission):')||undefined;
        const body={action:'fee', note:note};
        if(v.trim()) body.amount=v;
        _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', body);
      }));
    }
    // edit — hop logger or plan owner; delegates to the page slide-over
    if(_opts.onEdit && (h.logged_by_user_id===_opts.me || _opts.isOwner)){
      l2r.append(_link('✎ edit', ()=>_opts.onEdit(h)));
    }
    row.append(l2r);
    return row;
  }

  async function refresh(){
    if(!_el) return;
    _data = await _load();
    _el.textContent='';
    if(!_data.chains.length){ _el.style.display='none'; return; }
    _el.style.display='';

    // panel header — ledger idiom: .ph with title + meta on the right
    const ph=_e('div','ph');
    const t=_e('div','t','Money in transit'); t.style.fontSize='16px';
    const right=_e('div'); right.style.cssText='display:flex;align-items:center;gap:12px';
    right.append(_e('div','meta', _fmt(_data.in_transit_minor)+' in transit'));
    ph.append(t, right);
    _el.append(ph);

    // hop lookup across all chains — composition lines name upstream senders
    const hopById={};
    for(const ch of _data.chains) for(const h of ch.hops) hopById[h.id]=h;

    const body=_e('div','ledger fillrows');
    for(const ch of _data.chains){
      const lbl=_e('div',null,'Chain #'+ch.chain_id+(ch.closed?' · closed':''));
      lbl.style.cssText='font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);padding:12px 22px 0';
      body.append(lbl);
      for(const h of ch.hops) body.append(_hopRow(h, hopById));
    }
    _el.append(body);
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
