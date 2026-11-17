async function submitProfileRequest(url, method, body) {
  const response = await fetch(url, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  return { ok: response.ok, data };
}

function showProfileMessage(element, text, isSuccess) {
  element.textContent = text;
  element.className = `message ${isSuccess ? "success" : "error"}`;
}

const profileForm = document.getElementById("studentProfileForm");
const profileMessage = document.getElementById("profileMessage");
const saveProfileButton = document.getElementById("saveProfileButton");
const passwordForm = document.getElementById("changePasswordForm");
const passwordMessage = document.getElementById("passwordMessage");
const savePasswordButton = document.getElementById("savePasswordButton");

profileForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!profileForm.reportValidity()) return;

  saveProfileButton.disabled = true;
  profileMessage.textContent = "";
  try {
    const { ok, data } = await submitProfileRequest(
      "/api/auth/student-profile",
      "PUT",
      {
        full_name: document.getElementById("profileFullName").value,
        student_id: document.getElementById("profileStudentId").value,
        class_name: document.getElementById("profileClassName").value,
      }
    );
    if (!ok || !data.success) {
      showProfileMessage(profileMessage, data.message || "Không thể lưu hồ sơ.", false);
      return;
    }

    document.getElementById("profileFullName").value = data.user.full_name;
    document.getElementById("profileStudentId").value = data.user.student_id;
    document.getElementById("profileClassName").value = data.user.class_name;
    const userName = document.querySelector(".student-layout .teacher-name");
    const userAvatar = document.querySelector(".student-layout .teacher-avatar");
    if (userName) userName.textContent = data.user.full_name;
    if (userAvatar) userAvatar.textContent = data.user.full_name.charAt(0);
    showProfileMessage(profileMessage, data.message || "Đã cập nhật thông tin cá nhân.", true);
  } catch (error) {
    showProfileMessage(profileMessage, "Không thể kết nối máy chủ để lưu hồ sơ.", false);
  } finally {
    saveProfileButton.disabled = false;
  }
});

passwordForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!passwordForm.reportValidity()) return;

  const newPassword = document.getElementById("newPassword").value;
  const confirmPassword = document.getElementById("confirmPassword").value;
  if (newPassword !== confirmPassword) {
    showProfileMessage(passwordMessage, "Mật khẩu mới và xác nhận mật khẩu không khớp.", false);
    document.getElementById("confirmPassword").focus();
    return;
  }

  savePasswordButton.disabled = true;
  passwordMessage.textContent = "";
  try {
    const { ok, data } = await submitProfileRequest(
      "/api/auth/change-password",
      "POST",
      {
        current_password: document.getElementById("currentPassword").value,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }
    );
    if (!ok || !data.success) {
      showProfileMessage(passwordMessage, data.message || "Không thể đổi mật khẩu.", false);
      return;
    }

    passwordForm.reset();
    showProfileMessage(passwordMessage, data.message || "Đã đổi mật khẩu thành công.", true);
  } catch (error) {
    showProfileMessage(passwordMessage, "Không thể kết nối máy chủ để đổi mật khẩu.", false);
  } finally {
    savePasswordButton.disabled = false;
  }
});
