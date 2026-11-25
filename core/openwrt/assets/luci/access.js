'use strict';
'require view';
'require rpc';
'require ui';

var list = rpc.declare({ object: 'bot4vps-access', method: 'accounts' });
var rotate = rpc.declare({ object: 'bot4vps-access', method: 'rotate', params: ['id'] });
var toggle = rpc.declare({ object: 'bot4vps-access', method: 'toggle', params: ['id', 'enabled'] });

return view.extend({
    load: function() { return list(); },
    render: function(data) {
        var rows = (data.accounts || []).map(function(account) {
            return E('div', { 'class': 'cbi-section' }, [
                E('h3', {}, account.label),
                E('p', {}, account.username + ' — ' + (account.enabled ? 'Доступ включён' : 'Доступ отключён')),
                E('button', { 'class': 'cbi-button cbi-button-action', 'click': function() {
                    ui.showModal('Перевыпустить секрет доступа?', [
                        E('p', {}, 'Текущий секрет и сеансы Bot4VPS станут недействительными. Новый секрет нужно указать в панели.'),
                        E('button', { 'class': 'cbi-button', 'click': ui.hideModal }, 'Отмена'),
                        E('button', { 'class': 'cbi-button cbi-button-negative', 'click': function() {
                            return rotate(account.id).then(function(result) {
                                if (!result.ok) throw new Error(result.error || 'Не удалось перевыпустить секрет');
                                ui.showModal('Новый секрет Bot4VPS', [
                                    E('p', {}, 'Скопируйте секрет в настройки API шлюза в Bot4VPS. Секрет не отображается в журнале.'),
                                    E('input', { 'class': 'cbi-input-text', 'readonly': 'readonly', 'value': result.secret }),
                                    E('button', { 'class': 'cbi-button', 'click': ui.hideModal }, 'Закрыть')
                                ]);
                            }).catch(function(error) { ui.addNotification(null, E('p', {}, error.message), 'error'); });
                        } }, 'Перевыпустить')
                    ]);
                } }, 'Перевыпустить секрет'),
                ' ',
                E('button', { 'class': 'cbi-button', 'click': function() {
                    var enabled = !account.enabled;
                    ui.showModal(enabled ? 'Включить доступ?' : 'Отключить доступ?', [
                        E('p', {}, enabled ? 'Панель сможет снова подключиться с действующим секретом.' : 'Сеансы Bot4VPS будут отозваны. Мониторинг и управление из панели остановятся.'),
                        E('button', { 'class': 'cbi-button', 'click': ui.hideModal }, 'Отмена'),
                        E('button', { 'class': 'cbi-button cbi-button-action', 'click': function() {
                            return toggle(account.id, enabled).then(function(result) {
                                if (!result.ok) throw new Error(result.error || 'Не удалось изменить доступ');
                                window.location.reload();
                            }).catch(function(error) { ui.addNotification(null, E('p', {}, error.message), 'error'); });
                        } }, enabled ? 'Включить' : 'Отключить')
                    ]);
                } }, account.enabled ? 'Отключить доступ' : 'Включить доступ')
            ]);
        });
        return E('div', {}, [
            E('h2', {}, 'Доступ Bot4VPS'),
            E('p', {}, 'Отдельные учётные записи API. Управление здесь не изменяет ваш вход в LuCI или SSH.'),
            rows.length ? E('div', {}, rows) : E('p', {}, 'Подключений Bot4VPS нет.')
        ]);
    },
    handleSave: null, handleSaveApply: null, handleReset: null
});
