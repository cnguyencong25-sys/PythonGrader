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
    tbody.innerHTML = scores.map((score, index) => `
      <tr>
        <td>${index + 1}</td><td>${escapeHtml(score.student_id)}</td>
        <td>${escapeHtml(score.full_name)}</td><td>${escapeHtml(score.class_name)}</td>
        <td><strong>${score.score} / ${score.max_score}</strong></td>
        <td>${escapeHtml(score.time_taken)}</td><td>${score.violation_count || 0}</td>
        <td><button class="btn-secondary view-submission" data-index="${index}">Xem code</button></td>
      </tr>
      <tr class="submission-detail" id="submission-${index}" hidden><td colspan="8"></td></tr>
    `).join("");
    tbody.querySelectorAll(".view-submission").forEach(button => {
      button.addEventListener("click", () => {
        const detail = document.getElementById(`submission-${button.dataset.index}`);
        const score = scores[Number(button.dataset.index)];
        const target = detail.querySelector("td");
        if (!detail.hidden) {
          detail.hidden = true;
          return;
        }
        target.innerHTML = (score.submissions || []).map(submission => `
          <section><strong>${escapeHtml(submission.question_key)} — ${escapeHtml(submission.status)} (${submission.score}/${submission.max_score})</strong>
          <pre class="submission-code">${escapeHtml(submission.code)}</pre></section>
        `).join("") || "Không có bài nộp.";
        detail.hidden = false;
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
