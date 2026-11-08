#!/usr/bin/env python3
"""Read the existing Python API contract without importing or changing the server.

The resulting asset drives native Compose forms, never HTML or a WebView.
Run: python3 tools/generate_contract.py --repo /path/to/Bot4VPS
"""
import argparse
import ast
import json
import re
from pathlib import Path

LABELS = dict(line.split('=', 1) for line in '''name=Название
host=Адрес сервера
port=Порт
user=Пользователь SSH
username=Логин
password=Пароль
old=Текущий пароль
new=Новый пароль
new_password=Новый пароль
old_password=Текущий пароль
current_password=Текущий пароль
root_password=Пароль root
bot_token=Токен Telegram-бота
code=Код подтверждения
key=Ключ
public_key=Публичный SSH-ключ
key_path=Путь к SSH-ключу
auth_type=Способ входа
auth_enabled=Защита входа
test=Проверить SSH перед добавлением
certificate_check=Проверять сертификат
ssl_host=Домен сертификата
ssl_monitor=Следить за сертификатами группы
group=Группа
server_id=Сервер
destination_server_id=Сервер назначения
target=Назначение
target_root=Каталог восстановления
restore_mode=Способ восстановления
selection_mode=Что восстановить
selected_paths=Выбранные пути
protective_backup=Создать защитную копию
confirm_without_protective=Продолжить без защитной копии
confirm=Подтверждение
apply=Применить изменения
prepared_operation_id=Подготовленная операция
request_id=Идентификатор запроса
encrypt=Шифровать архив
label=Подпись
filename=Имя файла
file=Файл
cert=Файл сертификата
root=Раздел файлов
project=Проект Compose
directory=Каталог
content=Содержимое
path=Путь
exclusions=Исключения
sources=Источники копирования
automatic=Расписание
enabled=Включено
interval=Интервал проверки
profile=Профиль копирования
settings=Настройки
params=Параметры
values=Значения параметров
packages=Пакеты
backend=Система firewall
protocol=Протокол
source=Источник
selected_rules=Переносимые правила
acknowledge_firewall_conflict=Разрешить конфликт firewall
confirm_switch=Подтвердить переключение
family=Семейство nftables
table=Таблица nftables
chain=Цепочка nftables
ban_time=Время блокировки
find_time=Окно обнаружения
max_retry=Число попыток
ssh_jail_enabled=Защита SSH
jail=Правило Fail2ban
ip=IP-адрес
remove_config=Удалить конфигурацию
remove_home=Удалить домашний каталог
remove_data=Удалить данные
switch_to_key=Переключить подключение на ключ
sudo=Доступ sudo
allow_without_sudo=Подключаться без sudo
fingerprint=Отпечаток ключа
scope=Область
names=Имена файлов
script_name=Скрипт
command=Команда
session=Сохранять состояние оболочки
task_id=Задача
operation_id=Операция
backup_id=Резервная копия
entry_key=Импортированный архив
record_id=Запись аудита
event_id=Уведомление
sid=Сервис
action=Действие
image=Образ Docker
stack=Стек Compose
target_name=Имя проекта назначения
overwrite=Перезаписать
remote=На удалённом сервере
ignore_key=Исключённый стек
endpoint=Внешний адрес WireGuard
address=Адрес VPN
dns=DNS
new_name=Новое имя
old_name=Текущее имя
reissue=Перевыпустить профили
timezone=Часовой пояс
theme=Тема
tasks=Лимит истории задач
events=Лимит уведомлений
user_id=Telegram ID владельца
chat_id=Telegram ID получателя
domain=Домен
email=Email
common_name=Имя сертификата
cert_path=Путь к сертификату
trusted_proxies=Доверенные прокси
force=Принудительно
version=Версия
from=Начало периода
to=Конец периода
range=Период
step=Детализация
q=Поиск
query=Поиск
limit=Число записей
cursor=Следующая страница
parent=Родительский каталог
view=Режим просмотра
tail=Число строк журнала
kind=Тип
retry=Повторить
rebuild=Пересоздать индекс
use_stored=Использовать сохранённый пароль
replace=Заменить существующий файл
confirm_bot4vps_replace=Подтвердить замену архива установки
WG_PORT=Порт WireGuard
WG_ADDR=Адрес туннеля
WG_DNS=DNS клиентов
WG_ENDPOINT=Внешний адрес VPN
tag=Версия выпуска
arch=Архитектура
web_port=Порт панели
web_path=Путь панели
ssl_mode=Способ HTTPS
server_ip=IP сервера
autostart=Автозапуск
bind_ip=Адрес прослушивания
volumes=Тома
ports=Порты контейнера
environment=Переменные окружения
restart=Политика перезапуска
network=Сеть контейнера
detach=Фоновый запуск
args=Аргументы
success=Успешно
online=Доступен
status=Состояние
message=Сообщение
error=Ошибка
warnings=Предупреждения
output=Вывод
stdout=Вывод
stderr=Ошибки
created_at=Создано
finished_at=Завершено
started_at=Начато
duration=Длительность
count=Количество
size=Размер
installed=Установлен
running=Выполняется
queue=Очередь
queues=Очереди
servers=Серверы
groups=Группы
profiles=Профили
backups=Резервные копии
operations=Операции
items=Записи
rows=Записи
mtime=Изменено
cpu=CPU
ram_pct=Память, %
disk_pct=Диск, %
load=Средняя нагрузка
uptime=Время работы
ssh_error=Ошибка SSH
result=Результат
description=Описание
retention=Хранение
local=Локальное хранение
store=Хранилище
full=Полное восстановление
schedule=Расписание
day=День
time=Время
keep=Хранить копий
mode=Режим
type=Тип
uri=Адрес
uri_prefix=Путь панели
security_revision=Обновление безопасности
'''.strip().splitlines())

