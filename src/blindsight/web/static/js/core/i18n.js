"use strict";
// Translations of the UI (German, English, French). The catalogs js/i18n/<language>.js fill I18N_CATALOGS.
// Texts of the core (field labels, tips, messages) come translated from the server, which answers in the
// language sent with every request (header X-Language, see api in util.js).

const I18N_CATALOGS = {};
const LANGUAGES = ["de", "en", "fr"];
const DEFAULT_LANGUAGE = "de";
const LANGUAGE_KEY = "blindsight.language";

/** Stored choice, otherwise the first supported browser language, otherwise German. */
function initialLanguage() {
  try {
    const stored = localStorage.getItem(LANGUAGE_KEY);
    if (LANGUAGES.includes(stored)) return stored;
  } catch (e) { /* storage blocked, fall back to the browser language */ }
  for (const code of navigator.languages || [navigator.language || ""]) {
    const short = String(code).slice(0, 2).toLowerCase();
    if (LANGUAGES.includes(short)) return short;
  }
  return DEFAULT_LANGUAGE;
}

let currentLanguage = initialLanguage();

/** Text for key in the current language. {name} placeholders are replaced by params.name. */
function t(key, params = {}) {
  const catalog = I18N_CATALOGS[currentLanguage] || {};
  const template = catalog[key] ?? (I18N_CATALOGS[DEFAULT_LANGUAGE] || {})[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

/** Number in the format of the current language (thousands separators). */
const fmtCount = (value) => Number(value).toLocaleString(currentLanguage);

/** Static texts of the page (data-i18n for the content, data-i18n-title and data-i18n-placeholder). */
function applyStaticTexts(root = document) {
  for (const node of root.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll("[data-i18n-title]")) node.title = t(node.dataset.i18nTitle);
  for (const node of root.querySelectorAll("[data-i18n-placeholder]")) node.placeholder = t(node.dataset.i18nPlaceholder);
  document.documentElement.lang = currentLanguage;
}

/** Switch the language of the static texts and remember it. Dynamic parts are rebuilt by the caller. */
function setLanguage(language) {
  currentLanguage = LANGUAGES.includes(language) ? language : DEFAULT_LANGUAGE;
  try { localStorage.setItem(LANGUAGE_KEY, currentLanguage); } catch (e) { /* not remembered, still switched */ }
  applyStaticTexts();
}
