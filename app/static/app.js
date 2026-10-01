// 任务进度轮询 + 全选切换。无任何外部依赖。
(function () {
  "use strict";

  // ---- 全选 / 取消（点一次全选，再点取消全选）----
  document.querySelectorAll("[data-checkall-btn]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var name = btn.getAttribute("data-checkall-btn");
      var boxes = document.querySelectorAll('input[type="checkbox"][name="' + name + '"]');
      if (!boxes.length) return;
      var allChecked = Array.prototype.every.call(boxes, function (b) { return b.checked; });
      boxes.forEach(function (b) { b.checked = !allChecked; });
    });
  });
  document.querySelectorAll("input[data-checkall]").forEach(function (master) {
    master.addEventListener("change", function () {
      var boxes = document.querySelectorAll('input[type="checkbox"][name="' + master.getAttribute("data-checkall") + '"]');
      boxes.forEach(function (b) { b.checked = master.checked; });
    });
  });

  // ---- 弹窗（原生 <dialog>）：data-open-dialog 打开 / data-close-dialog 关闭 / Esc 自动 ----
  document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dlg = document.getElementById(btn.getAttribute("data-open-dialog"));
      if (dlg) dlg.showModal();
    });
  });
  document.querySelectorAll("[data-close-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dlg = btn.closest("dialog");
      if (dlg) dlg.close();
    });
  });

  // ---- 任务进度：自适应轮询 /api/jobs（有任务跑 3s，空闲 20s，页面在后台时暂停）----
  var box = document.getElementById("jobs-box");
  if (!box) return;

  var reloadArmed = false;
  var FAST = 3000, SLOW = 20000;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function renderJob(j) {
    var status = j.status === "running"
      ? '<span class="job-spin"></span><b>进行中</b>'
      : j.status === "succeeded"
        ? '<span class="badge badge-ok">完成</span>'
        : '<span class="badge badge-err">失败</span>';
    var logs = (j.log || []).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("");
    return '<div class="job-item job-' + j.status + '">' +
      '<div class="job-title">' + status + "<b>" + esc(j.title) + "</b>" +
      '<span class="muted small">#' + j.id + " · " + esc(j.created_at) + "</span></div>" +
      (j.error ? '<div class="small" style="color:var(--danger)">' + esc(j.error) + "</div>" : "") +
      (logs ? '<ul class="job-log">' + logs + "</ul>" : "") +
      "</div>";
  }

  function tick() {
    if (document.hidden) return Promise.resolve(SLOW); // 后台标签页不打接口
    return fetch("/api/jobs", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var jobs = data.jobs || [];
        var running = jobs.filter(function (j) { return j.status === "running"; });
        box.innerHTML = jobs.map(renderJob).join("");
        box.hidden = jobs.length === 0;

        // 页面标记了 autoreload 且曾有任务在跑 → 任务清零时刷新一次，让新产出出现
        if (document.body.hasAttribute("data-autoreload")) {
          if (running.length > 0) reloadArmed = true;
          else if (reloadArmed) window.location.reload();
        }
        return running.length > 0 ? FAST : SLOW;
      })
      .catch(function () { return SLOW; });
  }

  (function loop() { tick().then(function (delay) { setTimeout(loop, delay); }); })();
})();
