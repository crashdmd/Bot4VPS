package com.bot4vps.mobile.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.bot4vps.mobile.data.model.ServerSummary
import com.bot4vps.mobile.ui.servers.ServerListCard
import com.bot4vps.mobile.ui.theme.Bot4VpsTheme

@Preview(name = "Серверы · тёмная", widthDp = 360)
@Composable
private fun DarkServerCardsPreview() { ServerCardsPreview(dark = true) }

@Preview(name = "Серверы · светлая", widthDp = 360)
@Composable
private fun LightServerCardsPreview() { ServerCardsPreview(dark = false) }

@Preview(name = "Серверы · крупный текст", widthDp = 320, fontScale = 1.3f)
@Composable
private fun LargeTextServerCardsPreview() { ServerCardsPreview(dark = true) }

@Composable
private fun ServerCardsPreview(dark: Boolean) {
    Bot4VpsTheme(darkTheme = dark) {
        PanelBackground {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Серверы")
                ServerListCard(ServerSummary("1", name = "Основной сервер", host = "192.0.2.10", online = true)) {}
                ServerListCard(ServerSummary("2", name = "Сервер с длинным названием", host = "2001:db8::10", online = true, sshError = "Нет ключа")) {}
                ServerListCard(ServerSummary("3", name = "Резервный сервер", online = false)) {}
            }
        }
    }
}
