package com.bot4vps.mobile.ui.terminal

/** A Ctrl tap modifies the next text key from either the IME or hardware. */
class TerminalInput {
    var ctrl = false
        private set
    var onCtrlChanged: (Boolean) -> Unit = {}

    fun toggleCtrl() { ctrl = !ctrl; onCtrlChanged(ctrl) }
    fun text(value: String, hardwareCtrl: Boolean = false): String {
        if (value.isEmpty()) return value
        val control = ctrl || hardwareCtrl
        if (ctrl) { ctrl = false; onCtrlChanged(false) }
        if (!control) return value
        val first = value.first().uppercaseChar()
        val code = when {
            first in '@'..'_' -> first.code and 31
            first == ' ' -> 0
            first == '?' -> 127
            else -> return value
        }
        return code.toChar() + value.drop(1)
    }
}
