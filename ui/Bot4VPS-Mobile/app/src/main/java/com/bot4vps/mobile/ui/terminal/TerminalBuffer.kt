package com.bot4vps.mobile.ui.terminal

/** Small VT terminal grid shared by the native renderer and unit tests. */
class TerminalBuffer(var columns: Int = 80, var rows: Int = 24) {
    data class Cell(var char: Char = ' ', var color: Int = 7)
    var cells = Array(rows) { Array(columns) { Cell() } }; private set
    var x = 0; private set
    var y = 0; private set
    private var color = 7
    private var mode = 0
    private val escape = StringBuilder()
    private var savedX = 0
    private var savedY = 0
    private var top = 0
    private var bottom = rows - 1

    fun resize(cols: Int, count: Int) {
        val old = cells
        columns = cols.coerceIn(20, 240); rows = count.coerceIn(6, 100)
        cells = Array(rows) { row -> Array(columns) { col -> old.getOrNull(row)?.getOrNull(col)?.copy() ?: Cell() } }
        x = x.coerceAtMost(columns - 1); y = y.coerceAtMost(rows - 1)
        top = 0; bottom = rows - 1
    }

    fun append(text: String) {
        text.forEach { ch ->
            when (mode) {
                1 -> when (ch) {
                    '[' -> { mode = 2; escape.clear() }
                    ']' -> mode = 3
                    '7' -> { savedX = x; savedY = y; mode = 0 }
                    '8' -> { x = savedX.coerceIn(0, columns - 1); y = savedY.coerceIn(0, rows - 1); mode = 0 }
                    'c' -> { clear(); mode = 0 }
                    else -> mode = 0
                }
                2 -> if (ch in '@'..'~') { csi(ch, escape.toString()); mode = 0 } else if (escape.length < 128) escape.append(ch) else mode = 0
                3 -> if (ch == '\u0007') mode = 0 else if (ch == '\u001b') mode = 4
                4 -> { mode = if (ch == '\\') 0 else 3 }
                else -> when (ch) {
                    '\u001b' -> mode = 1
                    '\r' -> x = 0
                    '\n' -> newline()
                    '\b' -> x = (x - 1).coerceAtLeast(0)
                    '\t' -> x = ((x / 8 + 1) * 8).coerceAtMost(columns - 1)
                    else -> if (ch >= ' ' && ch != '\u007f') {
                        if (x >= columns) { x = 0; newline() }
                        cells[y][x] = Cell(ch, color); x++
                    }
                }
            }
        }
    }

    private fun newline() {
        if (y == bottom) {
            for (row in top until bottom) cells[row] = cells[row + 1]
            cells[bottom] = Array(columns) { Cell() }
        } else y = (y + 1).coerceAtMost(rows - 1)
    }

    private fun clear() { cells = Array(rows) { Array(columns) { Cell() } }; x = 0; y = 0; color = 7 }

    private fun csi(command: Char, raw: String) {
        val privateMode = raw.startsWith('?')
        val args = raw.removePrefix("?").split(';').map { it.toIntOrNull() ?: 0 }
        fun n(index: Int = 0, default: Int = 1) = args.getOrNull(index)?.takeIf { it > 0 } ?: default
        when (command) {
            'A' -> y = (y - n()).coerceAtLeast(0)
            'B' -> y = (y + n()).coerceAtMost(rows - 1)
            'C' -> x = (x + n()).coerceAtMost(columns - 1)
            'D' -> x = (x - n()).coerceAtLeast(0)
            'E' -> { x = 0; y = (y + n()).coerceAtMost(rows - 1) }
            'F' -> { x = 0; y = (y - n()).coerceAtLeast(0) }
            'G' -> x = (n() - 1).coerceIn(0, columns - 1)
            'H', 'f' -> { y = (n() - 1).coerceIn(0, rows - 1); x = (n(1) - 1).coerceIn(0, columns - 1) }
            'J' -> when (args.firstOrNull()) {
                2, 3 -> cells = Array(rows) { Array(columns) { Cell() } }
                1 -> { for (r in 0 until y) cells[r] = Array(columns) { Cell() }; for (c in 0..x.coerceAtMost(columns - 1)) cells[y][c] = Cell() }
                else -> { for (c in x.coerceAtMost(columns - 1) until columns) cells[y][c] = Cell(); for (r in y + 1 until rows) cells[r] = Array(columns) { Cell() } }
            }
            'K' -> when (args.firstOrNull()) {
                2 -> cells[y] = Array(columns) { Cell() }
                1 -> for (c in 0..x.coerceAtMost(columns - 1)) cells[y][c] = Cell()
                else -> for (c in x.coerceAtMost(columns - 1) until columns) cells[y][c] = Cell()
            }
            'm' -> args.forEach { if (it == 0 || it == 39) color = 7 else if (it in 30..37) color = it - 30 else if (it in 90..97) color = it - 90 + 8 }
            's' -> { savedX = x; savedY = y }
            'u' -> { x = savedX.coerceIn(0, columns - 1); y = savedY.coerceIn(0, rows - 1) }
            'r' -> { top = (n() - 1).coerceIn(0, rows - 2); bottom = (n(1, rows) - 1).coerceIn(top + 1, rows - 1); x = 0; y = top }
            'h', 'l' -> if (privateMode && args.firstOrNull() in listOf(47, 1047, 1049)) clear()
        }
    }

    fun lines(): List<String> = cells.map { row -> row.joinToString("") { it.char.toString() }.trimEnd() }
}
