/**
 * teacher_chapters.js — trang danh sách chương
 */

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
  return { ok: res.ok, status: res.status, data };
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

function formatDate(iso) {
  if (!iso) return "—";
  return formatVietnamDateTime(iso, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: undefined, minute: undefined, second: undefined,
  });
}

// ============================================================
// LOAD DANH SÁCH CHƯƠNG
// ============================================================
const chapterList = document.getElementById("chapterList");
const messageEl = document.getElementById("message");

async function loadChapters() {
  try {
    const { ok, data } = await fetchJSON("/api/chapters");
    if (!ok || !data.success) {
      chapterList.innerHTML = "";
      showMsg(messageEl, data.message || "Không tải được danh sách.");
      return;
    }

    const chapters = data.chapters || [];
    if (chapters.length === 0) {
      chapterList.innerHTML = '<p class="empty-state">Chưa có chương nào. Nhấn "Tạo chương mới" để bắt đầu.</p>';
      return;
    }

    chapterList.innerHTML = chapters.map(renderChapterCard).join("");
    bindChapterActions();
  } catch (err) {
    chapterList.innerHTML = "";
    showMsg(messageEl, "Lỗi kết nối máy chủ.");
  }
}

function renderChapterCard(c) {
  const visibilityBadge = c.is_hidden
    ? '<span class="chapter-visibility-badge">Đang ẩn với sinh viên</span>'
    : "";
  const previewHtml = c.exercises && c.exercises.length
    ? `<ul>${c.exercises.map((ex, i) =>
        `<li><span class="preview-index">${i + 1}.</span><span>${escapeHtml(ex.title)}</span></li>`
      ).join("")}</ul>`
    : `<div class="empty-preview">Chưa có bài tập nào</div>`;

  return `
    <div class="chapter-card${c.is_hidden ? " chapter-card-hidden" : ""}" data-id="${c.id}">
      <span class="chapter-mode-badge mode-badge-practice">Chương luyện tập</span>
      ${visibilityBadge}
      <h3>${escapeHtml(c.name)}</h3>
      <p class="chapter-meta"> ${c.exercise_count} bài tập</p>
      <p class="chapter-meta">Tạo ngày ${formatDate(c.created_at)}</p>
      <div class="chapter-actions">
        <button class="btn-edit-small edit-btn" data-id="${c.id}">Cấu hình</button>
        <button class="btn-visibility-small visibility-btn" data-id="${c.id}"
                data-hidden="${c.is_hidden ? "true" : "false"}">
          ${c.is_hidden ? "Hiện lại" : "Ẩn tạm thời"}
        </button>
        <button class="btn-delete-small delete-btn" data-id="${c.id}">Xoá</button>
      </div>
      <div class="chapter-hover-preview">
        <h4>Bài tập trong chương</h4>
        ${previewHtml}
      </div>
    </div>
  `;
}

function bindChapterActions() {
  document.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      window.location.href = `/teacher/chapters/${btn.dataset.id}/edit`;
    });
  });

  document.querySelectorAll(".visibility-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      btn.disabled = true;
      try {
        const { ok, data } = await fetchJSON(
          `/api/chapters/${btn.dataset.id}/toggle-visibility`,
          { method: "POST" }
        );
        if (!ok || !data.success) {
          showMsg(messageEl, data.message || "Không thể thay đổi trạng thái chương.");
          return;
        }
        await loadChapters();
        showMsg(messageEl, data.message, "success");
      } catch (error) {
        showMsg(messageEl, "Lỗi kết nối máy chủ.");
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Xoá chương này? Toàn bộ bài tập bên trong sẽ bị xoá.")) return;

      const { ok, data } = await fetchJSON(`/api/chapters/${btn.dataset.id}`, {
        method: "DELETE",
      });
      if (ok && data.success) {
        showMsg(messageEl, "Đã xoá chương.", "success");
        loadChapters();
      } else {
        showMsg(messageEl, data.message || "Không xoá được.");
      }
    });
  });

  // Click vào card (trừ nút) cũng mở cấu hình
  document.querySelectorAll(".chapter-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      window.location.href = `/teacher/chapters/${card.dataset.id}/edit`;
    });
  });
}

// ============================================================
// MODAL TẠO CHƯƠNG
// ============================================================
const modal = document.getElementById("createChapterModal");
const createForm = document.getElementById("createChapterForm");
const createMsg = document.getElementById("createChapterMsg");

document.getElementById("createChapterBtn").addEventListener("click", () => {
  modal.classList.remove("hidden");
  document.getElementById("newChapterName").focus();
});

document.getElementById("cancelCreateBtn").addEventListener("click", () => {
  modal.classList.add("hidden");
  createForm.reset();
  showMsg(createMsg, "");
});
document.getElementById("closeCreateChapterBtn").addEventListener("click", () => {
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

  const name = document.getElementById("newChapterName").value.trim();
  // Xoá dòng lấy mode, thay vào đó:
  const mode = "practice";

  showMsg(createMsg, "Đang tạo...", "");

  try {
    const { ok, data } = await fetchJSON("/api/chapters", {
      method: "POST",
      body: JSON.stringify({ name, mode }),
    });

    if (!ok || !data.success) {
      showMsg(createMsg, data.message || "Không tạo được chương.");
      submitBtn.disabled = false;
      return;
    }

    showMsg(createMsg, "Tạo thành công!", "success");
    setTimeout(() => {
      modal.classList.add("hidden");
      createForm.reset();
      loadChapters();
    }, 500);
  } catch (err) {
    showMsg(createMsg, "Lỗi kết nối.");
    submitBtn.disabled = false;
  }
});

// ============================================================
// KHỞI ĐỘNG
// ============================================================
loadChapters();