async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const examList = document.getElementById("examList");
const messageEl = document.getElementById("message");
const passwordModal = document.getElementById("examPasswordModal");
const passwordForm = document.getElementById("examPasswordForm");
const passwordInput = document.getElementById("examPasswordInput");
const passwordMessage = document.getElementById("examPasswordMessage");
const examPasswordExamName = document.getElementById("examPasswordExamName");
let pendingExamId = null;

async function loadExams() {
  try {
    const { ok, data } = await fetchJSON("/api/student/exams");
    if (!ok || !data.success) {
      examList.innerHTML = "";
      messageEl.textContent = data.message || "Lỗi tải dữ liệu.";
      return;
    }

    const exams = data.exams || [];
    if (exams.length === 0) {
      examList.innerHTML = '<p class="empty-state">Chưa có bài kiểm tra nào.</p>';
      return;
    }

    examList.innerHTML = exams.map(e => {
      const now = new Date();
      const start = parseVietnamDateTime(e.start_time);
      const end = parseVietnamDateTime(e.end_time);
      
      let statusHtml = "";
      let btnHtml = "";

      if (e.is_completed) {
        // TRẠNG THÁI ĐÃ LÀM BÀI
        statusHtml = `<span class="exam-status exam-status-completed">Đã làm bài</span>`;
        btnHtml = `<button onclick="viewResult(${e.id})" class="btn-secondary exam-card-action exam-card-result">Xem kết quả</button>`;
      } else if (start && now < start) {
        statusHtml = `<span class="exam-status exam-status-pending">Chưa mở</span>`;
        btnHtml = `<button class="btn-secondary exam-card-action" disabled>Chưa đến giờ</button>`;
      } else if (end && now > end) {
        statusHtml = `<span class="exam-status exam-status-closed">Đã đóng</span>`;
        btnHtml = `<button class="btn-secondary exam-card-action" disabled>Đã hết hạn</button>`;
      } else {
        statusHtml = `<span class="exam-status exam-status-open">Đang mở</span>`;
        btnHtml = `<button data-exam-id="${e.id}" data-password-required="${e.password_configured ? "true" : "false"}" class="btn-primary exam-card-action exam-enter-button">Vào thi</button>`;
      }

      return `
        <div class="chapter-card">
          <span class="chapter-mode-badge mode-badge-review">Bài thi</span>
          <h3>${e.name}</h3>
          <p class="chapter-meta">Thời gian: <strong>${e.duration_minutes} phút</strong></p>
          <p class="chapter-meta">Bắt đầu: ${start ? formatVietnamDateTime(start) : "Bất kỳ"}</p>
          <p class="chapter-meta">Kết thúc: ${end ? formatVietnamDateTime(end) : "Không giới hạn"}</p>
          <p class="chapter-meta">${e.exercise_count} bài tập</p>
          <p class="chapter-meta exam-card-status">Trạng thái: ${statusHtml}</p>
          ${btnHtml}
        </div>
      `;
    }).join("");

    examList.querySelectorAll(".exam-enter-button").forEach(button => {
      button.addEventListener("click", () => {
        const examId = Number(button.dataset.examId);
        if (button.dataset.passwordRequired === "true") {
          openPasswordModal(examId, button.closest(".chapter-card").querySelector("h3").textContent);
        } else {
          startExam(examId);
        }
      });
    });

  } catch (err) {
    examList.innerHTML = "";
    messageEl.textContent = "Lỗi kết nối máy chủ.";
  }
}

function openPasswordModal(examId, examName) {
  pendingExamId = examId;
  examPasswordExamName.textContent = examName;
  passwordInput.value = "";
  passwordMessage.textContent = "";
  passwordMessage.className = "message";
  passwordModal.classList.remove("hidden");
  passwordInput.focus();
}

function closePasswordModal() {
  passwordModal.classList.add("hidden");
  pendingExamId = null;
  passwordForm.reset();
  passwordMessage.textContent = "";
}

passwordForm.addEventListener("submit", event => {
  event.preventDefault();
  if (pendingExamId === null) return;
  const submitButton = passwordForm.querySelector('button[type="submit"]');
  startExam(pendingExamId, passwordInput.value, submitButton, true);
});

document.getElementById("cancelExamPassword").addEventListener("click", closePasswordModal);
passwordModal.addEventListener("click", event => {
  if (event.target === passwordModal) closePasswordModal();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !passwordModal.classList.contains("hidden")) closePasswordModal();
});

async function startExam(examId, password = "", button = null, passwordRequired = false) {
  if (button) button.disabled = true;
  passwordMessage.textContent = "";
  try {
    const { ok, data } = await fetchJSON(`/api/student/exams/${examId}/start`, {
      method: "POST",
      body: JSON.stringify({ password, device_id: window.getExamDeviceId() }),
    });
    if (ok && data.success) {
      window.rememberActiveExamSession(examId, data.session_id);
    const workspaceUrl = new URL("/student/exam-workspace", window.location.origin);
    workspaceUrl.searchParams.set("session_id", String(data.session_id));
    if (data.device_changed) {
      workspaceUrl.searchParams.set("device_changed", "1");
    } else if (!data.is_resumed) {
      workspaceUrl.searchParams.set("fresh_exam", "1");
    }
    closePasswordModal();
    window.location.href = workspaceUrl;
      return;
    }
    if (data.blocked) {
      if (passwordRequired) closePasswordModal();
      await window.showAppAlert("Bài thi đã bị giáo viên đình chỉ. Điểm bài thi được chốt 0.");
      return;
    }
    if (passwordRequired) {
      passwordMessage.textContent = data.message || "Không thể xác thực vào bài thi.";
      passwordMessage.className = "message error";
      passwordInput.focus();
    } else {
      messageEl.textContent = data.message || "Không thể vào thi.";
      messageEl.className = "message error";
    }
  } catch (error) {
    const text = "Không thể kết nối máy chủ để xác thực vào bài thi.";
    if (passwordRequired) {
      passwordMessage.textContent = text;
      passwordMessage.className = "message error";
    } else {
      messageEl.textContent = text;
      messageEl.className = "message error";
    }
  } finally {
    if (button) button.disabled = false;
  }
}

async function viewResult(examId) {
  const { ok, data } = await fetchJSON(`/api/student/exams/${examId}/history`);
  if (!ok || !data.success) {
    await window.showAppAlert(data.message || "Không tải được kết quả.");
    return;
  }

  const h = data.history;
  const start = formatVietnamDateTime(h.started_at);
  const end = formatVietnamDateTime(h.finished_at);
  
  const html = `
    <div class="exam-result-details">
      <p><strong>Thời gian bắt đầu:</strong> ${start}</p>
      <p><strong>Thời gian nộp bài:</strong> ${end}</p>
      <div class="exam-result-score">
        <p>Điểm số của bạn</p>
        <div>
          ${h.total_score} / ${h.total_max}
        </div>
      </div>
    </div>
  `;

  const modal = document.createElement("div");
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-box exam-result-modal">
      <h3>Kết quả bài thi</h3>
      ${html}
      <div class="modal-actions exam-result-actions">
        <button type="button" class="btn-primary" onclick="this.closest('.modal-overlay').remove()">Đóng</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

loadExams();