(function () {
  const endpoint = "/api/teacher/account-settings";
  const settings = {
    registration_blocked: false,
    student_login_maintenance: false,
  };
  const statusElements = {
    registration_blocked: document.getElementById("registrationState"),
    student_login_maintenance: document.getElementById("maintenanceState"),
  };
  const messageElement = document.getElementById("accountSettingsMessage");

  function setMessage(message, type = "") {
    messageElement.textContent = message;
    messageElement.className = `message account-settings-message ${type}`;
  }

  function renderSetting(key) {
    const enabled = settings[key];
    const button = document.querySelector(
      `[data-setting-toggle="${key}"]`
    );
    const status = statusElements[key];
    status.textContent = enabled ? "Đang bật" : "Đang tắt";
    status.classList.toggle("is-enabled", enabled);
    status.classList.toggle("is-disabled", !enabled);
    button.textContent = key === "registration_blocked"
      ? enabled ? "Cho phép tạo tài khoản" : "Chặn tạo tài khoản"
      : enabled ? "Tắt chế độ bảo trì" : "Bật chế độ bảo trì";
    button.dataset.enabled = String(enabled);
    button.setAttribute("aria-pressed", String(enabled));
    button.disabled = false;
  }

  async function readResponse(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      throw new Error(data.message || "Không thể cập nhật cấu hình tài khoản.");
    }
    return data;
  }

  async function loadSettings() {
    try {
      const data = await readResponse(await fetch(endpoint, {
        credentials: "include",
      }));
      Object.assign(settings, data.settings);
      Object.keys(settings).forEach(renderSetting);
    } catch (error) {
      setMessage(error.message, "error");
      document.querySelectorAll("[data-setting-toggle]").forEach(button => {
        button.disabled = true;
      });
    }
  }

  document.querySelectorAll("[data-setting-toggle]").forEach(button => {
    button.addEventListener("click", async () => {
      const key = button.dataset.settingToggle;
      const enabled = button.dataset.enabled !== "true";
      button.disabled = true;
      setMessage("");
      try {
        const data = await readResponse(await fetch(endpoint, {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, enabled }),
        }));
        settings[key] = data.enabled;
        renderSetting(key);
        setMessage("Đã lưu cấu hình tài khoản.", "success");
      } catch (error) {
        button.disabled = false;
        setMessage(error.message, "error");
      }
    });
  });

  loadSettings();
})();
