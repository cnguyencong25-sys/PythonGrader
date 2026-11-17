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

async function loadChapters() {
  try {
    const { ok, data } = await fetchJSON("/api/student/chapters");
    if (!ok || !data.success) {
      chapterList.innerHTML = "";
      showMsg(messageEl, data.message || "Không tải được danh sách.");
      return;
    }

    const chapters = data.chapters || [];
    if (chapters.length === 0) {
      chapterList.innerHTML = '<p class="empty-state">📭 Hiện chưa có chương luyện tập nào.</p>';
      return;
    }

    chapterList.innerHTML = chapters.map(c => {
      const isDone = c.total_exercises > 0 && c.completed_exercises === c.total_exercises;

      return `
        <div class="chapter-card" onclick="window.location.href='/student/chapters/${c.id}'">
          <span class="chapter-mode-badge mode-badge-practice">📖 Chương luyện tập</span>
          <h3>${c.name}</h3>
          <p class="chapter-meta">👨‍🏫 GV: ${c.teacher_name}</p>
          <p class="chapter-meta">📝 Tiến độ: <strong>${c.completed_exercises} / ${c.total_exercises}</strong> bài đúng</p>
          ${isDone ? '<p class="chapter-complete-badge">✅ Đã hoàn thành</p>' : ''}
        </div>
      `;
    }).join("");

  } catch (err) {
    chapterList.innerHTML = "";
    showMsg(messageEl, "Lỗi kết nối máy chủ.");
  }
}

loadChapters();