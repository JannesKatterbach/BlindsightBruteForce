"use strict";
// Help buttons ("i") with an explanation popover. Field help comes from the schema (field.help), help of
// page sections from data-help keys of the UI catalogs (optional data-help-title for the heading).

let helpAnchor = null;  // button whose popover is open

/** Help button. getTitle and getText are called on click, so the text follows a language switch. */
function helpButton(getTitle, getText) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "helpBtn";
  button.title = t("ui.help.button");
  button.setAttribute("aria-label", t("ui.help.button"));
  button.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleHelp(button, getTitle(), getText());
  });
  return button;
}

function toggleHelp(button, title, text) {
  const pop = $("#helpPop");
  if (helpAnchor === button && !pop.hidden) { closeHelp(); return; }
  helpAnchor = button;
  pop.innerHTML = `<div class="helpHead"><b>${esc(title)}</b><button type="button" class="helpClose" aria-label="${esc(t("ui.help.close"))}">×</button></div>` +
    `<p>${esc(text)}</p>`;
  pop.querySelector(".helpClose").addEventListener("click", closeHelp);
  pop.hidden = false;
  const r = button.getBoundingClientRect(), w = Math.min(380, window.innerWidth - 24);
  pop.style.width = w + "px";
  pop.style.left = Math.max(12, Math.min(window.scrollX + r.left - 20, window.scrollX + window.innerWidth - w - 12)) + "px";
  pop.style.top = window.scrollY + r.bottom + 6 + "px";
}

function closeHelp() {
  $("#helpPop").hidden = true;
  helpAnchor = null;
}

/** Visible text of an element without its help button. */
const ownText = (node) => [...node.childNodes].filter((c) => !(c.classList && c.classList.contains("helpBtn"))).map((c) => c.textContent).join("").trim();

/** Add help buttons to all elements with data-help that have none yet (called again after text changes). */
function attachStaticHelp(root = document) {
  for (const node of root.querySelectorAll("[data-help]")) {
    if ([...node.children].some((c) => c.classList.contains("helpBtn"))) continue;
    const title = () => (node.dataset.helpTitle ? t(node.dataset.helpTitle) : ownText(node));
    node.appendChild(helpButton(title, () => t(node.dataset.help)));
  }
}

/** Field label with the field's help button, if the field has a help text. */
function setFieldLabel(label, field, text) {
  label.textContent = text;
  if (field.help) label.appendChild(helpButton(() => field.label, () => fieldByPath(field.path).help));
}

function initHelp() {
  const pop = document.createElement("div");
  pop.id = "helpPop";
  pop.className = "helpPop";
  pop.setAttribute("role", "dialog");
  pop.hidden = true;
  document.body.appendChild(pop);
  pop.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => { if (!pop.hidden) closeHelp(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) closeHelp(); });
  attachStaticHelp();
}
