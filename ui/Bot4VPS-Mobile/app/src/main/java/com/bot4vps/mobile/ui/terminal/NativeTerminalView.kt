package com.bot4vps.mobile.ui.terminal

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.text.InputType
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.BaseInputConnection
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.view.inputmethod.InputMethodManager

class NativeTerminalView(context: Context) : View(context) {
    var onInput: (String) -> Unit = {}
    val input = TerminalInput()
    fun sendInput(value: String) { onInput(input.text(value)) }
    fun hideKeyboard() {
        (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(windowToken, 0)
        clearFocus()
    }
    var onResize: (Int, Int) -> Unit = { _, _ -> }
    val buffer = TerminalBuffer()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Typeface.MONOSPACE; textSize = 12 * resources.displayMetrics.scaledDensity }
    private val palette = intArrayOf(0xff181b23.toInt(),0xffef6666.toInt(),0xff78dba9.toInt(),0xffffd479.toInt(),0xff7dafff.toInt(),0xffcda2ff.toInt(),0xff6dd6dd.toInt(),0xffe3e8ef.toInt(),0xff758195.toInt(),0xffff9696.toInt(),0xffa3f0bf.toInt(),0xffffe8a5.toInt(),0xffa0c4ff.toInt(),0xffdfbaff.toInt(),0xff9cedf3.toInt(),0xffffffff.toInt())
    private val charWidth get() = paint.measureText("M")
    private val lineHeight get() = paint.fontSpacing
    init { isFocusable = true; isFocusableInTouchMode = true; setBackgroundColor(0xff10131b.toInt()) }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        val cols = ((w - 12) / charWidth).toInt().coerceAtLeast(20)
        val rows = ((h - 12) / lineHeight).toInt().coerceAtLeast(6)
        buffer.resize(cols, rows); onResize(buffer.columns, buffer.rows)
    }
    fun append(text: String) { buffer.append(text); invalidate() }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        buffer.cells.forEachIndexed { row, cells -> cells.forEachIndexed { col, cell ->
            if (cell.char != ' ') { paint.color = palette[cell.color.coerceIn(0,15)]; canvas.drawText(cell.char.toString(),6 + col * charWidth,6 + (row + 1) * lineHeight - paint.descent(),paint) }
        } }
        paint.color = 0xff75a9ff.toInt()
        val x = 6 + buffer.x.coerceAtMost(buffer.columns - 1) * charWidth
        val y = 6 + (buffer.y + 1) * lineHeight
        canvas.drawRect(x, y - 2, x + charWidth, y, paint)
    }
    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.action == MotionEvent.ACTION_UP) {
            performClick(); requestFocus()
            (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(this, InputMethodManager.SHOW_IMPLICIT)
        }
        return true
    }
    override fun performClick(): Boolean { super.performClick(); return true }
    override fun onCheckIsTextEditor() = true
    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection {
        outAttrs.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        outAttrs.imeOptions = EditorInfo.IME_FLAG_NO_EXTRACT_UI or EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING or EditorInfo.IME_ACTION_NONE
        return object : BaseInputConnection(this, false) {
            override fun commitText(text: CharSequence?, newCursorPosition: Int): Boolean { text?.let { sendInput(it.toString()) }; return true }
            override fun deleteSurroundingText(beforeLength: Int, afterLength: Int): Boolean { repeat(beforeLength) { sendInput("\u007f") }; return true }
            override fun sendKeyEvent(event: KeyEvent): Boolean = this@NativeTerminalView.dispatchKeyEvent(event)
        }
    }
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        val key = when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> "\r"
            KeyEvent.KEYCODE_DEL -> "\u007f"
            KeyEvent.KEYCODE_TAB -> "\t"
            KeyEvent.KEYCODE_ESCAPE -> "\u001b"
            KeyEvent.KEYCODE_DPAD_UP -> "\u001b[A"
            KeyEvent.KEYCODE_DPAD_DOWN -> "\u001b[B"
            KeyEvent.KEYCODE_DPAD_RIGHT -> "\u001b[C"
            KeyEvent.KEYCODE_DPAD_LEFT -> "\u001b[D"
            else -> event.getUnicodeChar(event.metaState and KeyEvent.META_CTRL_MASK.inv()).takeIf { it != 0 }?.let { String(Character.toChars(it)) }
        }
        if (key != null) { onInput(input.text(key, hardwareCtrl = event.isCtrlPressed)); return true }
        return super.onKeyDown(keyCode, event)
    }
}
