package com.bot4vps.mobile.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// Translucent web surfaces are composited over the page background.
data class PanelPalette(val gradientEnd: Color, val field: Color, val warning: Color)
val LocalPanelPalette = staticCompositionLocalOf {
    PanelPalette(Color(0xFF151D2E), Color(0xFF091324), Warning)
}

private val DarkScheme = darkColorScheme(
    primary = Primary, onPrimary = Color.White,
    primaryContainer = Color(0xFF172B50), onPrimaryContainer = Primary,
    secondary = Success, onSecondary = Color(0xFF0A1628),
    secondaryContainer = Color(0xFF14332D), onSecondaryContainer = Success,
    tertiary = Info, background = Color(0xFF0A1628), onBackground = Color(0xFFE8EDF5),
    surface = Color(0xFF131B2A), onSurface = Color(0xFFE8EDF5),
    surfaceVariant = Color(0xFF182235), onSurfaceVariant = Color(0xFF8B92A0),
    surfaceContainer = Color(0xFF182235), surfaceContainerHigh = Color(0xFF202A3B),
    surfaceContainerHighest = Color(0xFF182235), surfaceTint = Color.Transparent,
    outline = Color(0xFF354052), outlineVariant = Color(0xFF2C3647),
    error = Error, onError = Color.White, errorContainer = Color(0xFF332135), onErrorContainer = Error
)
private val LightScheme = lightColorScheme(
    primary = Primary, onPrimary = Color(0xFF27519C),
    primaryContainer = Color(0xFFD8E7FB), onPrimaryContainer = Color(0xFF27519C),
    secondary = Color(0xFF10B981), onSecondary = Color.White,
    secondaryContainer = Color(0xFFCAE5DF), onSecondaryContainer = Color(0xFF087B58),
    tertiary = Info, background = Color(0xFFDEE4EC), onBackground = Color(0xFF2A3646),
    surface = Color(0xFFD5DDE7), onSurface = Color(0xFF2A3646),
    surfaceVariant = Color(0xFFDBE3ED), onSurfaceVariant = Color(0xFF5D6D7F),
    surfaceContainer = Color(0xFFDBE3ED), surfaceContainerHigh = Color(0xFFE2EAF3),
    surfaceContainerHighest = Color(0xFFDBE3ED), surfaceTint = Color.Transparent,
    outline = Color(0xFFABB8C8), outlineVariant = Color(0xFFB9C5D3),
    error = Color(0xFFEF4444), onError = Color.White,
    errorContainer = Color(0xFFEAD3D9), onErrorContainer = Color(0xFFAF2836)
)
private val GlassScheme = DarkScheme.copy(
    primary = Color(0xFF3FB6F6), onPrimary = Color.White,
    primaryContainer = Color(0xFF153D59), onPrimaryContainer = Color(0xFF9AD0FF),
    background = Color(0xFF0F233B), onBackground = Color(0xFFEAF4FC),
    surface = Color(0xFF14304E), onSurface = Color(0xFFEAF4FC),
    surfaceContainer = Color(0xFF173853), surfaceContainerHigh = Color(0xFF1D4461),
    surfaceContainerHighest = Color(0xFF1D4461), surfaceVariant = Color(0xFF173853),
    onSurfaceVariant = Color(0xFFA3C0D6), outline = Color(0xFF395D7D), outlineVariant = Color(0xFF2E506D)
)
private val PanelShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp), small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(12.dp), large = RoundedCornerShape(16.dp), extraLarge = RoundedCornerShape(16.dp)
)

@Composable
fun Bot4VpsTheme(darkTheme: Boolean = true, blueTheme: Boolean = false, content: @Composable () -> Unit) {
    val palette = if (blueTheme) PanelPalette(Color(0xFF16425D), Color(0xFF0A1A2C), Warning)
        else if (darkTheme) PanelPalette(Color(0xFF151D2E), Color(0xFF091324), Warning)
        else PanelPalette(Color(0xFFD0D9E3), Color(0xFFCED7E2), Color(0xFFF59E0B))
    CompositionLocalProvider(LocalPanelPalette provides palette) {
        MaterialTheme(colorScheme = if (blueTheme) GlassScheme else if (darkTheme) DarkScheme else LightScheme,
            typography = AppTypography, shapes = PanelShapes, content = content)
    }
}
