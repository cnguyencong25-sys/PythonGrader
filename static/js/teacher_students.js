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

const tableBody = document.getElementById("studentTableBody");
const searchInput = document.getElementById("studentSearch");
const messageEl = document.getElementById("studentListMessage");
const deleteModal = document.getElementById("deleteStudentModal");
const deleteName = document.getElementById("deleteStudentName");
const deleteButton = document.getElementById("confirmDeleteStudent");
let students = [];
let pendingDeleteId = null;

function renderStudents() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const filtered = students.filter(student => [
    student.student_id, student.full_name, student.class_name, student.email
  ].some(value => String(value || "").toLocaleLowerCase().includes(query)));

  document.getElementById("studentCount").textContent = query
    ? `${filtered.length} / ${students.length}`
    : String(students.length);

  if (!filtered.length) {
    const text = students.length ? "Không tìm thấy sinh viên phù hợp." : "Chưa có tài khoản sinh viên.";
    tableBody.innerHTML = `<tr><td class="empty-table-cell" colspan="6">${text}</td></tr>`;
    return;
  }

  tableBody.innerHTML = filtered.map(student => `
    <tr>
      <td><span class="student-id-chip">${escapeHtml(student.student_id || "—")}</span></td>
      <td><strong class="student-table-name">${escapeHtml(student.full_name || "Chưa cập nhật")}</strong></td>
      <td>${escapeHtml(student.class_name || "—")}</td>
      <td class="student-email-cell">${escapeHtml(student.email)}</td>
      <td>
        <a class="btn-secondary student-history-link" href="/teacher/students/${student.id}/history">
          Xem bài đã làm
        </a>
      </td>
      <td>
        <button type="button" class="btn-delete-small delete-student-button"
                data-student-id="${student.id}" data-student-name="${escapeHtml(student.full_name || student.email)}">
          Xóa tài khoản
        </button>
      </td>
    </tr>
  `).join("");

  tableBody.querySelectorAll(".delete-student-button").forEach(button => {
    button.addEventListener("click", () => {
      pendingDeleteId = Number(button.dataset.studentId);
      deleteName.textContent = button.dataset.studentName;
      deleteModal.classList.remove("hidden");
    });
  });
}

function closeDeleteModal() {
  deleteModal.classList.add("hidden");
  pendingDeleteId = null;
}

async function loadStudents() {
  try {
    const { ok, data } = await fetchJSON("/api/teacher/students");
    if (!ok || !data.success) {
      tableBody.innerHTML = `<tr><td class="empty-table-cell" colspan="6">${escapeHtml(data.message || "Không tải được danh sách sinh viên.")}</td></tr>`;
      return;
    }
    students = data.students || [];
    renderStudents();
  } catch (error) {
    tableBody.innerHTML = '<tr><td class="empty-table-cell" colspan="6">Không thể kết nối máy chủ.</td></tr>';
  }
}

searchInput.addEventListener("input", renderStudents);
document.getElementById("cancelDeleteStudent").addEventListener("click", closeDeleteModal);
deleteModal.addEventListener("click", event => {
  if (event.target === deleteModal) closeDeleteModal();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !deleteModal.classList.contains("hidden")) closeDeleteModal();
});

deleteButton.addEventListener("click", async () => {
  if (pendingDeleteId === null) return;
  deleteButton.disabled = true;
  try {
    const { ok, data } = await fetchJSON(`/api/teacher/students/${pendingDeleteId}`, {
      method: "DELETE",
    });
    if (!ok || !data.success) {
      messageEl.textContent = data.message || "Không thể xóa tài khoản.";
      messageEl.className = "message error";
      return;
    }
    students = students.filter(student => student.id !== pendingDeleteId);
    closeDeleteModal();
    renderStudents();
    messageEl.textContent = data.message || "Đã xóa tài khoản sinh viên.";
    messageEl.className = "message success";
  } catch (error) {
    messageEl.textContent = "Không thể kết nối máy chủ để xóa tài khoản.";
    messageEl.className = "message error";
  } finally {
    deleteButton.disabled = false;
  }
});

loadStudents();
