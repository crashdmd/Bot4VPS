package com.bot4vps.mobile.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.runtime.Composable
import androidx.compose.material3.MaterialTheme

// Bot4VPS Web UI palette (dark theme based on #0a1628)

val Background: Color
    @Composable get() = MaterialTheme.colorScheme.background
val Surface: Color
    @Composable get() = MaterialTheme.colorScheme.surface
val SurfaceVariant: Color
    @Composable get() = MaterialTheme.colorScheme.surfaceVariant
val SurfaceElevated: Color
    @Composable get() = MaterialTheme.colorScheme.surfaceContainerHigh

val Primary = Color(0xFF4A7CFF)
val PrimaryVariant = Color(0xFF5D8BFF)
val Secondary = Color(0xFF3DD68C)
val SecondaryVariant = Color(0xFF10B981)

val OnBackground: Color
    @Composable get() = MaterialTheme.colorScheme.onBackground
val OnSurface: Color
    @Composable get() = MaterialTheme.colorScheme.onSurface
val OnSurfaceVariant: Color
    @Composable get() = MaterialTheme.colorScheme.onSurfaceVariant
val TextDim: Color
    @Composable get() = MaterialTheme.colorScheme.onSurfaceVariant

val Outline: Color
    @Composable get() = MaterialTheme.colorScheme.outline
val OutlineVariant: Color
    @Composable get() = MaterialTheme.colorScheme.outlineVariant

val Success = Color(0xFF3DD68C)
val Warning = Color(0xFFFFC542)
val Error = Color(0xFFFF5C7C)
val Info = Primary

val StatusOnline = Success
val StatusOffline = Error
val StatusAuthError = Warning
val StatusUnknown = Color(0xFF6B7280)

val CardBackground: Color
    @Composable get() = MaterialTheme.colorScheme.surfaceContainer
val CardBorder: Color
    @Composable get() = MaterialTheme.colorScheme.outlineVariant
