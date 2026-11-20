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

const chapterList = document.getElementById("chapterList");
const messageEl = document.getElementById("message");
const freePracticeModal = document.getElementById("freePracticeModal");
const practiceChapterSelect = document.getElementById("practiceChapterSelect");
const simulationChapterList = document.getElementById("simulationChapterList");
const simulationChapterOptions = document.getElementById("simulationChapterOptions");
const selectAllChapters = document.getElementById("selectAllChapters");
const practiceQuestionCount = document.getElementById("practiceQuestionCount");
const simulationQuestionCount = document.getElementById("simulationQuestionCount");
const simulationDuration = document.getElementById("simulationDuration");
const confirmFreePracticeBtn = document.getElementById("confirmFreePracticeBtn");
const freePracticeValidation = document.getElementById("freePracticeValidation");
let availableChapters = [];

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function selectedPracticeMode() {
  return document.querySelector('input[name="freePracticeMode"]:checked').value;
}

function updateModeCardState() {
  document.querySelectorAll(".free-practice-mode-card").forEach(card => {
    card.classList.toggle(
      "is-selected",
      card.querySelector('input[name="freePracticeMode"]').checked
    );
  });
}

function selectedSimulationChapters() {
  const selectedIds = new Set(
    [...simulationChapterOptions.querySelectorAll('input[data-chapter-id]:checked')]
      .map(input => Number(input.value))
  );
  return availableChapters.filter(chapter => selectedIds.has(chapter.id));
}

function validateFreePractice() {
  const mode = selectedPracticeMode();
  const chapters = mode === "practice"
    ? availableChapters.filter(chapter => chapter.id === Number(practiceChapterSelect.value))
    : selectedSimulationChapters();
  const questionCountInput = mode === "practice"
    ? practiceQuestionCount
    : simulationQuestionCount;
  const questionCount = Number(questionCountInput.value);
  const totalAvailable = chapters.reduce(
    (total, chapter) => total + chapter.total_exercises,
    0
  );

  let error = "";
  if (!chapters.length) {
    error = "Vui lòng chọn chương.";
  } else if (!Number.isInteger(questionCount) || questionCount < 1) {
    error = "Số câu hỏi phải là số nguyên lớn hơn 0.";
  } else if (questionCount > totalAvailable) {
    error = `Phạm vi đã chọn có tối đa ${totalAvailable} câu hỏi.`;
  } else if (mode === "simulation") {
    const duration = Number(simulationDuration.value);
    if (!Number.isFinite(duration) || duration <= 0) {
      error = "Thời gian làm bài phải lớn hơn 0 phút.";
    }
  }

  questionCountInput.max = totalAvailable || 1;
  freePracticeValidation.textContent = error || (
    `Đã chọn ${chapters.length} chương · ${totalAvailable} câu khả dụng`
  );
  freePracticeValidation.classList.toggle("is-error", Boolean(error));
  confirmFreePracticeBtn.disabled = Boolean(error);
}

function renderFreePracticeChapters() {
  practiceChapterSelect.innerHTML = '<option value="">-- Chọn chương --</option>';
  for (const chapter of availableChapters) {
    const option = document.createElement("option");
    option.value = chapter.id;
    option.textContent = `${chapter.name} (${chapter.total_exercises} câu)`;
    practiceChapterSelect.appendChild(option);
  }

  simulationChapterOptions.innerHTML = availableChapters.map(chapter => `
    <label class="free-practice-chapter-option">
      <input type="checkbox" data-chapter-id value="${chapter.id}">
      <span>${escapeHtml(chapter.name)}</span>
      <small>${chapter.total_exercises} câu</small>
    </label>
  `).join("");
  selectAllChapters.checked = false;
  selectAllChapters.indeterminate = false;
  validateFreePractice();
}

function updateSelectAllState() {
  const checkboxes = [...simulationChapterOptions.querySelectorAll('input[data-chapter-id]')];
  const checkedCount = checkboxes.filter(input => input.checked).length;
  selectAllChapters.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
  selectAllChapters.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
}

