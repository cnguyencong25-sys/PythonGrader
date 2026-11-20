function showMsg(el, text, type = "error") {
  if (!el) return;
  el.textContent = text;
  el.className = "message " + type;
}

async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return formatVietnamDateTime(iso, {
    hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric",
  });
}

const examList = document.getElementById("examList");
const messageEl = document.getElementById("message");

async function loadExams() {
  try {
    const { ok, data } = await fetchJSON("/api/exams");
    if (!ok || !data.success) {
      examList.innerHTML = "";
      showMsg(messageEl, data.message || "Không tải được danh sách.");
      return;
    }

    const exams = data.exams || [];
    if (exams.length === 0) {
      examList.innerHTML = '<p class="empty-state">Chưa có bài kiểm tra nào.</p>';
      return;
    }

    examList.innerHTML = exams.map(c => `
      <div class="chapter-card" data-id="${c.id}">
        <span class="chapter-mode-badge mode-badge-review">Bài kiểm tra</span>
        <h3>${escapeHtml(c.name)}</h3>
        <p class="chapter-meta">Thời gian làm: <strong>${c.duration_minutes} phút</strong></p>
        <p class="chapter-meta">Bắt đầu: ${formatDateTime(c.start_time)}</p>
        <p class="chapter-meta">Kết thúc: ${formatDateTime(c.end_time)}</p>
        <p class="chapter-meta">${c.exercise_count} bài tập</p>
        <p class="chapter-meta">Tối đa ${c.max_attempts} lượt</p>
        <p class="chapter-meta">Link thi: <a href="/exam/${escapeHtml(c.access_code)}" target="_blank" rel="noopener">Mở link sinh viên</a></p>
        <div class="chapter-actions">
          <button class="btn-edit-small edit-btn" data-id="${c.id}">Cấu hình</button>
          <button class="btn-delete-small delete-btn" data-id="${c.id}">Xoá</button>
        </div>
        <div class="chapter-hover-preview">
          <h4>Bài tập trong bài kiểm tra</h4>
          ${c.exercises && c.exercises.length 
            ? `<ul>${c.exercises.map((ex, i) => `<li><span class="preview-index">${i + 1}.</span><span>${escapeHtml(ex.title)}</span></li>`).join("")}</ul>`
            : `<div class="empty-preview">Chưa có bài tập nào</div>`}
        </div>
      </div>
    `).join("");

    document.querySelectorAll(".edit-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        window.location.href = `/teacher/exams/${btn.dataset.id}/edit`;
      });
    });

    document.querySelectorAll(".delete-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Xoá bài kiểm tra này? Toàn bộ bài tập bên trong sẽ bị xoá.")) return;
        const { ok, data } = await fetchJSON(`/api/exams/${btn.dataset.id}`, { method: "DELETE" });
        if (ok && data.success) {
          showMsg(messageEl, "Đã xoá.", "success");
          loadExams();
        } else {
          showMsg(messageEl, data.message || "Không xoá được.");
        }
      });
    });

    document.querySelectorAll(".chapter-card").forEach(card => {
      card.addEventListener("click", (e) => {
        if (e.target.closest("button, a")) return;
        window.location.href = `/teacher/exams/${card.dataset.id}/edit`;
      });
    });
  } catch (err) {
    examList.innerHTML = "";
    showMsg(messageEl, "Lỗi kết nối máy chủ.");
  }
}

const modal = document.getElementById("createExamModal");
const createForm = document.getElementById("createExamForm");
const createMsg = document.getElementById("createExamMsg");

document.getElementById("createExamBtn").addEventListener("click", () => {
  modal.classList.remove("hidden");
  document.getElementById("newExamName").focus();
});

document.getElementById("cancelCreateBtn").addEventListener("click", () => {
  modal.classList.add("hidden");
  createForm.reset();
  showMsg(createMsg, "");
});
document.getElementById("closeCreateExamBtn").addEventListener("click", () => {
  document.getElementById("cancelCreateBtn").click();
});
modal.addEventListener("click", event => {
  if (event.target === modal) document.getElementById("cancelCreateBtn").click();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !modal.classList.contains("hidden")) {
    document.getElementById("cancelCreateBtn").click();
  }
});

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = createForm.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  showMsg(createMsg, "Đang tạo...", "");

  const name = document.getElementById("newExamName").value.trim();
  const start_time = document.getElementById("newExamStart").value;
  const end_time = document.getElementById("newExamEnd").value;
  const duration_minutes = document.getElementById("newExamDuration").value;
  const exam_password = document.getElementById("newExamPassword").value;
  const max_attempts = document.getElementById("newExamMaxAttempts").value;

  try {
    const { ok, data } = await fetchJSON("/api/exams", {
      method: "POST",
      body: JSON.stringify({ name, start_time, end_time, duration_minutes, exam_password, max_attempts }),
    });

    if (!ok || !data.success) {
      showMsg(createMsg, data.message || "Không tạo được.");
      submitBtn.disabled = false;
      return;
    }

    showMsg(createMsg, "Tạo thành công!", "success");
    setTimeout(() => {
      modal.classList.add("hidden");
      createForm.reset();
      loadExams();
    }, 500);
  } catch (err) {
    showMsg(createMsg, "Lỗi kết nối.");
    submitBtn.disabled = false;
  }
});

loadExams();