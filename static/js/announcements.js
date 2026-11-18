(() => {
  const modal = document.getElementById("announcementModal");
  const toggle = document.getElementById("announcementToggle");
  if (!modal || !toggle) return;

  const role = modal.dataset.role;
  const list = document.getElementById("announcementList");
  const badge = document.getElementById("announcementBadge");
  const errorEl = document.getElementById("announcementError");
  const closeButton = document.getElementById("announcementClose");
  const form = document.getElementById("announcementForm");
  const contentInput = document.getElementById("announcementContent");
  const sendButton = document.getElementById("announcementSend");
  const ttlMs = 24 * 60 * 60 * 1000;
  let loading = false;
  let markVisibleAfterLoad = false;
  let renderedSignature = null;

  async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json();
    if (!response.ok || !data.success) {
      throw new Error(data.message || "Không thể tải thông báo.");
    }
    return data;
  }

  function setError(message = "") {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function updateBadge(count) {
    if (!badge) return;
    const unread = Math.max(0, Number(count) || 0);
    badge.hidden = unread === 0;
    badge.textContent = unread > 9 ? "9+" : String(unread);
    toggle.setAttribute("aria-label", unread ? `Thông báo, ${unread} chưa đọc` : "Thông báo");
  }

  function renderAnnouncements(items) {
    const activeItems = items.filter(item => {
      const createdAt = Date.parse(item.created_at);
      return Number.isFinite(createdAt) && Date.now() - createdAt < ttlMs;
    });
    const signature = JSON.stringify(activeItems);
    if (signature === renderedSignature) return;
    renderedSignature = signature;
    list.replaceChildren();

    if (activeItems.length === 0) {
      const empty = document.createElement("div");
      empty.className = "announcement-empty";
      empty.textContent = "Hiện chưa có thông báo nào trong 24 giờ qua.";
      list.append(empty);
      return;
    }

    for (const item of activeItems) {
      const card = document.createElement("article");
      card.className = "announcement-card";

      const message = document.createElement("div");
      message.className = "announcement-card-content";
      message.textContent = item.content;

      const meta = document.createElement("div");
      meta.className = "announcement-card-meta";
      const sentAt = document.createElement("time");
      sentAt.dateTime = item.created_at;
      sentAt.textContent = new Date(item.created_at).toLocaleString("vi-VN", {
        dateStyle: "short",
        timeStyle: "short",
      });
      meta.appendChild(sentAt);

      if (role === "teacher") {
        const deleteButton = document.createElement("button");
        deleteButton.className = "announcement-delete";
        deleteButton.type = "button";
        deleteButton.textContent = "Xóa";
        deleteButton.addEventListener("click", () => deleteAnnouncement(item.id));
        meta.appendChild(deleteButton);
      }

      card.append(message, meta);
      list.append(card);
    }
  }

  async function markVisibleAsRead(items) {
    if (role !== "student" || items.length === 0) return;
    const throughId = Math.max(...items.map(item => Number(item.id) || 0));
    if (!throughId) return;
    const result = await apiRequest("/api/announcements/read", {
      method: "POST",
      body: JSON.stringify({ through_id: throughId }),
    });
    updateBadge(result.unread_count);
  }

  async function refreshAnnouncements(markVisible = false) {
    if (loading) {
      markVisibleAfterLoad = markVisibleAfterLoad || markVisible;
      return;
    }
    loading = true;
    list.setAttribute("aria-busy", "true");
    try {
      const result = await apiRequest("/api/announcements");
      renderAnnouncements(result.announcements);
      updateBadge(result.unread_count);
      if (markVisible && result.unread_count > 0) {
        await markVisibleAsRead(result.announcements);
      }
      setError("");
    } catch (error) {
      setError(error.message || "Không thể tải thông báo. Vui lòng thử lại.");
    } finally {
      list.removeAttribute("aria-busy");
      loading = false;
      if (markVisibleAfterLoad) {
        markVisibleAfterLoad = false;
        refreshAnnouncements(true);
      }
    }
  }

  async function deleteAnnouncement(id) {
    if (!window.confirm("Bạn có chắc muốn xóa thông báo này?")) return;
    try {
      await apiRequest(`/api/announcements/${id}`, { method: "DELETE" });
      await refreshAnnouncements();
    } catch (error) {
      setError(error.message || "Không thể xóa thông báo.");
    }
  }

  function openModal() {
    modal.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    setError("");
    refreshAnnouncements(role === "student");
    closeButton.focus();
  }

  function closeModal() {
    modal.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.focus();
  }

  toggle.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  modal.addEventListener("click", event => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });

  if (form && contentInput && sendButton) {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const content = contentInput.value.trim();
      if (!content) {
        setError("Vui lòng nhập nội dung thông báo.");
        contentInput.focus();
        return;
      }

      sendButton.disabled = true;
      setError("");
      try {
        await apiRequest("/api/announcements", {
          method: "POST",
          body: JSON.stringify({ content }),
        });
        contentInput.value = "";
        await refreshAnnouncements();
      } catch (error) {
        setError(error.message || "Không thể gửi thông báo.");
      } finally {
        sendButton.disabled = false;
      }
    });
  }

  refreshAnnouncements();
  window.setInterval(() => {
    refreshAnnouncements(role === "student" && !modal.hidden);
  }, 15000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      refreshAnnouncements(role === "student" && !modal.hidden);
    }
  });
})();
