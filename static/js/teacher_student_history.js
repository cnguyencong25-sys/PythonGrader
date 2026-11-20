async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function formatDate(value) {
  if (!value) return "Chưa nộp";
  return formatVietnamDateTime(value);
}

function formatDuration(seconds) {
  if (seconds == null) return "Đang làm";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes ? `${minutes} phút ${remainingSeconds} giây` : `${remainingSeconds} giây`;
}

function statusLabel(status) {
  const labels = {
    correct: "Đúng",
    partial: "Đúng một phần",
    wrong: "Chưa đạt",
    pending: "Chưa nộp",
  };
  return labels[status] || status || "Chưa có kết quả";
}

const profile = document.querySelector(".student-profile-summary");
const studentUserId = Number(profile.dataset.studentUserId);
const historyList = document.getElementById("studentExamHistory");
const messageEl = document.getElementById("studentHistoryMessage");
const retakeModal = document.getElementById("allowRetakeModal");
const confirmRetakeButton = document.getElementById("confirmAllowRetake");
let pendingExamId = null;
let pendingExamName = "";

function renderAttempts(attempts) {
  if (!attempts.length) {
    historyList.innerHTML = '<p class="empty-state">Sinh viên chưa có lượt làm bài nào trong các bài thi của bạn.</p>';
    return;
  }

  historyList.innerHTML = attempts.map(attempt => {
    const isLatest = attempt.attempt_number === attempt.attempt_count;
    const submissionMarkup = attempt.submissions.length
      ? attempt.submissions.map(submission => `
          <details class="student-submission">
            <summary>
              <span>${escapeHtml(submission.title)}</span>
              <span class="submission-score">${escapeHtml(statusLabel(submission.status))} · ${escapeHtml(submission.score)} / ${escapeHtml(submission.max_score)}</span>
            </summary>
            <pre class="submission-code"><code>${escapeHtml(submission.code || "Chưa có mã nguồn.")}</code></pre>
          </details>
        `).join("")
      : '<p class="student-no-submissions">Chưa có bài nộp cho lượt này.</p>';

    let retakeControl = "";
    if (isLatest && attempt.retake_allowed) {
      retakeControl = '<span class="retake-status">Đã cấp lượt làm lại</span>';
    } else if (isLatest) {
      retakeControl = `<button type="button" class="btn-primary allow-retake-button"
        data-exam-id="${attempt.exam_id}" data-exam-name="${escapeHtml(attempt.exam_name)}">
        Cho phép làm lại
      </button>`;
    }

    return `
      <article class="student-attempt-card">
        <header class="student-attempt-header">
          <div>
            <div class="student-attempt-eyebrow">LƯỢT ${attempt.attempt_number} / ${attempt.attempt_count}</div>
            <h2>${escapeHtml(attempt.exam_name)}</h2>
          </div>
          <div class="student-attempt-header-actions">
            <span class="attempt-status ${attempt.is_finalized ? "attempt-status-finished" : "attempt-status-active"}">
              ${attempt.is_finalized ? "Đã nộp" : "Đang làm"}
            </span>
            ${retakeControl}
          </div>
        </header>
        <div class="student-attempt-stats">
          <div><span>Điểm</span><strong>${escapeHtml(attempt.score)} / ${escapeHtml(attempt.max_score)}</strong></div>
          <div><span>Câu đúng</span><strong>${attempt.correct_count} / ${attempt.question_count}</strong></div>
          <div><span>Thời gian làm</span><strong>${formatDuration(attempt.time_taken_seconds)}</strong></div>
          <div><span>${attempt.is_finalized ? "Thời gian nộp" : "Bắt đầu lúc"}</span><strong>${formatDate(attempt.finished_at || attempt.started_at)}</strong></div>
        </div>
        <section class="student-attempt-submissions">
          <h3>Mã nguồn đã nộp</h3>
          ${submissionMarkup}
        </section>
      </article>
    `;
  }).join("");

  historyList.querySelectorAll(".allow-retake-button").forEach(button => {
    button.addEventListener("click", () => {
      pendingExamId = Number(button.dataset.examId);
      pendingExamName = button.dataset.examName;
      document.getElementById("allowRetakeTitle").textContent = `Cho phép làm lại “${pendingExamName}”?`;
      retakeModal.classList.remove("hidden");
    });
  });
}

function closeRetakeModal() {
  retakeModal.classList.add("hidden");
  pendingExamId = null;
  pendingExamName = "";
}

async function loadHistory() {
  try {
    const { ok, data } = await fetchJSON(`/api/teacher/students/${studentUserId}/exam-history`);
    if (!ok || !data.success) {
      historyList.innerHTML = "";
      messageEl.textContent = data.message || "Không tải được lịch sử bài thi.";
      messageEl.className = "message error";
      return;
    }
    renderAttempts(data.attempts || []);
  } catch (error) {
    historyList.innerHTML = "";
    messageEl.textContent = "Không thể kết nối máy chủ để tải lịch sử.";
    messageEl.className = "message error";
  }
}

document.getElementById("cancelAllowRetake").addEventListener("click", closeRetakeModal);
retakeModal.addEventListener("click", event => {
  if (event.target === retakeModal) closeRetakeModal();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !retakeModal.classList.contains("hidden")) closeRetakeModal();
});

confirmRetakeButton.addEventListener("click", async () => {
  if (pendingExamId === null) return;
  confirmRetakeButton.disabled = true;
  try {
    const { ok, data } = await fetchJSON(
      `/api/teacher/students/${studentUserId}/exams/${pendingExamId}/allow-retake`,
      { method: "POST" }
    );
    if (!ok || !data.success) {
      messageEl.textContent = data.message || "Không thể cấp lượt làm lại.";
      messageEl.className = "message error";
      return;
    }
    closeRetakeModal();
    messageEl.textContent = data.message || "Đã cấp lượt làm lại.";
    messageEl.className = "message success";
    await loadHistory();
  } catch (error) {
    messageEl.textContent = "Không thể kết nối máy chủ để cấp lượt làm lại.";
    messageEl.className = "message error";
  } finally {
    confirmRetakeButton.disabled = false;
  }
});

loadHistory();