WORDS = dict(line.split('=', 1) for line in '''setup=Первичная настройка
auth=Учётная запись
account=Учётная запись
password=Пароль
recover=Восстановление доступа
confirm=Подтверждение
disable=Отключение
totp=Двухфакторная защита
audit=Аудит
facets=Фильтры
stats=Статистика
timeline=Хронология
backups=Резервные копии
create=Создание
import=Импорт
imported=Импортированные архивы
preview=Состав архива
readiness=Готовность восстановления
password-probe=Проверка пароля архива
inventory=Индекс архива
prepare=Подготовка
tree=Дерево файлов
children=Содержимое каталога
search=Поиск
plan=План восстановления
restore=Восстановление
download=Скачивание
profiles=Профили
bot4vps-settings=Настройки копии установки
source-tree=Выбор источников
locate=Найти каталог
files=Файлы
read=Содержимое файла
write=Сохранение файла
docker=Docker
projects=Проекты Compose
directories=Каталоги
upload=Загрузка файла
keys=SSH-ключи
view=Просмотр
masterkey=Мастер-ключ
encrypt-secrets=Шифрование секретов
new=Создание ключа
resend=Повторная отправка кода
metrics=Мониторинг серверов
overview=Обзор
latest=Последняя проба
monitor=Проверки
config=Конфигурация
notifications=Уведомления
categories=Категории уведомлений
channel=Канал уведомлений
check=Запуск проверки
events=Уведомления
mark-read=Отметить прочитанным
servers=Серверы
quick-setup=Настройка сервера
diagnostics=Диагностика
system=Система
check-updates=Проверка обновлений
upgrade=Обновление пакетов
reboot=Перезагрузка
packages=Пакеты
install=Установка
firewall=Firewall
nftables=nftables
chain=Цепочка
switch=Переключение
migration=Перенос правил
open=Открытие порта
close=Закрытие порта
enable=Включение
remove=Удаление
rules=Правила
fail2ban=Fail2ban
settings=Настройки
banned=Заблокированные адреса
restart=Перезапуск
start=Запуск
stop=Остановка
uninstall=Удаление
jails=Защищаемые службы
enabled=Включение правила
unban=Разблокировка адреса
whitelist=Доверенные адреса
filters=Фильтры
configuration=Файлы конфигурации
content=Содержимое
ssh=SSH-доступ
hostkey=Ключ сервера
accept=Принять ключ сервера
port=Порт
root-login=Вход root
password-auth=Вход по паролю
key=SSH-ключ
users=Пользователи
sudo=Права sudo
local-keys=Ключи панели
select=Ключ подключения
scripts=Скрипты
upload-check=Проверка имён файлов
exec=Команда SSH
probe=Проверка доступности
ssh-probe=Проверка SSH
ping=Проверка связи
test=Проверка подключения
test-connection=Проверка нового подключения
test-draft=Проверка изменённого подключения
groups=Группы серверов
services=Сервисы
params=Параметры установки
status=Состояние
images=Образы
pulling=Загрузки образов
cancel=Отмена
stacks=Стеки Compose
file=Compose-файл
logs=Журнал
zip=Архив проекта
ignored-stacks=Исключённые стеки
sync=Синхронизация
action=Действие
state=Состояние
export-zip=Экспорт профилей
reset-stats=Сброс статистики
qr=QR-код
endpoint=Внешний адрес VPN
toggle=Включение профиля
rename=Переименование
reissue=Перевыпуск
enqueue=Запуск операции
bulk-check=Проверка всех серверов
resolve-source=Источник установки
install-result=Результат установки
db-export=Экспорт базы
db-import=Импорт базы
backup-password=Пароль резервных копий
verify=Проверка
forgot=Восстановление пароля
timezone=Часовой пояс
theme=Тема
history=История
web=Панель
port-status=Состояние смены порта
summary=Обзор
journal=Журнал системы
telegram=Telegram
health=Проверка Telegram
queues=Очереди
tasks=Задачи
continue=Продолжить очередь
retry=Повторить задачу
clear=Очистить очередь
tls=HTTPS
self-signed=Самоподписанный сертификат
letsencrypt=Let's Encrypt
custom=Свой сертификат
proxy=Доверенный прокси
off=Отключить HTTPS
renew=Обновить сертификат
update=Обновление Bot4VPS
changelog=Описание версии
changelog_new=Изменения новой версии
versions=Доступные версии
rollback=Откат версии
filename=Переименовать архив
operations=Операции копирования
'''.strip().splitlines())

