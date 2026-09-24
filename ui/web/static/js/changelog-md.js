// Разметка описания версии (чанджлог) для модалок обновления и отката.
// Поднабор ограничен тем, что встречается в core/update/changelog.md:
// заголовки #..####, цитата >, списки - (в том числе вложенные),
// разделитель ---, **жирный** и `код`. Полноценный markdown здесь не нужен:
// файл закрыт для правок вне релиза, а лишняя зависимость в поставке панели
// ни к чему.
import { esc } from './api.js';

/** Разметка внутри строки: **жирный** и `код`.
 *  Работает по УЖЕ экранированному тексту — угловые скобки к этому моменту
 *  заменены на сущности, поэтому подстановка не открывает ничего заново. */
function inline(escaped) {
  return escaped
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

/** Секция changelog.md → HTML.
 *
 *  Порядок обязателен: сначала esc(), потом теги. Описание версии приходит
 *  из внешнего источника (ветка main и артефакт обновления), поэтому без
 *  экранирования чужой текст стал бы разметкой панели. */
export function changelogHtml(md) {
  const out = [];
  let items = null; // текущий список: [{ text, sub: [...] }]
  let quote = null; // накопленные строки цитаты

  const renderList = list => '<ul>' + list.map(it =>
    `<li>${it.text}${it.sub.length ? renderList(it.sub) : ''}</li>`
  ).join('') + '</ul>';
  const flushQuote = () => {
    if (!quote) return;
    out.push(`<blockquote>${quote.map(s => `<p>${s}</p>`).join('')}</blockquote>`);
    quote = null;
  };
  const flushList = () => {
    if (!items) return;
    out.push(renderList(items));
    items = null;
  };
  const flush = () => { flushQuote(); flushList(); };

  for (const raw of String(md ?? '').split('\n')) {
    const line = raw.trim();
    if (!line) { flush(); continue; }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      const level = heading[1].length;
      out.push(`<h${level}>${inline(esc(heading[2]))}</h${level}>`);
      continue;
    }
    if (/^-{3,}$/.test(line)) { flush(); out.push('<hr>'); continue; }

    const quoted = /^>\s?(.*)$/.exec(line);
    if (quoted) {
      flushList();
      (quote = quote || []).push(inline(esc(quoted[1])));
      continue;
    }

    const item = /^-\s+(.*)$/.exec(line);
    if (item) {
      flushQuote();
      // Вложенность — по отступу в исходной строке: trim() его съедает,
      // и без отдельной проверки пункт вложенного списка выглядел бы
      // обычным пунктом верхнего уровня.
      const nested = /^\s{2,}-/.test(raw);
      const entry = { text: inline(esc(item[1])), sub: [] };
      if (nested && items && items.length) items[items.length - 1].sub.push(entry);
      else (items = items || []).push(entry);
      continue;
    }

    flush();
    out.push(`<p>${inline(esc(line))}</p>`);
  }
  flush();
  return out.join('');
}

/** Тело модалки с описанием версии: разметка + прежняя прокрутка.
 *  maxHeight — CSS-значение прежнего <pre> (50vh / 60vh), чтобы высота
 *  окна не менялась. */
export function changelogBody(md, maxHeight) {
  return `<div class="changelog-doc" style="max-height:${maxHeight};overflow:auto">` +
    changelogHtml(md) + '</div>';
}
