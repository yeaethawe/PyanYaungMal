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

  document.querySelectorAll(".toast-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".toast")?.remove());
  });

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.row-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) {
        menu.removeAttribute("open");
      }
    });
  });
})();
