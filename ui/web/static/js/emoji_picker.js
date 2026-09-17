/** Сетка флагов/эмодзи для имени сервера.
 *
 * Общая для модалки «Добавить сервер» (servers.js) и Quick Setup →
 * Система → Имя (quick_setup.js): одинаковый набор, одинаковое
 * поведение — кнопка 🙂 у поля, попап с сеткой, вставка в позицию
 * курсора, клик мимо поля закрывает.
 *
 * CSS-классы (af-name-wrap / af-emoji-btn / af-emoji-pop / …) —
 * общие, определены в pages.css.
 */

// Прямыми идут флаги стран (с тултипом-названием), затем обычные эмодзи.
const NAME_FLAGS = [
  ['🇩🇪', 'Германия'], ['🇳🇱', 'Нидерланды'], ['🇫🇮', 'Финляндия'], ['🇸🇪', 'Швеция'],
  ['🇳🇴', 'Норвегия'], ['🇩🇰', 'Дания'], ['🇬🇧', 'Великобритания'], ['🇮🇪', 'Ирландия'],
  ['🇫🇷', 'Франция'], ['🇧🇪', 'Бельгия'], ['🇱🇺', 'Люксембург'], ['🇦🇹', 'Австрия'],
  ['🇨🇭', 'Швейцария'], ['🇪🇸', 'Испания'], ['🇵🇹', 'Португалия'], ['🇮🇹', 'Италия'],
  ['🇵🇱', 'Польша'], ['🇨🇿', 'Чехия'], ['🇸🇰', 'Словакия'], ['🇭🇺', 'Венгрия'],
  ['🇷🇴', 'Румыния'], ['🇧🇬', 'Болгария'], ['🇬🇷', 'Греция'], ['🇭🇷', 'Хорватия'],
  ['🇸🇮', 'Словения'], ['🇷🇸', 'Сербия'], ['🇱🇹', 'Литва'], ['🇱🇻', 'Латвия'],
  ['🇪🇪', 'Эстония'], ['🇺🇦', 'Украина'], ['🇷🇺', 'Россия'], ['🇧🇾', 'Беларусь'],
  ['🇲🇩', 'Молдова'], ['🇮🇸', 'Исландия'], ['🇲🇹', 'Мальта'], ['🇨🇾', 'Кипр'],
  ['🇹🇷', 'Турция'], ['🇬🇪', 'Грузия'], ['🇦🇲', 'Армения'], ['🇦🇿', 'Азербайджан'],
  ['🇰🇿', 'Казахстан'], ['🇮🇱', 'Израиль'], ['🇦🇪', 'ОАЭ'], ['🇸🇬', 'Сингапур'],
  ['🇯🇵', 'Япония'], ['🇭🇰', 'Гонконг'], ['🇨🇳', 'Китай'], ['🇰🇷', 'Южная Корея'],
  ['🇮🇳', 'Индия'], ['🇮🇩', 'Индонезия'], ['🇹🇭', 'Таиланд'], ['🇻🇳', 'Вьетнам'],
  ['🇺🇸', 'США'], ['🇨🇦', 'Канада'], ['🇲🇽', 'Мексика'], ['🇧🇷', 'Бразилия'],
  ['🇦🇷', 'Аргентина'], ['🇨🇱', 'Чили'], ['🇦🇺', 'Австралия'], ['🇳🇿', 'Новая Зеландия'],
  ['🇿🇦', 'ЮАР'], ['🇪🇬', 'Египет'], ['🇳🇬', 'Нигерия'], ['🇰🇪', 'Кения'],
  ['🇶🇦', 'Катар'], ['🇰🇼', 'Кувейт'], ['🇸🇦', 'Саудовская Арабия'], ['🇵🇭', 'Филиппины'],
  ['🇲🇾', 'Малайзия'], ['🇹🇼', 'Тайвань'], ['🇧🇩', 'Бангладеш'], ['🇵🇰', 'Пакистан'],
];
const NAME_EMOJIS = [
  '🖥', '💻', '🌐', '🌍', '🐧', '🚀', '⚡', '🔥', '🛡', '💾', '🗄', '🗃',
  '📦', '🧠', '🐳', '🔑', '🔒', '🧩', '⚙', '📡', '🛰', '🎯', '✨', '🌩',
];

function _item(emoji, title = '') {
  return `<button type="button" class="af-emoji-item" data-emoji="${emoji}"${title ? ` title="${title}"` : ''}>${emoji}</button>`;
}

/** HTML сетки (флаги + разделитель + обычные эмодзи). */
export function emojiGridHtml() {
  return NAME_FLAGS.map(([e, t]) => _item(e, t)).join('')
    + '<div class="af-emoji-sep"></div>'
    + NAME_EMOJIS.map(e => _item(e)).join('');
}

/** Показать/скрыть попап (force undefined — переключить). */
export function toggleEmojiPop(popId, force) {
  const pop = document.getElementById(popId);
  if (!pop) return;
  const show = force === undefined ? pop.classList.contains('hidden') : force;
  pop.classList.toggle('hidden', !show);
}

/** Вставить эмодзи в позицию курсора поля и закрыть попап. */
export function insertEmoji(inputId, emoji, popId) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const start = inp.selectionStart ?? inp.value.length;
  const end = inp.selectionEnd ?? start;
  inp.value = inp.value.slice(0, start) + emoji + inp.value.slice(end);
  const pos = start + emoji.length;
  inp.focus();
  inp.setSelectionRange(pos, pos);
  if (popId) toggleEmojiPop(popId, false);
}

/** Привязать пикер к разметке (id поля, кнопки 🙂 и попапа).
 *
 * Разметка пересоздаётся при перерисовке секции — привязка рассчитана
 * на повторные вызовы: слушатели вешаются на свежие элементы, попап
 * заполняется один раз (childElementCount). Клик мимо поля закрывает
 * ВСЕ открытые попапы — один глобальный слушатель на модуль.
 */
export function bindEmojiPicker({ inputId, btnId, popId }) {
  const pop = document.getElementById(popId);
  if (!pop) return;
  if (!pop.childElementCount) pop.innerHTML = emojiGridHtml();
  const btn = document.getElementById(btnId);
  if (btn) {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      toggleEmojiPop(popId);
    });
  }
  pop.addEventListener('click', e => {
    const item = e.target.closest('.af-emoji-item');
    if (item) insertEmoji(inputId, item.dataset.emoji, popId);
  });
}

// Клик мимо обёртки поля имени — закрыть все попапы эмодзи.
// Один слушатель на страницу (модуль-синглтон), а не на каждый бинд.
document.addEventListener('click', e => {
  if (e.target.closest('.af-name-wrap')) return;
  document.querySelectorAll('.af-emoji-pop:not(.hidden)')
    .forEach(p => p.classList.add('hidden'));
});