document.getElementById("openFreePracticeBtn").addEventListener("click", () => {
  freePracticeModal.classList.remove("hidden");
  validateFreePractice();
});
document.getElementById("cancelFreePracticeBtn").addEventListener("click", () => {
  freePracticeModal.classList.add("hidden");
});
freePracticeModal.addEventListener("click", event => {
  if (event.target === freePracticeModal) freePracticeModal.classList.add("hidden");
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") freePracticeModal.classList.add("hidden");
});
document.querySelectorAll('input[name="freePracticeMode"]').forEach(input => {
  input.addEventListener("change", () => {
    updateModeCardState();
    const isPractice = selectedPracticeMode() === "practice";
    document.getElementById("practiceConfig").hidden = !isPractice;
    document.getElementById("simulationConfig").hidden = isPractice;
    validateFreePractice();
  });
});
updateModeCardState();
practiceChapterSelect.addEventListener("change", validateFreePractice);
practiceQuestionCount.addEventListener("input", validateFreePractice);
simulationQuestionCount.addEventListener("input", validateFreePractice);
simulationDuration.addEventListener("input", validateFreePractice);
simulationChapterList.addEventListener("change", () => {
  updateSelectAllState();
  validateFreePractice();
});
selectAllChapters.addEventListener("change", () => {
  simulationChapterOptions.querySelectorAll('input[data-chapter-id]').forEach(input => {
    input.checked = selectAllChapters.checked;
  });
  updateSelectAllState();
  validateFreePractice();
});
confirmFreePracticeBtn.addEventListener("click", async () => {
  if (confirmFreePracticeBtn.disabled) return;
  confirmFreePracticeBtn.disabled = true;
  confirmFreePracticeBtn.textContent = "Đang tạo phiên...";
  freePracticeValidation.classList.remove("is-error");

  const mode = selectedPracticeMode();
  const chapters = mode === "practice"
    ? availableChapters.filter(chapter => chapter.id === Number(practiceChapterSelect.value))
    : selectedSimulationChapters();
  const payload = {
    mode,
    chapter_ids: chapters.map(chapter => chapter.id),
    question_count: Number(
      mode === "practice" ? practiceQuestionCount.value : simulationQuestionCount.value
    ),
  };
  if (mode === "simulation") payload.duration_minutes = Number(simulationDuration.value);

  try {
    const { ok, data } = await fetchJSON("/api/student/free-sessions/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!ok || !data.success) {
      freePracticeValidation.textContent = data.message || "Không thể tạo phiên luyện tập.";
      freePracticeValidation.classList.add("is-error");
      validateFreePractice();
      return;
    }
    window.location.href = `/student/free-practice-workspacesession_id=${data.session_id}`;
  } catch (error) {
    freePracticeValidation.textContent = "Lỗi kết nối máy chủ.";
    freePracticeValidation.classList.add("is-error");
    validateFreePractice();
  } finally {
    confirmFreePracticeBtn.textContent = "Xác nhận";
  }
});

async function loadChapters() {
  try {
    const { ok, data } = await fetchJSON("/api/student/chapters");
    if (!ok || !data.success) {
      chapterList.innerHTML = "";
      showMsg(messageEl, data.message || "Không tải được danh sách.");
      return;
    }

    const chapters = Array.isArray(data.chapters) ? data.chapters : [];
    availableChapters = chapters
      .filter(chapter => chapter && typeof chapter === "object")
      .map(chapter => {
        const totalExercises = Math.max(
          0,
          Math.floor(Number(chapter.total_exercises) || 0)
        );
        return {
          ...chapter,
          id: Number(chapter.id) || 0,
          name: typeof chapter.name === "string" ? chapter.name : "",
          teacher_name: typeof chapter.teacher_name === "string"
            ? chapter.teacher_name
            : "",
          total_exercises: totalExercises,
          completed_exercises: Math.min(
            totalExercises,
            Math.max(0, Math.floor(Number(chapter.completed_exercises) || 0))
          ),
        };
      });
    renderFreePracticeChapters();
    if (availableChapters.length === 0) {
      chapterList.innerHTML = '<p class="empty-state">Hiện chưa có chương luyện tập nào.</p>';
      return;
    }

    chapterList.innerHTML = availableChapters.map(c => {
      const isDone = c.total_exercises > 0 && c.completed_exercises === c.total_exercises;

      return `
        <div class="chapter-card" onclick="window.location.href='/student/chapters/${c.id}'">
          <span class="chapter-mode-badge mode-badge-practice">Chương luyện tập</span>
          <h3>${escapeHtml(c.name)}</h3>
          <p class="chapter-meta">GV: ${escapeHtml(c.teacher_name)}</p>
          <p class="chapter-meta">Tiến độ: <strong>${c.completed_exercises} / ${c.total_exercises}</strong> bài đúng</p>
          ${isDone ? '<p class="chapter-complete-badge">Đã hoàn thành</p>' : ''}
        </div>
      `;
    }).join("");

  } catch (err) {
    chapterList.innerHTML = "";
    showMsg(messageEl, "Lỗi kết nối máy chủ.");
  }
}

loadChapters();