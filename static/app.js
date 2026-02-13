function computeScore(p, c, h, t) {
    let score = 0.45 * t + 0.25 * h + 0.20 * c + 0.10 * p;
  
    // Same optional penalty rules as backend
    if (t <= 4) score = Math.min(score, 5.0);
    if (h <= 3) score -= 0.7;
  
    score = Math.max(0.0, Math.min(10.0, score));
    return Math.round(score * 10) / 10;
  }
  
  function updatePreview() {
    const p = Number(document.querySelector('input[name="presentation"]')?.value ?? 0);
    const c = Number(document.querySelector('input[name="coldness"]')?.value ?? 0);
    const h = Number(document.querySelector('input[name="head"]')?.value ?? 0);
    const t = Number(document.querySelector('input[name="taste"]')?.value ?? 0);
  
    const el = document.getElementById("scorePreview");
    if (el) el.textContent = computeScore(p, c, h, t).toFixed(1);
  }
  
  function wireSliders() {
    document.querySelectorAll(".slider").forEach((slider) => {
      const labelId = slider.getAttribute("data-label");
      const labelEl = labelId ? document.getElementById(labelId) : null;
  
      const onChange = () => {
        if (labelEl) labelEl.textContent = slider.value;
        updatePreview();
      };
  
      slider.addEventListener("input", onChange);
      onChange();
    });
  }
  
  function wireReset() {
    const btn = document.getElementById("resetBtn");
    if (!btn) return;
  
    btn.addEventListener("click", () => {
      // Defaults
      const defaults = { presentation: 8, coldness: 9, head: 8, taste: 9 };
      Object.entries(defaults).forEach(([name, val]) => {
        const el = document.querySelector(`input[name="${name}"]`);
        if (el) el.value = String(val);
      });
      const notes = document.querySelector(`textarea[name="notes"]`);
      if (notes) notes.value = "";
      wireSliders(); // refresh labels + preview
    });
  }
  
  document.addEventListener("DOMContentLoaded", () => {
    wireSliders();
    wireReset();
    updatePreview();
  });
  