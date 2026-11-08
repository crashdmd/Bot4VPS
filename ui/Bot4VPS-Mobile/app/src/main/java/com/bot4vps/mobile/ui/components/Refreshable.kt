package com.bot4vps.mobile.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.*
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import kotlinx.coroutines.flow.collect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

private val LocalRefreshProgress = staticCompositionLocalOf<() -> Float> { { 0f } }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Refreshable(refreshing: Boolean, onRefresh: () -> Unit, modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit) {
    val state = rememberPullToRefreshState()
    var touching by remember { mutableStateOf(false) }
    var eligible by remember { mutableStateOf(false) }
    var dragged by remember { mutableStateOf(false) }
    var pulled by remember { mutableStateOf(false) }
    val currentRefreshing = rememberUpdatedState(refreshing)
    LaunchedEffect(state) {
        snapshotFlow { Triple(touching && dragged && eligible, currentRefreshing.value, state.distanceFraction) }.collect { (finger, busy, distance) ->
            if (finger && !busy && distance > 0f) pulled = true
            if (!finger && !busy && distance <= 0f) pulled = false
        }
    }
    // Material also moves its indicator on initial/programmatic loads. Only a
    // finger-driven pull may move the content; keep its smooth return on release.
    val progress = remember(state) { {
        if (pulled || touching && dragged && eligible && !currentRefreshing.value) state.distanceFraction.coerceIn(0f, 1f) else 0f
    } }
    PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh,
        state = state, modifier = modifier.clipToBounds().pointerInput(Unit) {
            awaitEachGesture {
                awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                touching = true
                eligible = !currentRefreshing.value && state.distanceFraction <= 0f
                dragged = false
                try {
                    do {
                        val event = awaitPointerEvent(PointerEventPass.Final)
                        if(event.changes.any { it.position.y > it.previousPosition.y }) dragged = true
                    }
                    while (event.changes.any { it.pressed })
                } finally { touching = false }
            }
        }) {
        CompositionLocalProvider(LocalRefreshProgress provides progress) {
            Box(Modifier.fillMaxSize().graphicsLayer {
                translationY = 48.dp.toPx() * progress()
            }, content = content)
        }
    }
}

/** Open the gaps between blocks without scaling text or restarting list items. */
@Composable
fun refreshArrangement(baseSpacing: Dp): Arrangement.Vertical {
    val progress = LocalRefreshProgress.current
    return remember(baseSpacing, progress) {
        object : Arrangement.Vertical {
            // Read during layout: dragging only remeasures, without recomposing the list.
            override val spacing: Dp get() = baseSpacing + 8.dp * progress()
            override fun Density.arrange(totalSize: Int, sizes: IntArray, outPositions: IntArray) {
                with(Arrangement.spacedBy(spacing)) { arrange(totalSize, sizes, outPositions) }
            }
        }
    }
}
