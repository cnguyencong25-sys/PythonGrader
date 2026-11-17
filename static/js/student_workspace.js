async function fetchJSON(url, opts = {}) {
  opts.credentials = "include";
  opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

const wsLayout = document.querySelector(".workspace-layout");
const chapterId = wsLayout.dataset.chapterId;
const sessionId = wsLayout.dataset.sessionId; // Lấy session ID

let exercises = [];
let currentExIndex = -1;
let editor = null;
let submissionsData = {};
let autoSaveTimeout = null;

// Khởi tạo CodeMirror
function initEditor() {
  editor = createStudentCodeEditor(document.getElementById("codeEditor"), {
    mode: "python",
    theme: "dracula",
    lineNumbers: false,
    autoCloseBrackets: true,
    indentUnit: 4,
    tabSize: 4,
  });
  editor.setSize("100%", "100%");

  // Bắt sự kiện gõ phím -> Tự động lưu nháp (Debounce 1.5s)
  editor.on("change", () => {
    if (currentExIndex === -1) return;
    clearTimeout(autoSaveTimeout);
    autoSaveTimeout = setTimeout(() => autoSaveDraft(), 1500);
  });
}

// Lưu nháp ngầm (không chấm điểm)
async function autoSaveDraft() {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const code = editor.getValue();
  
  await fetchJSON(`/api/student/sessions/${sessionId}/save-draft`, {
    method: "POST",
    body: JSON.stringify({ exercise_id: ex.id, code })
  });
  console.log("Auto-saved draft for ex", ex.id);
}

// Load dữ liệu phiên làm bài
async function loadWorkspace() {
  const { ok, data } = await fetchJSON(`/api/student/sessions/${sessionId}`);
  if (!ok || !data.success) {
    alert(data.message || "Lỗi tải dữ liệu.");
    return;
  }

  exercises = data.chapter.exercises;
  submissionsData = data.submissions || {};

  renderExerciseGrid();

  if (exercises.length > 0) {
    selectExercise(0);
  }
}

function renderExerciseGrid() {
  const grid = document.getElementById("exerciseGrid");
  grid.innerHTML = exercises.map((ex, i) => {
    let statusClass = "";
    if (submissionsData[ex.id] && submissionsData[ex.id].status !== "pending") {
      statusClass = submissionsData[ex.id].status;
    }
    return `<button class="ex-btn ${statusClass}" data-index="${i}">${i + 1}</button>`;
  }).join("");

  document.querySelectorAll(".ex-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      // Trước khi chuyển câu, lưu nháp ngay lập tức (không chờ debounce)
      autoSaveDraft().then(() => selectExercise(parseInt(btn.dataset.index)));
    });
  });
}

function selectExercise(index) {
  currentExIndex = index;
  const ex = exercises[index];

  document.querySelectorAll(".ex-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelector(`.ex-btn[data-index="${index}"]`).classList.add("active");

  document.getElementById("problemBody").style.display = "flex";
  document.getElementById("problemTitle").textContent = `Bài ${index + 1}: ${ex.title}`;
  document.getElementById("problemDescription").textContent = ex.description;
  document.getElementById("problemOutputFormat").textContent = ex.output_format || "(Không có)";
  document.getElementById("problemConstraints").textContent = ex.constraints || "(Không có)";
  renderStudentSampleCases(ex);

  // Load code cũ (từ lúc lưu nháp hoặc nộp bài)
  if (submissionsData[ex.id] && submissionsData[ex.id].code) {
    editor.setValue(submissionsData[ex.id].code);
    if (submissionsData[ex.id].status !== "pending") {
      updateSubmitResultUI(submissionsData[ex.id]);
    } else {
      document.getElementById("submitResult").textContent = "";
    }
  } else {
    editor.setValue("def solve():\n    # Viết code của bạn ở đây\n    pass\n");
    document.getElementById("submitResult").textContent = "";
  }
}

function updateSubmitResultUI(result) {
  const resEl = document.getElementById("submitResult");
  if (result.status === "correct") {
    resEl.textContent = "✅ Đúng hoàn toàn!";
    resEl.className = "submit-result correct";
  } else if (result.status === "partial") {
    resEl.textContent = "⚠️ Đúng một phần.";
    resEl.className = "submit-result partial";
  } else {
    resEl.textContent = "❌ Sai.";
    resEl.className = "submit-result wrong";
  }
}

document.getElementById("submitBtn").addEventListener("click", async () => {
  if (currentExIndex === -1) return;
  const ex = exercises[currentExIndex];
  const code = editor.getValue();
  const btn = document.getElementById("submitBtn");
  
  btn.disabled = true;
  btn.textContent = "⏳ Đang chấm...";

  try {
    const { ok, data } = await fetchJSON(`/api/student/sessions/${sessionId}/submit`, {
      method: "POST",
      body: JSON.stringify({ exercise_id: ex.id, code })
    });

    if (ok && data.success) {
      const result = data.result;
      submissionsData[ex.id] = result;
      
      const exBtn = document.querySelector(`.ex-btn[data-index="${currentExIndex}"]`);
      exBtn.classList.remove("correct", "partial", "wrong");
      if(result.status !== "pending") exBtn.classList.add(result.status);

      updateSubmitResultUI(result);
    }
  } catch (err) {
    alert("Lỗi kết nối.");
  } finally {
    btn.disabled = false;
    btn.textContent = "🚀 Nộp bài";
  }
});

// ==========================================
// XỬ LÝ KẾT THÚC
// ==========================================
document.getElementById("finishBtn").addEventListener("click", async () => {
  await autoSaveDraft(); // Lưu nốt bài đang gõ

  const listEl = document.getElementById("summaryList");
  
  listEl.innerHTML = exercises.map((ex, i) => {
    const isDone = submissionsData[ex.id] && submissionsData[ex.id].status !== "pending";
    const statusText = isDone ? `Đã nộp (${submissionsData[ex.id].score} đ)` : "Chưa nộp";
    const className = isDone ? "done" : "undone";
    const icon = isDone ? "✅" : "❌";
    
    return `
      <div class="summary-item ${className}">
        <span>${icon} Bài ${i + 1}: ${ex.title}</span>
        <strong>${statusText}</strong>
      </div>
    `;
  }).join("");

  document.getElementById("summaryStep").style.display = "block";
  document.getElementById("scoreStep").style.display = "none";
  document.getElementById("finishModal").classList.remove("hidden");
});

document.getElementById("confirmFinishBtn").addEventListener("click", async () => {
  let totalScore = 0, totalMax = 0;
  
  exercises.forEach(ex => {
    if (submissionsData[ex.id]) {
      totalScore += submissionsData[ex.id].score;
      totalMax += submissionsData[ex.id].max_score;
    }
  });

  // Gọi API đánh dấu kết thúc
  await fetchJSON(`/api/student/sessions/${sessionId}/finish`, { method: "POST" });

  document.getElementById("finalScore").textContent = totalScore;
  document.getElementById("finalMaxScore").textContent = totalMax;
  
  document.getElementById("summaryStep").style.display = "none";
  document.getElementById("scoreStep").style.display = "block";
});

document.getElementById("closeFinishBtn").addEventListener("click", () => {
  window.location.href = "/student/chapters";
});

// Khởi động
initEditor();
loadWorkspace();