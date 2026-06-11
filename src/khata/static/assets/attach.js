/* attach.js — supporting-proof attachments on a ledger entry.
 *
 *   mountAttachments(container, { planId, entryId, canModify })
 *
 * Lists existing proof (image thumbnails / file chips), and — when canModify — offers
 * "Add file" (images / PDF / Office docs, multiple) and "Take photo" (rear camera on a
 * phone). Images are downscaled client-side before upload (smaller DB + drops EXIF/GPS).
 * All DOM is built with createElement + textContent (rule K4: never innerHTML on data).
 */
(function () {
  const MAX_EDGE = 1600;            // downscale long edge of photos to this
  const ACCEPT = "image/*,application/pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx";

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function humanSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  // Downscale an image File to a JPEG/PNG Blob if it is large; else return it unchanged.
  function downscaleImage(file) {
    return new Promise((resolve) => {
      if (!file.type.startsWith("image/") || file.type === "image/heic") return resolve(file);
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = function () {
        const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
        if (scale >= 1) { URL.revokeObjectURL(url); return resolve(file); }
        const cv = document.createElement("canvas");
        cv.width = Math.round(img.width * scale);
        cv.height = Math.round(img.height * scale);
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
        URL.revokeObjectURL(url);
        const type = file.type === "image/png" ? "image/png" : "image/jpeg";
        cv.toBlob((b) => resolve(b || file), type, 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  function mountAttachments(container, opts) {
    const planId = opts.planId, entryId = opts.entryId, canModify = !!opts.canModify;
    container.textContent = "";
    const wrap = el("div", "att-wrap");
    const grid = el("div", "att-grid");
    const status = el("div", "att-status");
    wrap.append(grid);
    container.append(wrap);

    function tile(a) {
      const t = el("div", "att-tile");
      const link = el("a");
      link.href = "/api/attachments/" + a.id;
      link.target = "_blank";
      link.rel = "noopener";
      if (a.is_image) {
        const im = el("img");
        im.src = "/api/attachments/" + a.id;
        im.alt = a.filename;
        link.append(im);
      } else {
        const chip = el("div", "att-doc");
        chip.append(el("span", "att-ext", (a.filename.split(".").pop() || "file").toUpperCase()));
        chip.append(el("span", "att-name", a.filename));
        link.append(chip);
      }
      t.append(link);
      t.append(el("div", "att-size", humanSize(a.size)));
      if (canModify) {
        const x = el("button", "att-del", "✕");
        x.type = "button";
        x.title = "Remove";
        x.addEventListener("click", async (ev) => {
          ev.preventDefault();
          if (!confirm("Remove this attachment?")) return;
          const r = await fetch("/api/attachments/" + a.id, { method: "DELETE" });
          if (r.ok) load(); else status.textContent = "Could not remove file.";
        });
        t.append(x);
      }
      return t;
    }

    async function load() {
      grid.textContent = "";
      let items = [];
      try {
        const r = await fetch("/api/plans/" + planId + "/entries/" + entryId + "/attachments");
        if (r.ok) items = (await r.json()).attachments || [];
      } catch (e) { /* offline / transient */ }
      if (!items.length && !canModify) {
        grid.append(el("div", "att-empty", "No proof attached."));
      }
      items.forEach((a) => grid.append(tile(a)));
      if (canModify) grid.append(addControls());
    }

    function addControls() {
      const box = el("div", "att-add");
      // file picker
      const fileInput = el("input"); fileInput.type = "file";
      fileInput.accept = ACCEPT; fileInput.multiple = true; fileInput.style.display = "none";
      const pick = el("button", "att-btn", "+ Add file"); pick.type = "button";
      pick.addEventListener("click", () => fileInput.click());
      // camera (phones surface the rear camera with capture)
      const camInput = el("input"); camInput.type = "file";
      camInput.accept = "image/*"; camInput.capture = "environment"; camInput.style.display = "none";
      const cam = el("button", "att-btn", "📷 Take photo"); cam.type = "button";
      cam.addEventListener("click", () => camInput.click());
      [fileInput, camInput].forEach((inp) =>
        inp.addEventListener("change", () => uploadAll(Array.from(inp.files || []), inp)));
      box.append(pick, cam, fileInput, camInput, status);
      return box;
    }

    async function uploadAll(files, inputEl) {
      for (const f of files) {
        status.textContent = "Uploading " + f.name + "…";
        let blob = f;
        try { blob = await downscaleImage(f); } catch (e) { blob = f; }
        const fd = new FormData();
        fd.append("file", blob, f.name);
        try {
          const r = await fetch("/api/plans/" + planId + "/entries/" + entryId + "/attachments",
            { method: "POST", body: fd });
          if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            status.textContent = (d.detail || "Upload failed") + ".";
            continue;
          }
        } catch (e) { status.textContent = "Upload failed (network)."; continue; }
      }
      status.textContent = "";
      if (inputEl) inputEl.value = "";
      load();
      if (typeof opts.onChange === "function") opts.onChange();
    }

    load();
  }

  window.mountAttachments = mountAttachments;
})();
