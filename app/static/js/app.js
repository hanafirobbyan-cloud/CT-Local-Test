/* Interaksi ringan tanpa framework. Dimuat dengan `defer`; aman bila JS nonaktif. */
(function () {
  "use strict";

  // Menu navigasi (mobile)
  document.querySelectorAll("[data-nav-toggle]").forEach(function (btn) {
    var target = document.getElementById(btn.getAttribute("aria-controls"));
    if (!target) return;
    btn.addEventListener("click", function () {
      var open = target.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    target.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        target.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      });
    });
  });

  // Hitung mundur acara
  var cd = document.querySelector("[data-countdown]");
  if (cd) {
    var target = Date.parse(cd.getAttribute("data-countdown"));
    var units = {};
    cd.querySelectorAll("[data-unit]").forEach(function (el) { units[el.getAttribute("data-unit")] = el; });
    var pad = function (n) { return n < 10 ? "0" + n : String(n); };
    var tick = function () {
      var diff = Math.max(0, target - Date.now());
      var s = Math.floor(diff / 1000);
      units.days.textContent = Math.floor(s / 86400);
      units.hours.textContent = pad(Math.floor((s % 86400) / 3600));
      units.minutes.textContent = pad(Math.floor((s % 3600) / 60));
      units.seconds.textContent = pad(s % 60);
      if (diff === 0) { clearInterval(timer); }
    };
    var timer = setInterval(tick, 1000);
    tick();
  }

  // Field NIM/prodi hanya untuk kategori mahasiswa
  var cat = document.querySelector("[data-category-select]");
  if (cat) {
    var sync = function () {
      var show = cat.value === "mahasiswa";
      document.querySelectorAll("[data-student-fields]").forEach(function (el) { el.hidden = !show; });
    };
    cat.addEventListener("change", sync);
    sync();
  }

  // Konfirmasi untuk aksi berisiko
  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      if (!window.confirm(el.getAttribute("data-confirm"))) { ev.preventDefault(); }
    });
  });

  // Salin ke clipboard
  document.querySelectorAll("[data-copy]").forEach(function (el) {
    el.addEventListener("click", function () {
      var text = el.getAttribute("data-copy");
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function () {
          var old = el.textContent; el.textContent = "Tersalin ✓";
          setTimeout(function () { el.textContent = old; }, 1500);
        });
      } else { window.prompt("Salin tautan:", text); }
    });
  });

  // Tampilkan field terkait checkbox (mis. alasan override publikasi Zoom)
  document.querySelectorAll("[data-toggle-target]").forEach(function (box) {
    var target = document.querySelector(box.getAttribute("data-toggle-target"));
    if (!target) return;
    var sync = function () { target.hidden = !box.checked; };
    box.addEventListener("change", sync);
    sync();
  });
})();
