async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

const joinForm = document.getElementById("joinExamForm");
const accessCode = joinForm.dataset.accessCode;
const joinMessage = document.getElementById("joinMessage");

requestJSON(`/api/public-exams/${accessCode}`).then(({ ok, data }) => {
  const availability = document.getElementById("examAvailability");
  if (!ok || !data.success) {
    availability.textContent = data.message || "Không thể tải thông tin bài thi.";
    document.getElementById("joinButton").disabled = true;
  } else if (!data.is_open) {
    availability.textContent = `Bài thi chưa mở. Thời gian bắt đầu: ${formatVietnamDateTime(data.start_time)}`;
  } else if (!data.password_configured) {
    availability.textContent = "Giáo viên chưa kích hoạt mật khẩu phòng thi.";
    document.getElementById("joinButton").disabled = true;
  } else {
    availability.textContent = "Nhập thông tin sinh viên và mật khẩu do giáo viên cung cấp.";
  }
}).catch(() => {
  document.getElementById("examAvailability").textContent = "Không kết nối được máy chủ.";
});

joinForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = document.getElementById("joinButton");
  button.disabled = true;
  joinMessage.textContent = "Đang xác thực...";
  const formData = new FormData(joinForm);
  try {
    const { ok, data } = await requestJSON(`/api/public-exams/${accessCode}/start`, {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(formData.entries())),
    });
    if (!ok || !data.success) {
      joinMessage.textContent = data.message || "Không thể vào thi.";
      return;
    }
    sessionStorage.setItem(`public-exam-token-${data.session_id}`, data.session_token);
    window.location.href = `/exam/${accessCode}/workspace/${data.session_id}`;
  } catch (error) {
    joinMessage.textContent = "Không kết nối được máy chủ.";
  } finally {
    button.disabled = false;
  }
});
