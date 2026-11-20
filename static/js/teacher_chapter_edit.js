/**
 * teacher_chapter_edit.js — trang cấu hình chương
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
  return { ok: res.ok, data };
}

const messageEl = document.getElementById("message");
const infoForm = document.getElementById("chapterInfoForm");
const chapterId = infoForm.dataset.chapterId;

// ============================================================
// LƯU THÔNG TIN CHƯƠNG
// ============================================================
infoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = infoForm.querySelector('button[type="submit"]');
  btn.disabled = true;
  showMsg(messageEl, "Đang lưu...", "");

  const name = document.getElementById("chapterName").value.trim();

  try {
    const { ok, data } = await fetchJSON(`/api/chapters/${chapterId}`, {
      method: "PUT",
      body: JSON.stringify({ name }),
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

// ============================================================
// XOÁ BÀI TẬP
// ============================================================
document.querySelectorAll(".btn-delete-small").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Xoá bài tập này?")) return;

    const { ok, data } = await fetchJSON(`/api/chapters/exercises/${btn.dataset.id}`, {
      method: "DELETE",
    });

    if (ok && data.success) {
      btn.closest(".exercise-item").remove();
      // Cập nhật số đếm
      const count = document.querySelectorAll(".exercise-item").length;
      const badge = document.getElementById("exerciseCountBadge");
      if (badge) badge.textContent = count;
      showMsg(messageEl, "Đã xoá bài tập.", "success");
    } else {
      showMsg(messageEl, data.message || "Không xoá được.");
    }
  });
});

// ============================================================
// ẨN / XUẤT BẢN BÀI TẬP
// ============================================================
document.querySelectorAll(".btn-toggle-small").forEach((btn) => {
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const { ok, data } = await fetchJSON(
        `/api/chapters/exercises/${btn.dataset.id}/toggle-publish`,
        { method: "POST" }
      );

      if (!ok || !data.success) {
        showMsg(messageEl, data.message || "Không thể thay đổi trạng thái bài tập.");
        return;
      }

      const isPublished = Boolean(data.is_published);
      btn.dataset.publish = isPublished ? "1" : "0";
      btn.textContent = isPublished ? "Ẩn bài" : "Xuất bản";
      btn.classList.toggle("btn-warning", isPublished);
      btn.classList.toggle("btn-success", !isPublished);
      showMsg(
        messageEl,
        isPublished ? "Đã xuất bản bài tập cho sinh viên." : "Đã ẩn bài tập khỏi sinh viên.",
        "success"
      );
    } catch (error) {
      showMsg(messageEl, "Lỗi kết nối máy chủ.");
    } finally {
      btn.disabled = false;
    }
  });
});