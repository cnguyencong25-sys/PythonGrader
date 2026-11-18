async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function scoreStatusLabel(status) {
  return {
    correct: "Đúng",
    partial: "Đúng một phần",
    wrong: "Sai",
  }[status] || "Đã nộp";
}

function renderSubmissionReview(target, submissions, rowIndex) {
  const completedSubmissions = submissions.filter(submission => submission.status !== "pending");
  if (!completedSubmissions.length) {
    target.innerHTML = '<div class="submission-review-empty">Sinh viên chưa có câu trả lời đã nộp.</div>';
    return;
  }

  target.innerHTML = `
    <div class="score-submission-review">
      <div class="submission-review-heading">
        <div>
          <strong>Mã nguồn bài làm</strong>
          <span>${completedSubmissions.length} câu đã nộp</span>
        </div>
        <label for="submission-question-${rowIndex}">Chọn câu</label>
      </div>
      <select id="submission-question-${rowIndex}" class="submission-question-select">
        ${completedSubmissions.map((submission, index) => `
          <option value="${index}">
            ${escapeHtml(submission.title || submission.question_key)} — ${escapeHtml(scoreStatusLabel(submission.status))}
          </option>
        `).join("")}
      </select>
      <div class="submission-review-meta">
        <strong class="submission-review-status"></strong>
        <span class="submission-review-score"></span>
      </div>
      <pre class="submission-code"></pre>
    </div>
  `;

  const selector = target.querySelector(".submission-question-select");
  const statusEl = target.querySelector(".submission-review-status");
  const scoreEl = target.querySelector(".submission-review-score");
  const codeEl = target.querySelector(".submission-code");

  function showSelectedSubmission() {
    const submission = completedSubmissions[Number(selector.value)];
    const status = submission.status;
    const statusClass = ["correct", "partial", "wrong"].includes(status)
      ? status
      : "submitted";
    statusEl.className = `submission-review-status status-${statusClass}`;
    statusEl.textContent = scoreStatusLabel(status);
    scoreEl.textContent = `${submission.score} / ${submission.max_score} điểm`;
    codeEl.textContent = submission.code || "Bài nộp này không có nội dung mã nguồn.";
  }

  selector.addEventListener("change", showSelectedSubmission);
  showSelectedSubmission();
}

const tbody = document.getElementById("scoreTableBody");
const messageEl = document.getElementById("message");
const examId = window.location.pathname.split("/")[3];
const filters = ["filterDate", "filterClass", "filterStudentId", "filterName"];

async function loadScores() {
  const params = new URLSearchParams();
  params.set("date", document.getElementById("filterDate").value);
  params.set("class_name", document.getElementById("filterClass").value.trim());
  params.set("student_id", document.getElementById("filterStudentId").value.trim());
  params.set("full_name", document.getElementById("filterName").value.trim());
  try {
    const { ok, data } = await fetchJSON(`/api/exams/${examId}/scores?${params}`);
    if (!ok || !data.success) {
      tbody.innerHTML = `<tr><td colspan="8">${escapeHtml(data.message || "Lỗi tải dữ liệu.")}</td></tr>`;
      return;
    }
    const scores = data.scores || [];
    if (!scores.length) {
      tbody.innerHTML = '<tr><td class="empty-table-cell" colspan="8">Chưa có kết quả phù hợp.</td></tr>';
      return;
    }
    tbody.innerHTML = scores.map((score, index) => {
      const hasSubmissions = (score.submissions || []).length > 0;
      return `
        <tr>
          <td>${index + 1}</td><td>${escapeHtml(score.student_id)}</td>
          <td>${escapeHtml(score.full_name)}</td><td>${escapeHtml(score.class_name)}</td>
          <td><strong>${score.score} / ${score.max_score}</strong></td>
          <td>${escapeHtml(score.time_taken)}</td><td>${score.violation_count || 0}</td>
          <td><button class="btn-secondary view-submission" data-index="${index}"
                      aria-expanded="false" ${hasSubmissions ? "" : "disabled"}>${hasSubmissions ? "Xem code" : "Chưa có code"}</button></td>
        </tr>
        <tr class="submission-detail" id="submission-${index}" hidden><td colspan="8"></td></tr>
      `;
    }).join("");
    tbody.querySelectorAll(".view-submission").forEach(button => {
      button.addEventListener("click", () => {
        const detail = document.getElementById(`submission-${button.dataset.index}`);
        const score = scores[Number(button.dataset.index)];
        const target = detail.querySelector("td");
        if (!detail.hidden) {
          detail.hidden = true;
          button.textContent = "Xem code";
          button.setAttribute("aria-expanded", "false");
          return;
        }
        renderSubmissionReview(target, score.submissions || [], Number(button.dataset.index));
        detail.hidden = false;
        button.textContent = "Ẩn code";
        button.setAttribute("aria-expanded", "true");
      });
    });
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="8">Lỗi kết nối máy chủ.</td></tr>';
  }
}

let filterTimeout;
filters.forEach(id => document.getElementById(id).addEventListener("input", () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(loadScores, 250);
}));

document.getElementById("exportSheetBtn").addEventListener("click", async () => {
  const button = document.getElementById("exportSheetBtn");
  const reportTab = window.open("about:blank", "_blank");
  button.disabled = true;
  button.textContent = "Đang tạo báo cáo...";
  messageEl.textContent = "";
  messageEl.className = "message score-export-message";
  const params = new URLSearchParams();
  params.set("date", document.getElementById("filterDate").value);
  params.set("class_name", document.getElementById("filterClass").value.trim());
  params.set("student_id", document.getElementById("filterStudentId").value.trim());
  params.set("full_name", document.getElementById("filterName").value.trim());
  try {
    const { ok, data } = await fetchJSON(`/api/exams/${examId}/export-sheet?${params}`, { method: "POST" });
    if (!ok || !data.success || !data.url) {
      if (reportTab) reportTab.close();
      messageEl.textContent = data.message || "Không thể tạo báo cáo Google Sheets.";
      messageEl.className = "message error score-export-message";
      return;
    }

    if (reportTab) reportTab.location = data.url;
    messageEl.textContent = "Đã tạo báo cáo. ";
    messageEl.className = "message success score-export-message";
    const link = document.createElement("a");
    link.href = data.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Mở Google Sheets";
    messageEl.appendChild(link);
  } catch (error) {
    if (reportTab) reportTab.close();
    messageEl.textContent = "Không kết nối được dịch vụ xuất Google Sheets.";
    messageEl.className = "message error score-export-message";
  } finally {
    button.disabled = false;
    button.innerHTML = '<span aria-hidden="true">📗</span> Xuất báo cáo xếp hạng';
  }
});

loadScores();
