// ANSI SGR (цвета/стили) → безопасный HTML.
// Текст предварительно экранируется (esc), затем поверх навешиваются <span style>.
// Поддержка: bold/dim/italic/underline, базовые 16 цветов, 256-палитра, truecolor (38;2;r;g;b).
import { esc } from './api.js';

// Стандартная 16-цветная палитра ANSI.
const NAMED = [
  '#000', '#a00', '#0a0', '#a50', '#00a', '#a0a', '#0aa', '#aaa',
  '#555', '#f55', '#5f5', '#ff5', '#55f', '#f5f', '#5ff', '#fff',
];

// xterm 256-палитра.
function color256(n) {
  n = Number(n);
  if (!Number.isFinite(n)) return null;
  if (n < 16) return NAMED[n];
  if (n >= 232) { const v = 8 + (n - 232) * 10; return `rgb(${v},${v},${v})`; }
  n -= 16;
  const r = Math.floor(n / 36) % 6, g = Math.floor(n / 6) % 6, b = n % 6;
  const c = v => v ? (v * 40 + 55) : 0;
  return `rgb(${c(r)},${c(g)},${c(b)})`;
}

export function ansiToHtml(input) {
  const s = String(input ?? '');
  const st = { bold: false, dim: false, italic: false, underline: false, fg: null, bg: null };
  let html = '';
  let spanOpen = false;

  const css = () => {
    const p = [];
    if (st.bold) p.push('font-weight:bold');
    if (st.dim) p.push('opacity:.55');
    if (st.italic) p.push('font-style:italic');
    if (st.underline) p.push('text-decoration:underline');
    if (st.fg) p.push('color:' + st.fg);
    if (st.bg) p.push('background:' + st.bg);
    return p.join(';');
  };
  // пересобираем оборачивающий <span> после любой смены стиля
  const reopen = () => {
    if (spanOpen) html += '</span>';
    const c = css();
    if (c) { html += '<span style="' + c + '">'; spanOpen = true; }
    else spanOpen = false;
  };

  const re = /\x1b\[([0-9;]*)m/g;
  let last = 0, m;
  while ((m = re.exec(s)) !== null) {
    html += esc(s.slice(last, m.index));   // текст до кода — экранированный
    last = re.lastIndex;
    const params = m[1] === '' ? [0] : m[1].split(';').map(Number);
    for (let k = 0; k < params.length; k++) {
      const p = params[k];
      if (p === 0) Object.assign(st, { bold: false, dim: false, italic: false, underline: false, fg: null, bg: null });
      else if (p === 1) st.bold = true;
      else if (p === 2) st.dim = true;
      else if (p === 3) st.italic = true;
      else if (p === 4) st.underline = true;
      else if (p === 22) { st.bold = false; st.dim = false; }
      else if (p === 23) st.italic = false;
      else if (p === 24) st.underline = false;
      else if (p === 39) st.fg = null;
      else if (p === 49) st.bg = null;
      else if (p >= 30 && p <= 37) st.fg = NAMED[p - 30];
      else if (p >= 90 && p <= 97) st.fg = NAMED[p - 90 + 8];
      else if (p >= 40 && p <= 47) st.bg = NAMED[p - 40];
      else if (p >= 100 && p <= 107) st.bg = NAMED[p - 100 + 8];
      else if (p === 38 || p === 48) {
        const mode = params[++k];
        let col = null;
        if (mode === 5 && params[k + 1] != null) { col = color256(params[k + 1]); k++; }
        else if (mode === 2 && params[k + 3] != null) { col = `rgb(${params[k + 1]},${params[k + 2]},${params[k + 3]})`; k += 3; }
        if (p === 38) st.fg = col; else st.bg = col;
      }
    }
    reopen();
  }
  html += esc(s.slice(last));
  if (spanOpen) html += '</span>';
  return html;
}
