const controls = new WeakMap();
let nextId = 0;

function addStyles(document) {
  if (document.querySelector("style[data-searchable-filters]")) return;
  const style = document.createElement("style");
  style.dataset.searchableFilters = "";
  style.textContent = `
    .searchable-filter { position: relative; width: min(100%, 320px); max-width: 100%; }
    .searchable-filter > select[hidden] { display: none !important; }
    .searchable-filter-field { position: relative; }
    .searchable-filter .searchable-filter-input {
      display: block; box-sizing: border-box; width: 100%; min-width: 0; min-height: 42px;
      margin: 0; padding: 9px 42px 9px 12px; border: 1px solid #3b5368;
      border-radius: 6px; color: #fff; background: #10212d; font: inherit;
    }
    .searchable-filter-input::placeholder { color: #b0bec5; opacity: 1; }
    .searchable-filter-input:focus { outline: 2px solid #4fc3f7; outline-offset: 1px; }
    .searchable-filter .searchable-filter-toggle {
      position: absolute; inset: 1px 1px 1px auto; width: 36px; min-height: 0;
      margin: 0; padding: 0; border: 0; border-radius: 0 5px 5px 0;
      color: #b3e5fc; background: transparent; font: inherit; cursor: pointer;
    }
    .searchable-filter-popup {
      position: absolute; left: 0; right: 0; top: calc(100% + 5px); z-index: 100010;
      max-height: 280px; overflow-y: auto; overscroll-behavior: contain;
      border: 1px solid #4fc3f7; border-radius: 7px; background: #142433;
      box-shadow: 0 8px 24px #0008; text-align: left;
    }
    .searchable-filter-popup[hidden] { display: none; }
    .searchable-filter-option { padding: 10px 12px; color: #e0e0e0; cursor: pointer; overflow-wrap: anywhere; }
    .searchable-filter-option[aria-selected="true"] { color: #b9f6ca; font-weight: 700; }
    .searchable-filter-option.is-active, .searchable-filter-option:hover { color: #fff; background: #294c64; }
    .searchable-filter-status { margin: 0; padding: 8px 12px; color: #b0bec5; font-size: .8rem; }
    .searchable-filter-status:empty { display: none; }
    @media (max-width: 720px) { .searchable-filter { width: 100%; } }
  `;
  document.head.appendChild(style);
}

