function showMsg(el, text, type = "error") {
  if (!el) return;
  el.textContent = text;
  el.className = "message " + type;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const messageEl = document.getElementById("message");
const infoForm = document.getElementById("examInfoForm");
const examId = infoForm.dataset.examId;
const chapterRulesEl = document.getElementById("chapterRules");
const chapterRuleMessage = document.getElementById("chapterRuleMessage");
let availableChapters = [];

function addChapterRule(rule = {}) {
  const row = document.createElement("div");
  row.className = "row-2 chapter-rule-row";
  row.innerHTML = `<div><label>Chương</label><select class="rule-chapter"></select></div>
    <div><label>Số câu ngẫu nhiên</label><input class="rule-count" type="number" min="1" value="${rule.question_count || 1}">
    <button type="button" class="btn-delete-small remove-rule">Xóa</button></div>`;
  const select = row.querySelector(".rule-chapter");
  select.innerHTML = availableChapters.map(chapter =>
    `<option value="${chapter.id}">${escapeHtml(chapter.name)} (${chapter.exercise_count} câu)</option>`
  ).join("");
  if (rule.chapter_id) select.value = String(rule.chapter_id);
  row.querySelector(".remove-rule").addEventListener("click", () => row.remove());
  chapterRulesEl.appendChild(row);
}

async function loadChapterRules() {
  const [chapterResponse, rulesResponse] = await Promise.all([
    fetchJSON("/api/chapters"), fetchJSON(`/api/exams/${examId}/chapter-rules`)
  ]);
  if (!chapterResponse.ok || !chapterResponse.data.success) {
    showMsg(chapterRuleMessage, chapterResponse.data.message || "Không tải được danh sách chương.");
    return;
  }
  if (!rulesResponse.ok || !rulesResponse.data.success) {
    showMsg(chapterRuleMessage, rulesResponse.data.message || "Không tải được cấu hình chương.");
    return;
  }
  availableChapters = chapterResponse.data.chapters.filter(chapter => chapter.exercise_count > 0);
  (rulesResponse.data.rules || []).forEach(addChapterRule);
}

document.getElementById("addChapterRule").addEventListener("click", () => addChapterRule());
document.getElementById("saveChapterRules").addEventListener("click", async () => {
  const rules = Array.from(chapterRulesEl.querySelectorAll(".chapter-rule-row")).map(row => ({
    chapter_id: Number(row.querySelector(".rule-chapter").value),
    question_count: Number(row.querySelector(".rule-count").value),
  }));
  const { ok, data } = await fetchJSON(`/api/exams/${examId}/chapter-rules`, {
    method: "PUT", body: JSON.stringify({ rules }),
  });
  showMsg(chapterRuleMessage, data.message || (ok ? "Đã lưu cấu hình." : "Không lưu được."), ok ? "success" : "error");
});

infoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = infoForm.querySelector('button[type="submit"]');
  btn.disabled = true;
  showMsg(messageEl, "Đang lưu...", "");

  const name = document.getElementById("examName").value.trim();
  const start_time = document.getElementById("examStart").value;
  const end_time = document.getElementById("examEnd").value;
  const duration_minutes = document.getElementById("examDuration").value;
  const max_attempts = document.getElementById("examMaxAttempts").value;
  const exam_password = document.getElementById("examPassword").value;
  const clear_exam_password = document.getElementById("clearExamPassword").checked;

  try {
    const { ok, data } = await fetchJSON(`/api/exams/${examId}`, {
      method: "PUT",
      body: JSON.stringify({ name, start_time, end_time, duration_minutes, max_attempts, exam_password, clear_exam_password }),
    });
    if (!ok || !data.success) {
      showMsg(messageEl, data.message || "Không lưu được.");
      btn.disabled = false;
      return;
    }
    showMsg(messageEl, "Đã lưu thay đổi.", "success");
    btn.disabled = false;
  } catch (err) {
    showMsg(messageEl, "Lỗi kết nối.");
    btn.disabled = false;
  }
});
document.querySelectorAll(".btn-toggle-small").forEach(btn => {
  btn.addEventListener("click", async () => {
    const res = await fetchJSON(`/api/chapters/exercises/${btn.dataset.id}/toggle-publish`, { method: "POST" });
    if (res.ok) location.reload(); // Reload lại trang để cập nhật giao diện
  });
});
loadChapterRules();
document.querySelectorAll(".btn-toggle-small").forEach(btn => {
  btn.addEventListener("click", async () => {
    const res = await fetchJSON(`/api/exams/exercises/${btn.dataset.id}/toggle-publish`, { method: "POST" });
    if (res.ok) location.reload();
  });
});
// Xoá bài tập
document.querySelectorAll(".btn-delete-small").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Xoá bài tập này?")) return;

    const { ok, data } = await fetchJSON(`/api/exams/exercises/${btn.dataset.id}`, {
      method: "DELETE",
    });

    if (ok && data.success) {
      btn.closest(".exercise-item").remove();
      const count = document.querySelectorAll(".exercise-item").length;
      const badge = document.getElementById("exerciseCountBadge");
      if (badge) badge.textContent = count;
      showMsg(messageEl, "Đã xoá bài tập.", "success");
    } else {
      showMsg(messageEl, data.message || "Không xoá được.");
    }
  });
});