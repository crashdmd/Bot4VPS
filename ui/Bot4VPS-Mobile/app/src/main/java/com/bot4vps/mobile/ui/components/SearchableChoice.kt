package com.bot4vps.mobile.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchableChoice(label: String, selected: String?, options: List<Pair<String, String>>, onSelect: (String?) -> Unit,
    modifier: Modifier = Modifier, allowEmpty: Boolean = false, emptyLabel: String = "Все серверы", enabled: Boolean = true, searchHint: String = "Найти по имени или адресу") {
    var expanded by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    PanelSecondaryButton(onClick = { query = ""; expanded = true }, enabled = enabled, modifier = modifier.fillMaxWidth()) {
        Text("$label: ${options.find { it.first == selected }?.second ?: selected ?: emptyLabel}", Modifier.weight(1f))
        Icon(Icons.Default.ExpandMore, "Выбрать")
    }
    if (expanded) ModalBottomSheet(onDismissRequest = { expanded = false }) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 24.dp)) {
            Text(label, style = MaterialTheme.typography.titleLarge)
            PanelSearchField(query, { query = it }, placeholder = searchHint, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
            val filtered = options.filter { query.isBlank() || it.second.contains(query.trim(), true) || it.first.contains(query.trim(), true) }
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                if (allowEmpty) item { TextButton(onClick = { onSelect(null); expanded = false }, modifier = Modifier.fillMaxWidth()) { Text(emptyLabel) } }
                if (filtered.isEmpty()) item { Text("Ничего не найдено", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(filtered, key = { it.first }) { (id, title) ->
                    TextButton(onClick = { onSelect(id); expanded = false }, modifier = Modifier.fillMaxWidth()) {
                        Text(title, Modifier.weight(1f))
                        if (id == selected) Icon(Icons.Default.Check, "Выбран")
                    }
                }
            }
        }
    }
}
