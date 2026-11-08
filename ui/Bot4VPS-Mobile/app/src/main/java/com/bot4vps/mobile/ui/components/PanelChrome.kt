package com.bot4vps.mobile.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Close
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.ui.theme.LocalPanelPalette

/** Native equivalents of the shared mobile web panel controls. */
@Composable
fun PanelBackground(content: @Composable BoxScope.() -> Unit) {
    Box(Modifier.fillMaxSize().background(Brush.linearGradient(
        listOf(MaterialTheme.colorScheme.background, LocalPanelPalette.current.gradientEnd))), content = content)
}

@Composable
fun PanelScaffold(
    modifier: Modifier = Modifier,
    topBar: @Composable () -> Unit = {},
    bottomBar: @Composable () -> Unit = {},
    snackbarHost: @Composable () -> Unit = {},
    content: @Composable (PaddingValues) -> Unit
) {
    PanelBackground {
        Scaffold(modifier = modifier, containerColor = Color.Transparent,
            topBar = topBar, bottomBar = bottomBar, snackbarHost = snackbarHost, content = content)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PanelTopBar(
    title: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    navigationIcon: @Composable () -> Unit = {},
    actions: @Composable RowScope.() -> Unit = {}
) {
    TopAppBar(title = { ProvideTextStyle(MaterialTheme.typography.headlineMedium) { title() } }, modifier = modifier, navigationIcon = navigationIcon, actions = actions,
        expandedHeight = 56.dp,
        colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent,
            titleContentColor = MaterialTheme.colorScheme.onBackground))
}

@Composable
fun PanelSurfaceCard(
    modifier: Modifier = Modifier,
    shape: Shape = MaterialTheme.shapes.medium,
    colors: CardColors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    content: @Composable ColumnScope.() -> Unit
) {
    Card(modifier = modifier, shape = shape, colors = colors,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp), content = content)
}

@Composable
fun PanelSurfaceCard(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    shape: Shape = MaterialTheme.shapes.medium,
    colors: CardColors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    content: @Composable ColumnScope.() -> Unit
) {
    Card(onClick = onClick, modifier = modifier, enabled = enabled, shape = shape, colors = colors,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp), content = content)
}

@Composable
fun PanelButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    shape: Shape = RoundedCornerShape(8.dp),
    colors: ButtonColors = ButtonDefaults.buttonColors(
        containerColor = if (MaterialTheme.colorScheme.background.luminance() > .5f)
            MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.primary),
    content: @Composable RowScope.() -> Unit
) {
    Button(onClick = onClick, modifier = modifier, enabled = enabled, shape = shape, colors = colors,
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, content = content)
    }
}

@Composable
fun PanelSecondaryButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    shape: Shape = RoundedCornerShape(8.dp),
    colors: ButtonColors = ButtonDefaults.outlinedButtonColors(
        containerColor = MaterialTheme.colorScheme.surfaceContainer,
        contentColor = MaterialTheme.colorScheme.onSurface),
    content: @Composable RowScope.() -> Unit
) {
    OutlinedButton(onClick = onClick, modifier = modifier, enabled = enabled, shape = shape, colors = colors,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, content = content)
    }
}

@Composable
fun PanelTab(
    selected: Boolean,
    onClick: () -> Unit,
    label: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    FilterChip(selected = selected, onClick = onClick, label = label, modifier = modifier,
        enabled = enabled, shape = RoundedCornerShape(8.dp),
        border = FilterChipDefaults.filterChipBorder(enabled = enabled, selected = selected,
            borderColor = MaterialTheme.colorScheme.outlineVariant, selectedBorderColor = MaterialTheme.colorScheme.primary),
        colors = FilterChipDefaults.filterChipColors(
            containerColor = MaterialTheme.colorScheme.surface,
            labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
            selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
            selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer))
}

@Composable
fun PanelTextField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    readOnly: Boolean = false,
    textStyle: TextStyle = MaterialTheme.typography.bodyMedium,
    label: @Composable (() -> Unit)? = null,
    placeholder: @Composable (() -> Unit)? = null,
    leadingIcon: @Composable (() -> Unit)? = null,
    trailingIcon: @Composable (() -> Unit)? = null,
    supportingText: @Composable (() -> Unit)? = null,
    isError: Boolean = false,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
    singleLine: Boolean = false,
    maxLines: Int = if (singleLine) 1 else Int.MAX_VALUE,
    minLines: Int = 1,
    interactionSource: MutableInteractionSource? = null,
    shape: Shape = RoundedCornerShape(8.dp)
) {
    val field = LocalPanelPalette.current.field
    OutlinedTextField(value = value, onValueChange = onValueChange, modifier = modifier,
        enabled = enabled, readOnly = readOnly, textStyle = textStyle, label = label,
        placeholder = placeholder, leadingIcon = leadingIcon, trailingIcon = trailingIcon,
        supportingText = supportingText, isError = isError, visualTransformation = visualTransformation,
        keyboardOptions = keyboardOptions, keyboardActions = keyboardActions, singleLine = singleLine,
        maxLines = maxLines, minLines = minLines, interactionSource = interactionSource, shape = shape,
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = field, unfocusedContainerColor = field,
            disabledContainerColor = field.copy(alpha = .5f), errorContainerColor = field,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
            focusedBorderColor = MaterialTheme.colorScheme.primary))
}

@Composable
fun PanelSearchField(value: String, onValueChange: (String) -> Unit, modifier: Modifier = Modifier, placeholder: String = "Поиск") {
    val shape = RoundedCornerShape(8.dp)
    BasicTextField(value, onValueChange, modifier = modifier.height(40.dp)
        .background(LocalPanelPalette.current.field, shape).border(1.dp, MaterialTheme.colorScheme.outline, shape),
        singleLine = true, textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary), decorationBox = { input ->
            Row(Modifier.fillMaxSize().padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Default.Search, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Box(Modifier.weight(1f)) {
                    if(value.isEmpty()) Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    input()
                }
                if(value.isNotEmpty()) IconButton(onClick = { onValueChange("") }, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Default.Close, "Очистить поиск", Modifier.size(18.dp))
                }
            }
        })
}
