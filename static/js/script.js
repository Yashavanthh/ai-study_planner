// ── Flash auto-dismiss ───────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".flash").forEach((el, i) => {
    setTimeout(() => {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 4000 + i * 300);
  });
});

// ── Password show/hide toggle ────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".pwd-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
    });
  });
});

// ── Difficulty picker — keep selected state visible ──────────────
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".diff-btn input").forEach(radio => {
    radio.addEventListener("change", () => {
      document.querySelectorAll(".diff-btn span").forEach(s => s.style.cssText = "");
    });
  });
});
