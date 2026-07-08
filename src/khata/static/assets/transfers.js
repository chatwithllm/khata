// Money-in-transit panel + chain timeline for payment chains.
// Mounts into a container on plan detail pages:
//   KhataTransfers.mount(document.getElementById('transit-panel'), PID,
//     {me: USER_ID, base: 'INR', fmt: fmtNum, sym: sym, onChange: boot, onEdit: openHopEdit})
// fmt(minor, ccy) -> grouped number string; sym(ccy) -> currency symbol.
// onEdit(hop) — optional; shows an Edit action for the hop's logger / plan owner.
//
// Design: each chain renders as a literal rail — a vertical line with a node per
// hop (hollow = money still moving, filled = delivered / resolved). Notes are
// cleaned at display time: repeated "$X USD @rate — " prefixes collapse into one
// mono fx token in the meta line; the human comment is what remains.
window.KhataTransfers = (function(){
  let _el=null,_pid=null,_opts={},_data=null;

  const CSS = `
.trx-chain{border-top:1px solid var(--line);padding:4px 22px 10px}
.trx-chain:first-of-type{border-top:0}
.trx-eyebrow{display:flex;justify-content:space-between;align-items:baseline;
  font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-faint);padding:14px 0 4px}
.trx-hop{display:grid;grid-template-columns:18px 1fr auto;column-gap:12px;row-gap:2px;
  padding:8px 0;position:relative}
.trx-rail{grid-row:1 / span 5;position:relative}
.trx-rail::before{content:'';position:absolute;left:8px;top:-10px;bottom:-10px;
  width:2px;background:var(--line)}
.trx-hop:first-of-type .trx-rail::before{top:8px}
.trx-hop:last-of-type .trx-rail::before{bottom:auto;height:18px}
.trx-node{position:relative;z-index:1;width:11px;height:11px;border-radius:50%;
  margin:5px 0 0 3px;border:2px solid var(--ink-faint);background:var(--card)}
.trx-node.hold{border-color:var(--accent-dk)}
.trx-node.done{border-color:var(--pos);background:var(--pos)}
.trx-node.dead{border-color:var(--ink-faint);background:var(--ink-faint)}
.trx-route{font-weight:600;font-size:14px;color:var(--ink)}
.trx-amt{grid-row:1;font-family:'JetBrains Mono',monospace;font-weight:600;font-size:14px;
  text-align:right;white-space:nowrap}
.trx-meta{grid-column:2;display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  font-size:11.5px;color:var(--ink-faint)}
.trx-fx{font-family:'JetBrains Mono',monospace;font-size:10.5px}
.trx-chip{padding:1px 8px;border:1px solid var(--line);border-radius:999px;
  font-size:10.5px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.trx-chip.hold{color:var(--accent-dk);border-color:var(--accent-dk)}
.trx-chip.done{color:var(--pos);border-color:var(--pos)}
.trx-chip.warn{color:var(--neg);border-color:var(--neg)}
.trx-note{grid-column:2;font-size:12px;color:var(--ink-faint);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;max-width:58ch}
.trx-comp{grid-column:2;font-size:11.5px;font-weight:600;color:var(--accent-dk);
  font-family:'JetBrains Mono',monospace}
.trx-acts{grid-column:2 / -1;display:flex;gap:14px;font-size:11.5px;font-weight:600;
  padding-top:2px}
.trx-acts span{color:var(--primary);cursor:pointer;user-select:none}
.trx-acts span:hover{text-decoration:underline}
.trx-acts span.quiet{color:var(--ink-faint)}
@media(max-width:640px){.trx-note{max-width:100%}}
`;
  function _injectCss(){
    if(document.getElementById('trx-css')) return;
    const s=document.createElement('style'); s.id='trx-css'; s.textContent=CSS;
    document.head.appendChild(s);
  }

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

  // Collapse repeated "$1,500 USD @94.97 — " prefixes (accumulated by edits)
  // into one fx token + the human comment that remains.
  function _cleanNote(note){
    let fx=null, rest=(note||'').trim();
    const re=/^\$?([\d,\.]+)\s+([A-Z]{3})\s+@([\d\.]+)\s*(?:—\s*)?/;
    let m, guard=0;
    while((m=re.exec(rest)) && guard++<10){
      if(!fx) fx='$'+m[1]+' @'+m[3];
      rest=rest.slice(m[0].length).trim();
    }
    return {fx: fx, rest: rest};
  }

  function _nodeCls(h){
    if(h.is_terminal) return 'done';
    if(h.resolution==='returned'||h.resolution==='fee') return 'dead';
    if(h.outstanding_minor>0) return 'hold';
    return '';
  }
  function _statusChip(h){
    if(h.is_terminal) return _e('span','trx-chip done','delivered');
    if(h.resolution==='returned') return _e('span','trx-chip','returned');
    if(h.resolution==='fee') return _e('span','trx-chip warn','fee');
    if(h.outstanding_minor>0)
      return _e('span','trx-chip hold','holding '+_fmt(h.outstanding_minor)+(h.days_held?' · '+h.days_held+'d':''));
    return _e('span','trx-chip','forwarded');
  }

  function _dateTxt(iso){
    const d=new Date(iso);
    if(isNaN(d.getTime())) return '';
    const M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return String(d.getDate()).padStart(2,'0')+' '+M[d.getMonth()]+' '+d.getFullYear();
  }

  function _link(label, fn, quiet){
    const b=_e('span',quiet?'quiet':null,label);
    b.tabIndex=0; b.setAttribute('role','button');
    b.addEventListener('click', fn);
    b.addEventListener('keydown', e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); fn(); } });
    return b;
  }

  function _hopRow(h, hopById){
    const row=_e('div','trx-hop');

    const rail=_e('div','trx-rail');
    rail.append(_e('div','trx-node '+_nodeCls(h)));
    row.append(rail);

    row.append(_e('div','trx-route',(h.from.display||'?')+' → '+(h.to.display||'?')));
    row.append(_e('div','trx-amt',_fmt(h.amount_minor)));

    const cleaned=_cleanNote(h.note);
    const meta=_e('div','trx-meta');
    meta.append(_e('span',null,_dateTxt(h.occurred_at)));
    if(h.method) meta.append(_e('span',null,h.method));
    if(cleaned.fx) meta.append(_e('span','trx-fx',cleaned.fx));
    meta.append(_statusChip(h));
    if(h.receipt_status==='pending') meta.append(_e('span','trx-chip','receipt pending'));
    if(h.receipt_status==='countered') meta.append(_e('span','trx-chip hold','countered '+_fmt(h.counter_amount_minor||0)));
    if(h.has_proof){
      const pf=_e('span','trx-chip','proof'+(h.attachment_count>1?' ×'+h.attachment_count:''));
      // hover preview helper lives on pages that define it (asset-detail)
      if(window.attachProofPreview) window.attachProofPreview(pf, '/api/plans/'+_pid+'/hops/'+h.id+'/attachments');
      meta.append(pf);
    }
    row.append(meta);

    if(cleaned.rest){
      const note=_e('div','trx-note',cleaned.rest);
      note.title=cleaned.rest;
      row.append(note);
    }

    // merged hop: spell out whose money it carries
    if((h.sources||[]).some(s=>s.source_hop_id!==null)){
      const parts=[];
      for(const s of h.sources){
        if(s.source_hop_id===null){
          parts.push(_fmt(s.amount_minor)+' '+(h.from.display||'own')+"'s own");
        }else{
          const up=hopById[s.source_hop_id];
          parts.push(_fmt(s.amount_minor)+' from '+((up&&up.from.display)||'chain'));
        }
      }
      row.append(_e('div','trx-comp','= '+parts.join('  +  ')));
    }

    const acts=_e('div','trx-acts');
    if(h.receipt_status==='pending' && h.to.user_id===_opts.me){
      acts.append(_link('Confirm receipt', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'confirm'})));
      acts.append(_link('Counter…', ()=>{
        const v=prompt('Amount actually received:');
        if(v) _act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'counter', amount:v});
      }));
    }
    if(h.receipt_status==='countered' && h.logged_by_user_id===_opts.me){
      acts.append(_link('Accept counter', ()=>_act('/api/plans/'+_pid+'/hops/'+h.id+'/receipt', {action:'accept'})));
    }
    if(h.outstanding_minor>0 && !h.is_terminal){
      acts.append(_link('Return', ()=>{
        if(confirm('Return the outstanding '+_fmt(h.outstanding_minor)+' to '+(h.from.display||'sender')+'?'))
          _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', {action:'return'});
      }, true));
      acts.append(_link('Mark fee…', ()=>{
        const v=prompt('Fee amount (blank = full outstanding '+_fmt(h.outstanding_minor)+'):');
        if(v===null) return;
        const note=prompt('Fee note (e.g. agent commission):')||undefined;
        const body={action:'fee', note:note};
        if(v.trim()) body.amount=v;
        _act('/api/plans/'+_pid+'/hops/'+h.id+'/resolve', body);
      }, true));
    }
    if(_opts.onEdit && (h.logged_by_user_id===_opts.me || _opts.isOwner)){
      acts.append(_link('Attach proof', ()=>_opts.onEdit(h)));
      acts.append(_link('Edit', ()=>_opts.onEdit(h), true));
    }
    if(acts.children.length) row.append(acts);
    return row;
  }

  async function refresh(){
    if(!_el) return;
    _injectCss();
    _data = await _load();
    _el.textContent='';
    if(!_data.chains.length){ _el.style.display='none'; return; }
    _el.style.display='';

    const ph=_e('div','ph');
    const t=_e('div','t','Money in transit'); t.style.fontSize='16px';
    const right=_e('div'); right.style.cssText='display:flex;align-items:center;gap:12px';
    right.append(_e('div','meta', _fmt(_data.in_transit_minor)+' in transit'));
    ph.append(t, right);
    _el.append(ph);

    const hopById={};
    for(const ch of _data.chains) for(const h of ch.hops) hopById[h.id]=h;

    for(const ch of _data.chains){
      const block=_e('div','trx-chain');
      const eyebrow=_e('div','trx-eyebrow');
      eyebrow.append(_e('span',null,'Chain #'+ch.chain_id));
      if(ch.closed) eyebrow.append(_e('span',null,'closed'));
      block.append(eyebrow);
      for(const h of ch.hops) block.append(_hopRow(h, hopById));
      _el.append(block);
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
