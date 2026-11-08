package com.bot4vps.mobile.ui.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Backspace
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bot4vps.mobile.data.model.LockPin

/** PIN never enters an editable text field or the system IME. */
@Composable
fun PinEntryScreen(
    title: String,
    prompt: String,
    digits: Int,
    onDigit: (Int) -> Unit,
    onDelete: () -> Unit,
    onBack: () -> Unit,
    enabled: Boolean,
    busy: Boolean = false,
    error: String? = null,
    subtitle: String? = null,
    firstPinComplete: Boolean = false,
    onBiometric: (() -> Unit)? = null,
) {
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(Unit) { keyboard?.hide() }
    DisposableEffect(Unit) { onDispose { keyboard?.hide() } }
    Surface(color = MaterialTheme.colorScheme.background, modifier = Modifier.fillMaxSize()) {
        BoxWithConstraints(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 24.dp, vertical = 8.dp)) {
            val compact = maxHeight < 480.dp && maxWidth > maxHeight
            val bottomGap = if (maxHeight >= 480.dp) 80.dp else 32.dp
            val keyHeight = (maxHeight * if (compact) 0.16f else 0.115f).coerceIn(48.dp, 76.dp)
            Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(Modifier.fillMaxWidth().height(56.dp), contentAlignment = Alignment.Center) {
                    Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 48.dp))
                    IconButton(onClick = onBack, enabled = !busy, modifier = Modifier.align(Alignment.CenterStart)) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад", tint = MaterialTheme.colorScheme.primary)
                    }
                }
                if (compact) {
                    Row(Modifier.weight(1f).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        PinPrompt(prompt, digits, firstPinComplete, subtitle, busy, error, Modifier.weight(1f).padding(end = 16.dp), compact = true)
                        PinKeypad(onDigit, onDelete, enabled, onBiometric, !busy, keyHeight, Modifier.weight(1f))
                    }
                } else {
                    PinPrompt(prompt, digits, firstPinComplete, subtitle, busy, error, Modifier.weight(1f).fillMaxWidth())
                    PinKeypad(onDigit, onDelete, enabled, onBiometric, !busy, keyHeight,
                        Modifier.widthIn(max = 420.dp).fillMaxWidth())
                    Spacer(Modifier.height(bottomGap))
                }
            }
        }
    }
}

@Composable
private fun PinPrompt(prompt: String, digits: Int, firstPinComplete: Boolean, subtitle: String?, busy: Boolean, error: String?, modifier: Modifier, compact: Boolean = false) {
    Box(modifier, contentAlignment = Alignment.Center) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(prompt, style = if (compact) MaterialTheme.typography.titleLarge else MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
        subtitle?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        }
        Spacer(Modifier.height(if (compact) 16.dp else 32.dp))
        if (firstPinComplete) { PinDots(LockPin.LENGTH); Spacer(Modifier.height(if (compact) 12.dp else 24.dp)) }
        PinDots(digits)
        Box(Modifier.fillMaxWidth().heightIn(min = if (compact) 40.dp else 68.dp).padding(top = 16.dp), contentAlignment = Alignment.TopCenter) {
            if (busy) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
            else error?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center) }
        }
    }
    }
}

@Composable
private fun PinDots(digits: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(28.dp),
        modifier = Modifier.clearAndSetSemantics { contentDescription = "Введено $digits из ${LockPin.LENGTH} цифр" }) {
        repeat(LockPin.LENGTH) { index ->
            Box(Modifier.size(12.dp).background(if (index < digits) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant, CircleShape))
        }
    }
}

@Composable
private fun PinKeypad(onDigit: (Int) -> Unit, onDelete: () -> Unit, enabled: Boolean, onBiometric: (() -> Unit)?, biometricEnabled: Boolean, keyHeight: androidx.compose.ui.unit.Dp, modifier: Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (row in 0..2) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (column in 1..3) {
                val digit = row * 3 + column
                PinDigit(digit, onDigit, enabled, Modifier.weight(1f).height(keyHeight))
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (onBiometric != null) IconButton(onClick = onBiometric, enabled = biometricEnabled, modifier = Modifier.weight(1f).height(keyHeight)) {
                Icon(Icons.Default.Fingerprint, "Войти по биометрии", Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
            } else Spacer(Modifier.weight(1f))
            PinDigit(0, onDigit, enabled, Modifier.weight(1f).height(keyHeight))
            IconButton(onClick = onDelete, enabled = enabled, modifier = Modifier.weight(1f).height(keyHeight)) {
                Icon(Icons.AutoMirrored.Outlined.Backspace, "Удалить последнюю цифру", Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
            }
        }
    }
}

@Composable
private fun PinDigit(digit: Int, onDigit: (Int) -> Unit, enabled: Boolean, modifier: Modifier) {
    TextButton(onClick = { onDigit(digit) }, enabled = enabled, modifier = modifier, shape = CircleShape, contentPadding = PaddingValues(0.dp),
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onBackground)) {
        Text(digit.toString(), fontSize = 32.sp, fontWeight = FontWeight.Medium)
    }
}
