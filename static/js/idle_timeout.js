/**
 * idle_timeout.js — Tự động đăng xuất sau 50 phút không tương tác.
 *
 * - Đếm ngược 50 phút kể từ lần tương tác cuối (chuột, phím, scroll)
 * - Cứ 5 phút gửi /api/auth/ping để server gia hạn session
 * - Hết giờ -> gọi /api/auth/logout -> về /login?expired=idle
 * - Hiện cảnh báo trước 60 giây
 */
(function () {
  const IDLE_LIMIT_MS = 50 * 60 * 1000;       // 50 phút
  const WARN_BEFORE_MS = 60 * 1000;           // cảnh báo trước 60s
  const PING_INTERVAL_MS = 60 * 1000;         // ping mỗi 1 phút (phát hiện bị đá nhanh)

  let lastActivity = Date.now();
  let lastPing = Date.now();
  let warned = false;
  let warningEl = null;

  // ---------- Cập nhật lastActivity khi user tương tác ----------
  const events = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "click"];
  const onActivity = () => {
    lastActivity = Date.now();
    if (warned) hideWarning();
  };
  events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));

  // ---------- Cảnh báo ----------
  function showWarning(secondsLeft) {
    warned = true;
    if (!warningEl) {
      warningEl = document.createElement("div");
      warningEl.style.cssText = `
        position:fixed;bottom:20px;right:20px;z-index:99999;
        background:#e67e22;color:#fff;padding:14px 20px;border-radius:10px;
        font-family:sans-serif;font-size:14px;box-shadow:0 6px 20px rgba(0,0,0,.3);
        max-width:320px;
      `;
      document.body.appendChild(warningEl);
    }
    warningEl.innerHTML = `
      ⚠️ Bạn sắp bị đăng xuất do không hoạt động.<br>
      Còn <strong>${secondsLeft}</strong> giây. Di chuyển chuột để tiếp tục.
    `;
  }

  function hideWarning() {
    warned = false;
    if (warningEl) {
      warningEl.remove();
      warningEl = null;
    }
  }

  // ---------- Vòng lặp check mỗi giây ----------
  setInterval(() => {
    const idle = Date.now() - lastActivity;
    const left = IDLE_LIMIT_MS - idle;

    if (left <= 0) {
      doLogout("idle");
      return;
    }

    if (left <= WARN_BEFORE_MS) {
      showWarning(Math.ceil(left / 1000));
    } else if (warned) {
      hideWarning();
    }
  }, 1000);

  // ---------- Ping server để server biết user còn active ----------
    // ---------- Ping server để vừa giữ session vừa phát hiện bị đá ----------
  setInterval(async () => {
    if (loggingOut) return;
    // Chỉ ping khi user còn tương tác (tránh ping khi đã idle)
    if (Date.now() - lastActivity > IDLE_LIMIT_MS) return;

    lastPing = Date.now();
    try {
      const res = await fetch("/api/auth/ping", {
        method: "POST",
        credentials: "include",
      });

      if (res.status === 401) {
        // Bị đá (another_login / idle_timeout / session_not_found)
        const data = await res.json().catch(() => ({}));
        let reason = data.reason || "session_not_found";
        if (reason.startsWith("revoked:")) reason = reason.split(":")[1];
        window.location.href = `/login?expired=${reason}`;
      }
    } catch (_) { /* lỗi mạng, bỏ qua */ }
  }, PING_INTERVAL_MS);

  // ---------- Logout ----------
  let loggingOut = false;
  async function doLogout(reason) {
    if (loggingOut) return;
    loggingOut = true;
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch (_) { /* ignore */ }
    window.location.href = `/login?expired=${reason}`;
  }

  // Cho phép gọi thủ công nếu cần
  window.__idleLogout = doLogout;
    // ---------- Bắt buộc logout khi bị đá giữa chừng ----------
  // Trình duyệt không tự đá khi có session khác -> phải ping mới biết.
  // Nhưng khi user click link bất kỳ, before_request của Flask trả 401/redirect.
  // Đoạn dưới chỉ để phòng hờ khi user mở tab cũ đã bị đá.
  window.addEventListener("focus", async () => {
    if (loggingOut) return;
    try {
      const res = await fetch("/api/auth/me", { credentials: "include" });
      if (res.status === 401) {
        const data = await res.json().catch(() => ({}));
        let reason = data.reason || "session_not_found";
        if (reason.startsWith("revoked:")) reason = reason.split(":")[1];
        window.location.href = `/login?expired=${reason}`;
      }
    } catch (_) {}
  });
})();