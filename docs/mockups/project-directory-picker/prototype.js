const projects = document.querySelectorAll("[data-project]");
const pathInputs = document.querySelectorAll("[data-path-input]");
const selectedNames = document.querySelectorAll("[data-selected-name]");

function selectProject(row) {
  document.querySelectorAll("[data-project]").forEach((item) => {
    item.classList.toggle("is-selected", item === row);
  });
  document.querySelectorAll("[data-folder]").forEach((item) => {
    item.classList.remove("is-selected");
  });
  pathInputs.forEach((input) => {
    input.value = row.dataset.path;
  });
  selectedNames.forEach((label) => {
    label.textContent = row.dataset.project;
  });
}

projects.forEach((row) => {
  row.addEventListener("click", () => selectProject(row));
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest(".dialog");
    const target = button.dataset.view;
    dialog.querySelectorAll("[data-view]").forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    dialog
      .querySelector(".recents")
      ?.classList.toggle("is-hidden", target !== "recents");
    dialog
      .querySelector(".browser")
      ?.classList.toggle("is-visible", target === "browser");
  });
});

document.querySelectorAll("[data-open-browser]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest(".dialog");
    dialog.querySelector(".recents")?.classList.add("is-hidden");
    dialog.querySelector(".browser")?.classList.add("is-visible");
    dialog.querySelectorAll("[data-view]").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.view === "browser");
    });
  });
});

document.querySelectorAll("[data-show-recents]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest(".dialog");
    dialog.querySelector(".recents")?.classList.remove("is-hidden");
    dialog.querySelector(".browser")?.classList.remove("is-visible");
  });
});

document.querySelectorAll("[data-folder]").forEach((folder) => {
  folder.addEventListener("click", () => {
    const scope = folder.closest(".browser, .split-pane");
    scope?.querySelectorAll("[data-folder]").forEach((item) => {
      item.classList.toggle("is-selected", item === folder);
    });
    document.querySelectorAll("[data-project]").forEach((item) => {
      item.classList.remove("is-selected");
    });
    pathInputs.forEach((input) => {
      input.value = folder.dataset.folder;
    });
    selectedNames.forEach((label) => {
      label.textContent = folder.dataset.name;
    });
  });
});

document.querySelectorAll("[data-apply]").forEach((button) => {
  button.addEventListener("click", () => {
    const original = button.innerHTML;
    button.innerHTML = '<i data-lucide="check"></i>已应用';
    button.style.background = "#30956c";
    button.style.borderColor = "#30956c";
    window.lucide?.createIcons();
    window.setTimeout(() => {
      button.innerHTML = original;
      button.style.background = "";
      button.style.borderColor = "";
      window.lucide?.createIcons();
    }, 1300);
  });
});

window.lucide?.createIcons();
