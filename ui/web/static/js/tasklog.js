import { ansiToHtml } from './ansi.js';

// Накопленный журнал окна живёт при сворачивании. Нумерация строк API
// позволяет дописывать снимки без повторов, включая одинаковые строки.
export class TaskLogBuffer {
  constructor() { this.lines = []; this.next = 0; this.size = 0; this.truncated = false; }
  update(task) {
    const lines = Array.isArray(task.output_lines) ? task.output_lines : [];
    const start = Number.isInteger(task.output_line_start) ? task.output_line_start : 0;
    if (start > this.next) this.truncated = true;
    for (let index = Math.max(0, this.next - start); index < lines.length; index++) {
      const line = String(lines[index]);
      this.lines.push(line); this.size += line.length + 1;
    }
    this.next = Math.max(this.next, start + lines.length);
    // Ограничение памяти вкладки; сервер также хранит ограниченный журнал.
    while (this.size > 4 * 1024 * 1024 && this.lines.length) {
      this.size -= this.lines.shift().length + 1; this.truncated = true;
    }
  }
  html(task) {
    let body = this.lines.length ? this.lines.map(ansiToHtml).join('\n')
      : ansiToHtml(task.result?.output || task.result?.error || task.error || '(нет вывода)');
    if (this.lines.length && !task.success && task.result?.output
        && String(task.result.output).trim() !== this.lines.join('\n').trim()) {
      body += `\n${'─'.repeat(36)}\n${ansiToHtml(String(task.result.output).trim())}`;
    }
    return body;
  }
}

export function taskDuration(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const s = String(value % 60).padStart(2, '0');
  const m = String(Math.floor(value / 60) % 60).padStart(2, '0');
  return value >= 3600 ? `${Math.floor(value / 3600)}:${m}:${s}` : `${m}:${s}`;
}
