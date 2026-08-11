# CodeMirror (опционально)

Редактор файлов в разделе «Файлы» работает и без этих библиотек — тогда он
показывает нумерацию строк, но без подсветки синтаксиса. Чтобы включить
подсветку shell и YAML, положите сюда четыре файла.

## Установка

Одной командой на сервере:

```bash
cd /opt/bot4vps/ui/web/static/vendor/codemirror
CM=https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16
curl -fLO $CM/codemirror.min.css
curl -fLO $CM/codemirror.min.js
curl -fL -o shell.min.js  $CM/mode/shell/shell.min.js
curl -fL -o yaml.min.js   $CM/mode/yaml/yaml.min.js
curl -fL -o material-darker.min.css $CM/theme/material-darker.min.css
systemctl restart bot4vps
```

После этого обновите страницу с очисткой кэша (Ctrl+Shift+R).

## Как это проверяется

`ui/web/static/js/editor.js` смотрит, определён ли `window.CodeMirror`:

* определён → редактор с подсветкой, складками и Ctrl+S;
* не определён → встроенный редактор с нумерацией строк.

Никаких обращений к CDN во время работы панели не происходит: `index.html`
подключает файлы только из этого каталога. Если их нет, браузер получит 404 на
теги подключения и просто продолжит работу — это ожидаемо.

## Почему не CDN

Bot4VPS — панель управления серверами, её открывают в том числе в закрытых
сетях и через VPN. Остальной интерфейс (включая xterm в веб-терминале)
обслуживается локально, редактор устроен так же.
