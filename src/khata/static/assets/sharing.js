// Reusable plan-sharing panel — mountSharing(planId, containerEl). XSS-safe (textContent only).
(function () {
  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
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
    for (const m of members) {
      const row = el("div");
      row.style.display = "flex"; row.style.alignItems = "center"; row.style.gap = "10px";
      row.style.padding = "8px 0"; row.style.borderBottom = "1px solid var(--line)";
      const nm = el("div");
      nm.appendChild(el("div", null, m.display_name || m.email));
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
    }
    box.appendChild(list);

    if (isOwner) {
      const form = el("div");
      form.style.display = "flex"; form.style.gap = "8px"; form.style.marginTop = "10px";
      const input = el("input"); input.placeholder = "add by email"; input.style.flex = "1";
      input.style.fontFamily = "inherit"; input.style.fontSize = "14px"; input.style.padding = "8px 11px";
      input.style.border = "1px solid var(--line)"; input.style.borderRadius = "9px";
      input.style.background = "var(--card)"; input.style.color = "var(--ink)";
      const btn = el("button", "btn", "Add");
      const err = el("div", "err");
      err.style.color = "var(--neg)"; err.style.fontSize = "13px"; err.style.minHeight = "16px"; err.style.marginTop = "6px";
      btn.addEventListener("click", async () => {
        err.textContent = "";
        const res = await fetch("/api/plans/" + planId + "/members", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: input.value }) });
        if (res.ok) { input.value = ""; mountSharing(planId, box); return; }
        const e = await res.json().catch(() => ({}));
        err.textContent = ({ user_not_found: "No account with that email.",
                             already_member: "Already shared with them." })[e.error] || e.detail || "Could not add.";
      });
      form.append(input, btn); box.appendChild(form); box.appendChild(err);
    }
  }
  window.mountSharing = mountSharing;
})();
