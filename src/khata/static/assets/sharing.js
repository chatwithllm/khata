// Reusable plan-sharing panel — mountSharing(planId, containerEl). XSS-safe (textContent only).
(function () {
  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  const AV_COLORS = ["#b06a32", "#3d6b6e", "#7a5ea8", "#5a7a3a", "#a8506a", "#3a6a9a"];
  // a small circular avatar: the member's photo, or a coloured initial
  function memberAvatar(m, idx) {
    const a = el("div");
    a.style.cssText = "width:30px;height:30px;border-radius:50%;flex:none;display:grid;place-items:center;"
      + "overflow:hidden;color:#fff;font-weight:700;font-size:13px;line-height:1";
    if (m.avatar) {
      a.style.backgroundImage = 'url("' + m.avatar + '")';
      a.style.backgroundSize = "cover"; a.style.backgroundPosition = "center";
    } else {
      a.style.background = AV_COLORS[idx % AV_COLORS.length];
      a.textContent = ((m.display_name || m.email || "?")[0] || "?").toUpperCase();
    }
    return a;
  }

  async function mountSharing(planId, box) {
    box.textContent = "";
    let meId = null;
    try { const me = await fetch("/api/auth/me"); if (me.ok) meId = (await me.json()).user.id; } catch (_) {}
    const r = await fetch("/api/plans/" + planId + "/members");
    if (!r.ok) return;
    const members = (await r.json()).members || [];
    const owner = members.find((m) => m.role === "owner");
    const isOwner = owner && meId === owner.user_id;

    const h = el("h2", null, "Shared with");
    h.style.fontFamily = "Fraunces, serif"; h.style.fontSize = "19px"; h.style.marginBottom = "10px";
    box.appendChild(h);

    const list = el("div");
    members.forEach((m, idx) => {
      const row = el("div");
      row.style.display = "flex"; row.style.alignItems = "center"; row.style.gap = "10px";
      row.style.padding = "8px 0"; row.style.borderBottom = "1px solid var(--line)";
      row.appendChild(memberAvatar(m, idx));
      const nm = el("div");
      const nameRow = el("div");
      nameRow.style.display = "flex"; nameRow.style.alignItems = "center"; nameRow.style.gap = "7px";
      nameRow.appendChild(el("span", null, m.display_name || m.email));
      if (m.status === "invited") {
        const pend = el("span", null, "pending");
        pend.style.fontSize = "10.5px"; pend.style.fontWeight = "700"; pend.style.letterSpacing = ".04em";
        pend.style.textTransform = "uppercase"; pend.style.padding = "2px 7px"; pend.style.borderRadius = "999px";
        pend.style.background = "color-mix(in srgb, var(--primary) 18%, transparent)";
        pend.style.color = "var(--accent-dk)";
        pend.title = "Invited — awaiting their approval";
        nameRow.appendChild(pend);
      }
      nm.appendChild(nameRow);
      const sub = el("div", "muted", m.email + " · " + m.role); sub.style.fontSize = "12px";
      nm.appendChild(sub);
      row.appendChild(nm);
      if (isOwner && m.role !== "owner") {
        const rm = el("span", "tlink", "Remove");
        rm.style.marginLeft = "auto"; rm.style.color = "var(--neg)"; rm.style.cursor = "pointer";
        rm.addEventListener("click", async () => {
          await fetch("/api/plans/" + planId + "/members/" + m.user_id, { method: "DELETE" });
          mountSharing(planId, box);
        });
        row.appendChild(rm);
      }
      list.appendChild(row);
    });
    box.appendChild(list);

    if (isOwner) {
      const form = el("div");
      form.style.display = "flex"; form.style.gap = "8px"; form.style.marginTop = "10px";
      const input = el("input"); input.placeholder = "add by email"; input.style.flex = "1";
      input.style.fontFamily = "inherit"; input.style.fontSize = "14px"; input.style.padding = "8px 11px";
      input.style.border = "1px solid var(--line)"; input.style.borderRadius = "9px";
      input.style.background = "var(--card)"; input.style.color = "var(--ink)";
      const roleSel = el("select");
      roleSel.style.cssText = "flex:none;font-family:inherit;font-size:13px;padding:8px 6px;"
        + "border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink)";
      [["contributor", "contributor"], ["seller", "seller"]].forEach(([v, t]) => {
        const o = el("option", null, t); o.value = v; roleSel.appendChild(o);
      });
      roleSel.title = "Role — sellers see the plan read-only";
      const btn = el("button", "btn", "Add");
      // detail pages have no .btn stylesheet rule — style inline (flex:none so the
      // row can't squeeze it below tap size)
      btn.style.cssText = "flex:none;font-family:inherit;font-size:14px;font-weight:600;"
        + "padding:9px 18px;border:none;border-radius:9px;cursor:pointer;"
        + "background:var(--primary);color:#fff";
      const err = el("div", "err");
      err.style.color = "var(--neg)"; err.style.fontSize = "13px"; err.style.minHeight = "16px"; err.style.marginTop = "6px";
      btn.addEventListener("click", async () => {
        err.textContent = "";
        const res = await fetch("/api/plans/" + planId + "/members", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: input.value, role: roleSel.value }) });
        if (res.ok) { input.value = ""; mountSharing(planId, box); return; }
        const e = await res.json().catch(() => ({}));
        err.textContent = ({ user_not_found: "No account with that email.",
                             already_member: "Already shared with them." })[e.error] || e.detail || "Could not add.";
      });
      form.append(input, roleSel, btn); box.appendChild(form); box.appendChild(err);
    }
  }
  window.mountSharing = mountSharing;
})();