SECTIONS = {'dashboard':'Обзор', 'servers':'Серверы', 'groups':'Группы', 'quick_setup':'Настройка сервера',
            'docker':'Docker', 'wireguard':'WireGuard', 'xui':'3x-ui', 'backups':'Резервные копии',
            'files':'Файлы и ключи', 'metrics':'Мониторинг', 'audit':'Аудит', 'events':'Уведомления',
            'queues':'Очереди', 'settings':'Настройки', 'security':'Безопасность', 'telegram':'Telegram', 'update':'Обновления'}

def value(node, fallback=None):
    try:
        result=ast.literal_eval(node)
        return fallback if result is Ellipsis else result
    except (ValueError, TypeError): return fallback

def parse_default(node):
    if node is None: return None, True, {}
    if isinstance(node, ast.Call):
        kw = {k.arg:k.value for k in node.keywords}
        default = kw.get('default', node.args[0] if node.args else None)
        factory = kw.get('default_factory')
        if factory: return ([] if ast.unparse(factory) == 'list' else {}), False, kw
        return value(default), default is None or isinstance(default, ast.Constant) and default.value is Ellipsis, kw
    return value(node), False, {}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'app/src/main/assets/native_contract.json')
    args=parser.parse_args(); web=args.repo/'ui/web'
    classes={}; aliases={}; trees={}
    for path in sorted([web/'app.py', *(web/'routers').glob('*.py')]):
        if path.name == 'mobile_app.py':
            continue  # Web APK distribution is not a native panel operation.
        tree=ast.parse(path.read_text()); trees[path]=tree
        for n in tree.body:
            if isinstance(n,ast.ClassDef): classes[n.name]=n
            if isinstance(n,ast.Assign):
                for t in n.targets:
                    if isinstance(t,ast.Name) and isinstance(n.value,(ast.Subscript,ast.Constant)): aliases[t.id]=n.value

    def schema(annotation, seen=()):
        if annotation is None: return {'type':'string'}
        if isinstance(annotation,ast.BinOp) and isinstance(annotation.op,ast.BitOr):
            parts=[annotation.left,annotation.right]
            chosen=next((a for a in parts if not isinstance(a,ast.Constant) or a.value is not None),parts[0])
            return schema(chosen,seen)
        if isinstance(annotation,ast.Subscript):
            kind=ast.unparse(annotation.value)
            if kind in ('Annotated','Optional'): return schema(annotation.slice.elts[0] if isinstance(annotation.slice,ast.Tuple) else annotation.slice,seen)
            if kind=='Literal': return {'type':'string','enum':value(annotation.slice,[]) if isinstance(annotation.slice,ast.Tuple) else [value(annotation.slice)]}
            if kind in ('List','list'): return {'type':'array','items':schema(annotation.slice,seen)}
            if kind in ('Dict','dict'): return {'type':'object','additionalProperties':schema(annotation.slice.elts[-1],seen) if isinstance(annotation.slice,ast.Tuple) else {'type':'string'}}
        name=ast.unparse(annotation)
        if name in classes and name not in seen: return model(name,seen)
        if name in aliases and name not in seen: return schema(aliases[name],seen+(name,))
        return {'type':{'int':'integer','float':'number','bool':'boolean','dict':'object','Any':'string','UploadFile':'file'}.get(name,'string')}

    def model(name,seen=()):
        cls=classes[name]; props={}; required=[]
        for base in cls.bases:
            b=ast.unparse(base)
            if b in classes and b not in seen:
                inherited=model(b,seen+(name,)); props.update(inherited.get('properties',{})); required+=inherited.get('required',[])
        for n in cls.body:
            if not isinstance(n,ast.AnnAssign) or not isinstance(n.target,ast.Name):continue
            key=n.target.id; s=schema(n.annotation,seen+(name,)); default,req,kw=parse_default(n.value)
            s['title']=LABELS.get(key,key.replace('_',' ').capitalize())
            if name == 'ServerCreate' and key == 'test': s['description']='Проверить адрес, порт и данные входа. Если SSH недоступен, сервер не будет добавлен.'
            s['nullable']='None' in ast.unparse(n.annotation) or ast.unparse(n.annotation).startswith('Optional')
            if default is not None:s['default']=default
            if req:required.append(key)
            for src,dst in [('min_length','minLength'),('max_length','maxLength'),('ge','minimum'),('le','maximum'),('pattern','pattern')]:
                if src in kw and value(kw[src]) is not None:s[dst]=value(kw[src])
            if key in ('password','old','new','new_password','old_password','root_password','current_password','bot_token','key','private_key'):s['secret']=True
            if key in ('content','public_key','command'):s['multiline']=True
            if key=='auth_type':s['enum']=['password','key']
            if key=='root':s['enum']=['scripts','keys','docker']
            if key=='theme':s['enum']=['dark','light']
            pattern=s.get('pattern','')
            if re.fullmatch(r'\^\([a-z|]+\)\$',pattern):s['enum']=pattern[2:-2].split('|')
            props[key]=s
        return {'type':'object','properties':props,'required':required,'model':name}

    operations=[]
    for path,tree in trees.items():
        prefixes={}
        for n in tree.body:
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func).endswith('APIRouter'):
                for target in n.targets:
                    if isinstance(target,ast.Name):prefixes[target.id]=next((value(k.value,'') for k in n.value.keywords if k.arg=='prefix'),'')
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for dec in n.decorator_list:
                if not isinstance(dec,ast.Call) or not isinstance(dec.func,ast.Attribute) or dec.func.attr not in ('get','post','put','patch','delete'):continue
                if not dec.args or not isinstance(dec.args[0],ast.Constant):continue
                url=prefixes.get(ast.unparse(dec.func.value),'')+dec.args[0].value
                if not url.startswith('/api/') or url in ('/api/stream','/api/routes','/api/ping','/api/upd/health'):continue
                if url.startswith('/api/login') or url in ('/api/me','/api/logout'):continue
                method=dec.func.attr.upper(); fields=[]; body=None
                defaults=[None]*(len(n.args.args)-len(n.args.defaults))+n.args.defaults
                for a,d in zip(n.args.args,defaults):
                    typ=ast.unparse(a.annotation) if a.annotation else ''
                    if a.arg in ('request','background_tasks','websocket'):continue
                    default,req,kw=parse_default(d)
                    if a.arg in ('body','ref'):
                        body=schema(a.annotation); continue
                    location='path' if '{'+a.arg+'}' in url else ('form' if 'UploadFile' in typ or isinstance(d,ast.Call) and ast.unparse(d.func) in ('Form','File') else 'query')
                    f=schema(a.annotation); f.update(name=value(kw.get('alias'),a.arg),location=location,title=LABELS.get(a.arg,a.arg.replace('_',' ').capitalize()),required=req or location=='path')
                    if default is not None:f['default']=default
                    if a.arg=='root':f['enum']=['scripts','keys','docker']
                    fields.append(f)
                parts=[s for s in url.split('/')[2:] if not s.startswith('{')]
                section=('quick_setup' if 'quick-setup' in url else 'security' if parts[0] in ('auth','masterkey','setup') else 'events' if parts[0] in ('events','notifications','monitor') else 'queues' if parts[0] in ('tasks','queues') else 'metrics' if parts[0] in ('metrics','timeline') else 'files' if parts[0] in ('files','keys','scripts','scripts-archive.zip','upload') else 'servers' if parts[0]=='ssh' else 'dashboard' if parts[0] in ('summary','system') else parts[0])
                if section=='settings' and 'backup-password' in parts:section='security'
                if section=='services':section='services'
                translated=[WORDS.get(p,p.replace('_',' ').capitalize()) for p in parts]
                if method=='DELETE':title='Удалить: '+ ' · '.join(translated[-2:])
                elif method in ('PATCH','PUT'):title='Изменить: '+' · '.join(translated[-2:])
                elif method=='POST':title=' · '.join(translated[-3:])
                else:title=' · '.join(translated[-2:])
                operations.append(dict(id=method+' '+url,method=method,path=url,section=section,title=title,
                    group=translated[-2] if len(translated)>1 else translated[0],fields=fields,body=body,
                    destructive=method=='DELETE' or any(p in parts for p in ('reboot','off','remove','uninstall','reset-stats','rollback','clear','new','hostkey')),
                    download=any(p in parts for p in ('download','db-export','export-zip','config','qr')) and method=='GET' and parts[0]=='services' or parts[-1]=='download' or url=='/api/scripts-archive.zip'))

    # Concrete service actions expose the existing polymorphic API as ordinary native forms.
    base_actions=[op for op in operations if op['path'].endswith('/enqueue/{action}') or op['path'].endswith('/action/{action}')]
    concrete=[]
    for sid in ('wireguard','docker','3x-ui'):
        svc=args.repo/'services'/sid/'impl/service.py'
        tree=ast.parse(svc.read_text())
        for n in ast.walk(tree):
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) or not (n.name.startswith('do_') or n.name.startswith('card_')):continue
            action=n.name.split('_',1)[1]
            if action in ('sync','resolve_source','release_download') or n.name.startswith('card_') and action in ('ssh','check_installed','action_requires_sync'):continue
            template=next(op for op in base_actions if ('/action/' in op['path'])==n.name.startswith('card_'))
            op=json.loads(json.dumps(template)); op['path']=op['path'].replace('{sid}',sid).replace('{action}',action)
            op['id']='POST '+op['path'];op['section']={'3x-ui':'xui'}.get(sid,sid)
            op['fields']=[f for f in op['fields'] if f['name'] not in ('sid','action')]
            op['title']=' · '.join(WORDS.get(t,LABELS.get(t,t.capitalize())) for t in action.split('_'))
            op['group']='Операции'
            props={}
            for call in ast.walk(n):
                if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and 'params' in ast.unparse(call.func.value) and call.func.attr=='get' and call.args and isinstance(call.args[0],ast.Constant):
                    k=call.args[0].value; default=value(call.args[1]) if len(call.args)>1 else None
                    props[k]={'type':'boolean' if isinstance(default,bool) else 'integer' if isinstance(default,int) else 'string','title':LABELS.get(k,k.replace('_',' ').capitalize())}
                    if default is not None:props[k]['default']=default
            op['body']={'type':'object','properties':{'params':{'type':'object','properties':props,'additionalProperties':{'type':'string'},'title':'Параметры'}},'required':[]}
            op['destructive']=any(x in action for x in ('remove','rm','prune','down','stop','reset'))
            concrete.append(op)
    operations.extend(concrete)
    service_clones=[]
    for op in operations:
        if op['section']=='services':
            # Each service has a separate native section; no user-entered service identifier.
            for sid in ('wireguard','docker','3x-ui'):
                suffix=op['path'].split('{sid}',1)[-1]
                if '/action/{action}' in suffix or '/enqueue/{action}' in suffix:continue
                if any(word in suffix for word in ('/images','/stacks','/ignored-stacks')) and sid!='docker':continue
                if any(word in suffix for word in ('/config','/export-zip','/reset-stats','/qr','/endpoint')) and sid!='wireguard':continue
                if '/profiles' in suffix and sid!='wireguard' and not (sid=='docker' and op['method']=='GET' and suffix.endswith('/profiles')):continue
                if any(word in suffix for word in ('/db-export','/db-import','/resolve-source','/install-result')) and sid!='3x-ui':continue
                clone=json.loads(json.dumps(op));clone['path']=clone['path'].replace('{sid}',sid)
                clone['id']=clone['method']+' '+clone['path'];clone['section']={'3x-ui':'xui'}.get(sid,sid)
                clone['fields']=[f for f in clone['fields'] if f['name']!='sid']
                service_clones.append(clone)
    operations=[op for op in operations if op['section']!='services']+service_clones
    # Stable deduplication: prefer explicit action descriptors over the generic templates.
    operations=list({op['id']:op for op in operations}.values())
    def field(name,typ='string',default=None,choices=None):
        result={'type':typ,'title':LABELS.get(name,name.replace('_',' ').capitalize())}
        if default is not None:result['default']=default
        if choices:result['enum']=choices
        if name in ('password','key','bot_token'):result['secret']=True
        return result
    def obj(props,required=()):return {'type':'object','properties':props,'required':list(required)}
    schedule=obj({'enabled':field('enabled','boolean',False),'daily_time':{'type':'string','title':'Время ежедневной копии','default':'02:30'},'keep_last':{'type':'integer','title':'Хранить последних копий','default':7,'minimum':1}})
    limits=obj({key:{'type':'integer','title':title,'nullable':True,'minimum':1} for key,title in [('max_source_bytes','Максимальный размер источников, байт'),('max_archive_bytes','Максимальный размер архива, байт')]})
    notification=obj({'enabled':field('enabled','boolean',False),'success':field('success','boolean',False),'error':field('error','boolean',True)})
    backup_profile=obj({'schema_version':{'type':'integer','default':1,'hidden':True},'sources':{'type':'array','items':obj({'path':field('path'),'exclusions':{'type':'array','items':{'type':'string'},'title':'Исключения','default':[]}},['path']),'title':'Источники копирования','default':[]},'automatic':schedule,'limits':limits,'encrypt':field('encrypt','boolean',False),'notifications':obj({'backup':dict(notification,title='Уведомления о копировании'),'restore':dict(notification,title='Уведомления о восстановлении')})})
    action_overrides={
        ('docker','container_run'):obj({'name':field('name'),'image':field('image'),'ports':field('ports'),'env':dict(field('environment'),multiline=True),'restart':field('restart',choices=['no','always','unless-stopped','on-failure'])},['name','image']),
        ('3x-ui','install'):obj({'username':field('username'),'password':field('password'),'port':field('port','integer',54321),'web_base_path':dict(field('web_path'),default=''),'source':field('source',default='github',choices=['github','push']),'tag':field('tag'),'arch':field('arch'),'ssl_mode':field('ssl_mode',default='none',choices=['none','domain','ip','custom','proxy']),'domain':field('domain'),'server_ip':field('server_ip'),'cert_file':field('cert_path'),'key_file':field('key_path'),'bind_local':field('bind_ip','boolean',False)},['username','password','port']),
        ('wireguard','install'):obj({'WG_PORT':field('WG_PORT','integer',51820),'WG_ADDR':field('WG_ADDR',default='10.66.66.1/24'),'WG_DNS':field('WG_DNS',default='1.1.1.1'),'WG_ENDPOINT':field('WG_ENDPOINT')}),
        ('3x-ui','unit_action'):obj({'action':field('action',choices=['start','stop','restart','restart_xray'])},['action']),
    }
    for action in ('container_start','container_stop','container_restart','container_rm'):action_overrides['docker',action]=obj({'name':field('name')},['name'])
    for action in ('compose_up','compose_down','compose_restart'):
        action_overrides['docker',action]=obj({'stack':dict(field('stack'),title='Проект'), 'source':{'type':'string','title':'Источник','enum':['library','server'],'default':'library'}, 'key':dict(field('key'),title='Развёртывание',nullable=True,secret=False)},['stack','source'])
    for action in ('set_autostart','set_bbr'):action_overrides['3x-ui',action]=obj({'enabled':field('enabled','boolean',False)},['enabled'])
    for action,key in [('change_username','username'),('change_password','password'),('change_port','port'),('change_path','path')]:
        action_overrides['3x-ui',action]=obj({key:field(key,'integer' if key=='port' else 'string'),'restart':field('restart','boolean',True)},[key])
    for op in operations:
        if op['path'].endswith('/export-zip'):
            op['download']=True
            op['body']['required']=['names']
            op['body']['properties']['names'].update(title='Профили',minItems=1)
        if op['path']=='/api/update/rollback':op['body']={'type':'object','properties':{'version':{'type':'string','title':'Версия'}},'required':['version']}
        if op.get('body',{}):
            props=op['body'].get('properties',{})
            if op['body'].get('model')=='RestoreBody':
                for key in ('apply','confirm','prepared_operation_id','request_id'):props.pop(key,None)
                props['restore_mode'].update(default='merge',enum=['merge','clean'])
            if op['body'].get('model')=='ProfileBody':props['profile']=dict(backup_profile,title='Профиль копирования')
            if op['body'].get('model')=='BotSettingsBody':props['settings']=obj({k:v for k,v in backup_profile['properties'].items() if k not in ('schema_version','sources')})
            if 'params' in props:
                sid=next((s for s in ('docker','wireguard','3x-ui') if '/'+s+'/' in op['path']),None)
                action=op['path'].split('/')[-1]
                if (sid,action) in action_overrides:props['params']=dict(action_overrides[sid,action],title='Параметры')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    version_tree = ast.parse((args.repo / 'core/version.py').read_text())
    version = next(ast.literal_eval(node.value) for node in version_tree.body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'APP_VERSION' for target in node.targets))
    args.output.write_text(json.dumps({'version':version,'sections':SECTIONS,'labels':LABELS,'operations':operations},ensure_ascii=False,indent=2)+'\n')
    print(f'Generated {len(operations)} native operation descriptors: {args.output}')

if __name__=='__main__':main()
