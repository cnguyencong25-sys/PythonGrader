/**
 * auth.js - xử lý cả form login và register
 * Tự phát hiện đang ở trang nào dựa vào id form.
 */

const msgEl = document.getElementById("message");

function showMessage(text, type = "error") {
  if (!msgEl) return;
  msgEl.textContent = text;
  msgEl.className = "message " + type;
}

function dispatchLoginResult(success) {
  let playback = Promise.resolve();
  window.dispatchEvent(new CustomEvent("python-grader:login-result", {
    detail: {
      success,
      waitUntil(promise) {
        playback = Promise.resolve(promise);
      },
    },
  }));
  return playback;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",   // gửi/nhận HttpOnly cookie
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

// ============================================================
// FORM ĐĂNG NHẬP
// ============================================================
const loginForm = document.getElementById("loginForm");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = loginForm.querySelector('button[type="submit"]');
    btn.disabled = true;
    showMessage("Đang xử lý...", "");

    try {
      const { ok, data } = await postJSON("/api/auth/login", {
        email: document.getElementById("email").value.trim(),
        password: document.getElementById("password").value,
      });

      if (!ok || !data.success) {
        dispatchLoginResult(false);
        showMessage(data.message || "Đăng nhập thất bại.");
        btn.disabled = false;
        return;
      }

      const mascotPlayback = dispatchLoginResult(true);
      showMessage("Đăng nhập thành công! Đang chuyển...", "success");
      await mascotPlayback;
      window.location.href = data.redirect;
    } catch (err) {
      dispatchLoginResult(false);
      showMessage("Lỗi kết nối máy chủ.");
      btn.disabled = false;
    }
  });
}

// ============================================================
// FORM ĐĂNG KÝ
// ============================================================
const registerForm = document.getElementById("registerForm");
if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = registerForm.querySelector('button[type="submit"]');
    btn.disabled = true;
    showMessage("Đang xử lý...", "");

    const password = document.getElementById("password").value;
    const confirm = document.getElementById("confirm_password").value;

    if (password !== confirm) {
      dispatchLoginResult(false);
      showMessage("Mật khẩu xác nhận không khớp.");
      btn.disabled = false;
      return;
    }

    try {
      const { ok, data } = await postJSON("/api/auth/register", {
        email: document.getElementById("email").value.trim(),
        password,
        confirm_password: confirm,
      });

      if (!ok || !data.success) {
        dispatchLoginResult(false);
        showMessage(data.message || "Đăng ký thất bại.");
        btn.disabled = false;
        return;
      }

      const mascotPlayback = dispatchLoginResult(true);
      showMessage("Đăng ký thành công! Đang chuyển...", "success");
      await mascotPlayback;
      window.location.href = data.redirect;
    } catch (err) {
      dispatchLoginResult(false);
      showMessage("Lỗi kết nối máy chủ.");
      btn.disabled = false;
    }
  });
}
// ============================================================
// FORM HOÀN TẤT HỒ SƠ SINH VIÊN
// ============================================================
const profileForm = document.getElementById("profileForm");
if (profileForm) {
  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = profileForm.querySelector('button[type="submit"]');
    btn.disabled = true;
    showMessage("Đang lưu...", "");

    try {
      const { ok, data } = await postJSON("/api/auth/complete-profile", {
        full_name:  document.getElementById("full_name").value.trim(),
        class_name: document.getElementById("class_name").value.trim(),
        student_id: document.getElementById("student_id").value.trim(),
      });

      if (!ok || !data.success) {
        showMessage(data.message || "Không thể lưu hồ sơ.");
        btn.disabled = false;
        return;
      }

      showMessage("Lưu thành công! Đang chuyển...", "success");
      setTimeout(() => (window.location.href = data.redirect), 500);
    } catch (err) {
      showMessage("Lỗi kết nối máy chủ.");
      btn.disabled = false;
    }
  });
}

// ============================================================
// NÚT ĐĂNG XUẤT (dùng chung cho mọi trang)
// ============================================================
const logoutLink = document.getElementById("logoutLink");
if (logoutLink) {
  logoutLink.addEventListener("click", async (e) => {
    e.preventDefault();
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    window.location.href = "/login";
  });
}