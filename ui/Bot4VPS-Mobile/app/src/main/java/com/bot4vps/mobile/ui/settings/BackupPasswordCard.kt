package com.bot4vps.mobile.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bot4vps.mobile.data.api.*
import com.bot4vps.mobile.data.model.*
import com.bot4vps.mobile.data.repository.checkedObject
import com.bot4vps.mobile.ui.components.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import javax.inject.Inject

@HiltViewModel
class BackupPasswordViewModel @Inject constructor(private val panel: NativePanelClient) : ViewModel() {
    var status by mutableStateOf<JsonObject?>(null); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    init { refresh() }
    fun refresh() {
        if(busy) return
        viewModelScope.launch {
            busy=true
            try { status=panel.checkedObject("GET","/api/settings/backup-password") }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { error=errorText(e) }
            finally { busy=false }
        }
    }
    fun save(password: String, current: String, onSaved: () -> Unit) {
        if(busy) return
        busy=true; error=null; notice=null
        viewModelScope.launch {
            try {
                status=panel.checkedObject("POST","/api/settings/backup-password",buildJsonObject {
                    put("password",password); if(status?.flag("configured")==true) put("current_password",current)
                }).let { JsonObject(status.orEmpty()+it) }
                notice=if(password.isEmpty()) "Сохранённый пароль удалён" else "Пароль сохранён"
                onSaved()
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { error=errorText(e) }
            finally { busy=false }
        }
    }
}

@Composable
fun BackupPasswordCard(onOperation: (String) -> Unit, onChanged: () -> Unit = {}, vm: BackupPasswordViewModel = hiltViewModel()) {
    var edit by remember { mutableStateOf(false) }
    var remove by remember { mutableStateOf(false) }
    val configured=vm.status?.flag("configured")==true
    val available=vm.status?.flag("masterkey_available")==true
    LaunchedEffect(vm) { vm.refresh() }
    if(edit || remove) {
        var password by remember { mutableStateOf("") }
        var repeat by remember { mutableStateOf("") }
        var current by remember { mutableStateOf("") }
        AlertDialog(onDismissRequest={ if(!vm.busy) { edit=false; remove=false } },title={ Text(if(remove) "Удалить сохранённый пароль?" else if(configured) "Изменить пароль архивов" else "Пароль резервных копий") },
            text={ Column(Modifier.verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                Text(if(remove) "Новые копии не смогут использовать этот пароль. Для существующих архивов он всё ещё понадобится." else "Старые архивы сохраняют прежний пароль. Новый пароль используется для следующих копий.",style=MaterialTheme.typography.bodySmall)
                if(configured) PanelTextField(current,{ current=it },label={ Text("Текущий пароль") },singleLine=true,visualTransformation=PasswordVisualTransformation(),enabled=!vm.busy,modifier=Modifier.fillMaxWidth())
                if(!remove) {
                    PanelTextField(password,{ password=it },label={ Text("Новый пароль") },singleLine=true,visualTransformation=PasswordVisualTransformation(),enabled=!vm.busy,modifier=Modifier.fillMaxWidth())
                    PanelTextField(repeat,{ repeat=it },label={ Text("Повторите пароль") },singleLine=true,visualTransformation=PasswordVisualTransformation(),enabled=!vm.busy,modifier=Modifier.fillMaxWidth())
                }
                vm.error?.let { Text(it,color=MaterialTheme.colorScheme.error) }
            } },confirmButton={ TextButton(onClick={ vm.save(if(remove) "" else password,current) { edit=false; remove=false; onChanged() } },enabled=!vm.busy && (!configured || current.isNotEmpty()) && (remove || password.isNotEmpty() && password.length<=256 && password==repeat)) { Text(if(remove) "Удалить пароль" else "Сохранить") } },
            dismissButton={ TextButton(onClick={ edit=false; remove=false },enabled=!vm.busy) { Text("Отмена") } })
    }
    SettingsCard("Пароль резервных копий","Общий пароль для зашифрованных архивов панели и серверов") {
        SettingRow("Сохранённый пароль",if(vm.status==null) "Загрузка состояния" else if(configured) "Настроен" else "Не задан") {
            PanelSecondaryButton(onClick={ edit=true },enabled=available && !vm.busy) { Text(if(configured) "Изменить" else "Задать") }
        }
        Text("Пароль хранится на панели под защитой мастер-ключа. Включение шифрования выбирается отдельно для каждой цели копирования.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        if(vm.status!=null && !available) Text("Сначала восстановите мастер-ключ в настройках безопасности.",color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodySmall)
        if(configured) SettingsCategoryCard("Действия с паролем","Восстановление доступа и удаление сохранённого пароля") {
            PanelSecondaryButton(onClick={ onOperation("POST /api/settings/backup-password/forgot") },enabled=!vm.busy,modifier=Modifier.fillMaxWidth()) { Text("Забыли пароль?") }
            TextButton(onClick={ remove=true },enabled=available && !vm.busy) { Text("Удалить сохранённый пароль",color=MaterialTheme.colorScheme.error) }
        }
        if(!edit && !remove) vm.error?.let { ErrorCard(it,vm::refresh) }
        vm.notice?.let { Text(it,style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.primary) }
    }
}
