(() => {
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const userSearch = document.getElementById("user-search");
  const globalSearch = document.getElementById("global-search");
  const selectAll = document.getElementById("select-all");
  const membersTable = document.getElementById("members-table");
  const warnDialog = document.getElementById("warn-dialog");
  const warnUser = document.getElementById("warn_user");
  const openWarn = document.getElementById("open-warn");
  const closeWarn = document.getElementById("close-warn");

  sidebarToggle?.addEventListener("click", () => {
    document.body.classList.toggle("nav-open");
  });

  function filterRows(query) {
    const needle = query.trim().toLowerCase();
    document.querySelectorAll("tr[data-search]").forEach((row) => {
      const haystack = row.getAttribute("data-search") || "";
      row.hidden = Boolean(needle) && !haystack.toLowerCase().includes(needle);
    });
  }

  userSearch?.addEventListener("input", () => {
    if (globalSearch) {
      globalSearch.value = userSearch.value;
    }
    filterRows(userSearch.value);
  });

  globalSearch?.addEventListener("input", () => {
    if (userSearch) {
      userSearch.value = globalSearch.value;
    }
    filterRows(globalSearch.value);
  });

  selectAll?.addEventListener("change", () => {
    membersTable
      ?.querySelectorAll('tbody input[type="checkbox"]')
      .forEach((box) => {
        box.checked = selectAll.checked;
      });
  });

  function openWarnDialog(userId) {
    if (!warnDialog) {
      return;
    }
    if (warnUser && userId) {
      warnUser.value = String(userId);
    }
    if (typeof warnDialog.showModal === "function") {
      warnDialog.showModal();
    }
  }

  openWarn?.addEventListener("click", () => openWarnDialog());
  closeWarn?.addEventListener("click", () => warnDialog?.close());

  document.querySelectorAll(".warn-open").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest("details")?.removeAttribute("open");
      openWarnDialog(button.dataset.userId);
    });
  });

  document.querySelectorAll(".detail-open").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest("details")?.removeAttribute("open");
      const dialog = document.getElementById(button.dataset.dialog);
      if (dialog && typeof dialog.showModal === "function") {
        dialog.showModal();
      }
    });
  });

  document.querySelectorAll(".detail-close").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });

  document.querySelectorAll(".toast-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".toast")?.remove());
  });

  window.addEventListener("dragover", (event) => {
    if (event.dataTransfer && [...event.dataTransfer.types].includes("Files")) {
      event.preventDefault();
    }
  });

  window.addEventListener("drop", (event) => {
    if (event.dataTransfer && [...event.dataTransfer.types].includes("Files")) {
      event.preventDefault();
    }
  });

  function acceptedImage(input, file) {
    if (!file || !String(file.type).startsWith("image/")) {
      return false;
    }
    const rules = (input.getAttribute("accept") || "image/*")
      .split(",")
      .map((rule) => rule.trim())
      .filter(Boolean);
    if (!rules.length || rules.includes("image/*")) {
      return true;
    }
    return rules.includes(file.type);
  }

  function refreshFileDrop(zone) {
    const input = zone.querySelector('input[type="file"]');
    const preview = zone.querySelector(".file-drop-preview");
    const placeholder = zone.querySelector(".file-drop-placeholder");
    const fallback = zone.querySelector(".file-drop-fallback");
    const title = zone.querySelector(".file-drop-title");
    const sub = zone.querySelector(".file-drop-sub");
    const name = zone.querySelector(".file-drop-name");
    const file = input && input.files && input.files[0];
    const hasPreview = Boolean(preview && preview.getAttribute("src") && !preview.hidden);
    const previewIsLocal = Boolean(preview && String(preview.getAttribute("src") || "").startsWith("blob:"));
    const ready = Boolean(file) && (!input || !input.hasAttribute("data-image-crop") || previewIsLocal);
    zone.classList.toggle("has-file", ready);
    zone.classList.toggle("has-preview", hasPreview);
    if (placeholder) {
      placeholder.hidden = hasPreview;
    }
    if (fallback) {
      fallback.hidden = hasPreview;
    }
    if (title) {
      title.textContent = ready
        ? zone.dataset.ready || title.textContent
        : hasPreview
          ? zone.dataset.change || title.textContent
          : zone.dataset.choose || title.textContent;
    }
    if (sub) {
      sub.hidden = ready;
    }
    if (name) {
      name.hidden = !ready;
      name.textContent = ready ? zone.dataset.picked || file.name : "";
    }
  }

  function previewDroppedFile(input, file) {
    if (input.hasAttribute("data-image-crop")) {
      return;
    }
    const img = input.closest("[data-file-drop]")?.querySelector(".file-drop-preview");
    if (!img) {
      return;
    }
    if (input._dropPreviewUrl) {
      URL.revokeObjectURL(input._dropPreviewUrl);
    }
    input._dropPreviewUrl = URL.createObjectURL(file);
    img.src = input._dropPreviewUrl;
    img.hidden = false;
  }

  document.querySelectorAll("[data-file-drop]").forEach((zone) => {
    const input = zone.querySelector('input[type="file"]');
    if (!input) {
      return;
    }
    let dragDepth = 0;

    zone.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dragDepth += 1;
      zone.classList.add("is-dragover");
    });
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "copy";
      }
    });
    zone.addEventListener("dragleave", (event) => {
      event.preventDefault();
      dragDepth -= 1;
      if (dragDepth <= 0) {
        dragDepth = 0;
        zone.classList.remove("is-dragover");
      }
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      dragDepth = 0;
      zone.classList.remove("is-dragover");
      const dropped = [...((event.dataTransfer && event.dataTransfer.files) || [])].filter((file) =>
        acceptedImage(input, file)
      );
      if (!dropped.length) {
        return;
      }
      const transfer = new DataTransfer();
      if (input.multiple) {
        dropped.forEach((file) => transfer.items.add(file));
      } else {
        transfer.items.add(dropped[0]);
      }
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (file && acceptedImage(input, file)) {
        previewDroppedFile(input, file);
      }
      refreshFileDrop(zone);
    });

    refreshFileDrop(zone);
  });

  document.querySelectorAll("[data-photo-picker]").forEach((picker) => {
    picker.querySelectorAll("[data-remove-existing]").forEach((button) => {
      button.addEventListener("click", () => {
        const thumb = button.closest(".photo-thumb");
        const checkbox = thumb?.querySelector('input[name="remove_photo"]');
        const input = picker.querySelector('input[type="file"]');
        const removing = thumb && !thumb.classList.contains("is-removed");
        if (removing) {
          const kept = picker.querySelectorAll(".photo-thumb[data-existing-id]:not(.is-removed)").length;
          const incoming = (input && input._pickedFiles && input._pickedFiles.length) || 0;
          if (kept + incoming <= 1) {
            return;
          }
        }
        thumb?.classList.toggle("is-removed");
        if (checkbox) {
          checkbox.checked = Boolean(thumb?.classList.contains("is-removed"));
        }
      });
    });
  });

  document.querySelectorAll("[data-gallery]").forEach((gallery) => {
    const slides = [...gallery.querySelectorAll("img")];
    const count = gallery.querySelector(".gallery-count");
    let index = 0;
    function show(next) {
      index = (next + slides.length) % slides.length;
      slides.forEach((image, imageIndex) => {
        image.hidden = imageIndex !== index;
      });
      if (count) {
        count.textContent = `${index + 1}/${slides.length}`;
      }
    }
    gallery.querySelector(".gallery-prev")?.addEventListener("click", (event) => {
      event.preventDefault();
      show(index - 1);
    });
    gallery.querySelector(".gallery-next")?.addEventListener("click", (event) => {
      event.preventDefault();
      show(index + 1);
    });
  });

  const screenshotInput = document.getElementById("screenshot");
  const screenshotName = document.getElementById("screenshot-name");
  screenshotInput?.addEventListener("change", () => {
    if (!screenshotName) {
      return;
    }
    const file = screenshotInput.files && screenshotInput.files[0];
    screenshotName.hidden = !file;
    screenshotName.textContent = file ? file.name : "";
  });

  const messageList = document.getElementById("message-list");
  if (messageList) {
    messageList.scrollTop = messageList.scrollHeight;
    const liveUrl = messageList.dataset.liveUrl;
    const sendUrl = messageList.dataset.sendUrl;
    const compose = document.getElementById("chat-compose");
    const bodyInput = document.getElementById("body");
    const shotInput = document.getElementById("screenshot");
    const shotName = document.getElementById("screenshot-name");
    let pollTimer = 0;
    let polling = false;

    function lastMessageId() {
      const nodes = messageList.querySelectorAll("[data-message-id]");
      if (!nodes.length) {
        return 0;
      }
      return Number(nodes[nodes.length - 1].dataset.messageId) || 0;
    }

    function lastMessageNode() {
      const nodes = messageList.querySelectorAll("[data-message-id]");
      return nodes.length ? nodes[nodes.length - 1] : null;
    }

    function nearBottom() {
      return messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight < 80;
    }

    function appendMessage(item) {
      if (messageList.querySelector(`[data-message-id="${item.id}"]`)) {
        return;
      }
      messageList.querySelector(".chat-empty")?.remove();
      const previous = lastMessageNode();
      const prevDay = previous ? previous.dataset.day : "";
      const prevSender = previous ? previous.dataset.sender : "";
      if (item.day && item.day !== prevDay) {
        const dayItem = document.createElement("li");
        dayItem.className = "chat-day";
        dayItem.innerHTML = `<span></span>`;
        dayItem.querySelector("span").textContent = item.day;
        messageList.append(dayItem);
      }
      const row = document.createElement("li");
      row.className = "message";
      if (item.mine) {
        row.classList.add("is-mine");
      }
      if (previous && item.day === prevDay && String(item.sender_id) === prevSender) {
        row.classList.add("is-follow");
      }
      row.dataset.messageId = String(item.id);
      row.dataset.sender = String(item.sender_id);
      row.dataset.day = item.day || "";
      if (item.photo_url) {
        const link = document.createElement("a");
        link.href = item.photo_url;
        link.target = "_blank";
        link.rel = "noopener";
        const image = document.createElement("img");
        image.className = "payment-shot";
        image.src = item.photo_url;
        image.alt = item.photo_alt || messageList.dataset.photoAlt || "";
        link.append(image);
        row.append(link);
      }
      if (item.body) {
        const text = document.createElement("p");
        text.textContent = item.body;
        row.append(text);
      }
      const time = document.createElement("time");
      time.textContent = item.time || "";
      row.append(time);
      messageList.append(row);
    }

    async function poll() {
      if (!liveUrl || polling || document.hidden) {
        return;
      }
      polling = true;
      try {
        const response = await fetch(`${liveUrl}?after=${lastMessageId()}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        const stick = nearBottom();
        (data.messages || []).forEach(appendMessage);
        if (stick) {
          messageList.scrollTop = messageList.scrollHeight;
        }
        if (data.ended && messageList.dataset.ended !== "1") {
          window.location.reload();
          return;
        }
        if (data.can_end_sale && messageList.dataset.canEndSale !== "1") {
          window.location.reload();
        }
      } catch (_error) {
        // Keep polling even if the network blips.
      } finally {
        polling = false;
      }
    }

    function schedulePoll() {
      window.clearTimeout(pollTimer);
      if (document.hidden || messageList.dataset.ended === "1") {
        return;
      }
      pollTimer = window.setTimeout(async () => {
        await poll();
        schedulePoll();
      }, 1500);
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        window.clearTimeout(pollTimer);
        return;
      }
      poll().finally(schedulePoll);
    });

    compose?.addEventListener("submit", async (event) => {
      if (!sendUrl || !window.fetch) {
        return;
      }
      event.preventDefault();
      const formData = new FormData(compose);
      const sendButton = compose.querySelector(".chat-send");
      if (sendButton) {
        sendButton.disabled = true;
      }
      try {
        const response = await fetch(sendUrl, {
          method: "POST",
          cache: "no-store",
          headers: { Accept: "application/json" },
          body: formData,
        });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data || !data.ok) {
          window.alert((data && data.error) || "Could not send that message.");
          return;
        }
        const stick = nearBottom();
        if (data.message) {
          appendMessage(data.message);
        }
        if (stick) {
          messageList.scrollTop = messageList.scrollHeight;
        }
        if (bodyInput) {
          bodyInput.value = "";
        }
        if (shotInput) {
          shotInput.value = "";
        }
        if (shotName) {
          shotName.hidden = true;
          shotName.textContent = "";
        }
        if (data.ended) {
          window.location.reload();
        }
      } catch (_error) {
        window.alert("Could not send that message.");
      } finally {
        if (sendButton) {
          sendButton.disabled = false;
        }
        bodyInput?.focus();
      }
    });

    if (messageList.dataset.ended !== "1") {
      schedulePoll();
    }
  }

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.row-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) {
        menu.removeAttribute("open");
      }
    });
  });
})();