export function enhanceFilterSelect(select) {
  if (controls.has(select)) {
    controls.get(select).refresh();
    return;
  }
  const document = select.ownerDocument;
  const view = document.defaultView;
  addStyles(document);
  const id = `${select.id || "table-filter"}-search-${++nextId}`;
  const wrapper = document.createElement("div");
  wrapper.className = "searchable-filter";
  const field = document.createElement("div");
  field.className = "searchable-filter-field";
  const input = document.createElement("input");
  input.id = id;
  input.type = "text";
  input.className = "searchable-filter-input";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("autocapitalize", "off");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${id}-options`);
  input.setAttribute("aria-label", select.getAttribute("aria-label") || "Select an option");
  document.querySelectorAll("label[for]").forEach(label => {
    if (label.htmlFor === select.id) {
      label.htmlFor = id;
      if (!select.hasAttribute("aria-label")) input.removeAttribute("aria-label");
    }
  });
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.tabIndex = -1;
  toggle.className = "searchable-filter-toggle";
  toggle.textContent = "▾";
  toggle.setAttribute("aria-label", "Show options");
  toggle.setAttribute("aria-controls", `${id}-options`);
  const popup = document.createElement("div");
  popup.className = "searchable-filter-popup";
  popup.hidden = true;
  const list = document.createElement("div");
  list.id = `${id}-options`;
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Available options");
  const status = document.createElement("p");
  status.className = "searchable-filter-status";
  status.setAttribute("role", "status");
  popup.append(list, status);
  field.append(input, toggle);
  select.before(wrapper);
  wrapper.append(select, field, popup);
  select.hidden = true;

  let open = false;
  let editing = false;
  let active = -1;
  let matches = [];
  let lastValue = select.value;

  function positionPopup() {
    const rect = field.getBoundingClientRect();
    const below = view.innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const flip = below < 180 && above > below;
    popup.style.top = flip ? "auto" : "calc(100% + 5px)";
    popup.style.bottom = flip ? "calc(100% + 5px)" : "auto";
    popup.style.maxHeight = `${Math.max(80, Math.min(280, flip ? above : below))}px`;
  }

  function activate(index) {
    active = index;
    [...list.children].forEach((option, i) => option.classList.toggle("is-active", i === index));
    const option = list.children[index];
    if (!option) { input.removeAttribute("aria-activedescendant"); return; }
    input.setAttribute("aria-activedescendant", option.id);
    if (option.offsetTop < popup.scrollTop) popup.scrollTop = option.offsetTop;
    else if (option.offsetTop + option.offsetHeight > popup.scrollTop + popup.clientHeight) {
      popup.scrollTop = option.offsetTop + option.offsetHeight - popup.clientHeight;
    }
  }

  function renderOptions() {
    const query = editing ? input.value.trim().toLowerCase() : "";
    const available = [...select.options].filter(option => !option.disabled &&
      (!option.value || !query || option.textContent.toLowerCase().includes(query)));
    // Put prefix matches first, so typing Z immediately reaches Z tickers.
    matches = query ? [
      ...available.filter(option => !option.value),
      ...available.filter(option => option.value && option.textContent.toLowerCase().startsWith(query)),
      ...available.filter(option => option.value && !option.textContent.toLowerCase().startsWith(query)),
    ] : available;
    list.replaceChildren(...matches.map((option, index) => {
      const item = document.createElement("div");
      item.id = `${id}-option-${index}`;
      item.className = "searchable-filter-option";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(option.value === select.value));
      item.dataset.index = String(index);
      item.textContent = option.textContent;
      return item;
    }));
    const count = matches.filter(option => option.value).length;
    status.textContent = query && !count ? "No matching options. Clear the search to see the full list." : "";
    positionPopup();
    popup.scrollTop = 0;
    activate(query ? matches.findIndex(option => option.value)
      : Math.max(0, matches.findIndex(option => option.value === select.value)));
  }

  function show() {
    if (select.disabled) return;
    open = true;
    popup.hidden = false;
    input.setAttribute("aria-expanded", "true");
    renderOptions();
  }

  function close() {
    open = false;
    editing = false;
    popup.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    input.value = select.value ? select.selectedOptions[0]?.textContent || "" : "";
  }

  function choose(index) {
    if (!matches[index]) return;
    select.value = matches[index].value;
    close();
    select.dispatchEvent(new view.Event("change", { bubbles: true }));
  }

  function refresh() {
    if (!open || select.value !== lastValue) {
      editing = false;
      input.value = select.value ? select.selectedOptions[0]?.textContent || "" : "";
    }
    lastValue = select.value;
    const allLabel = select.options[0]?.textContent || "All options";
    input.placeholder = `${allLabel} — type to search`;
    input.disabled = toggle.disabled = select.disabled;
    if (select.disabled) close();
    if (open) renderOptions();
  }

  input.addEventListener("focus", () => { editing = false; show(); input.select(); });
  input.addEventListener("click", () => {
    if (!open) { editing = false; show(); }
    if (!editing) input.select();
  });
  input.addEventListener("input", () => {
    editing = true;
    if (!input.value.trim() && select.value) {
      select.value = "";
      select.dispatchEvent(new view.Event("change", { bubbles: true }));
    }
    show();
  });
  input.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) { show(); return; }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      activate(Math.max(0, Math.min(matches.length - 1, active + direction)));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Tab") close();
  });
  toggle.addEventListener("mousedown", event => event.preventDefault());
  toggle.addEventListener("click", () => {
    if (open) close();
    else { input.focus(); editing = false; show(); input.select(); }
  });
  list.addEventListener("mousedown", event => event.preventDefault());
  list.addEventListener("click", event => {
    const option = event.target.closest('[role="option"]');
    if (option) choose(Number(option.dataset.index));
  });
  wrapper.addEventListener("focusout", event => {
    if (!wrapper.contains(event.relatedTarget)) close();
  });
  document.addEventListener("pointerdown", event => {
    if (!wrapper.contains(event.target)) close();
  });
  view.addEventListener("resize", () => { if (open) positionPopup(); });
  select.addEventListener("change", refresh);
  new view.MutationObserver(refresh).observe(select, { attributes: true, attributeFilter: ["disabled"] });
  controls.set(select, { refresh });
  refresh();
}
