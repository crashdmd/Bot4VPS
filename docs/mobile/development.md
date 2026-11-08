# Сборка и публикация Bot4VPS Mobile

Исходники находятся в [`ui/Bot4VPS-Mobile`](../../ui/Bot4VPS-Mobile). Приложение написано на Kotlin и Jetpack Compose; минимальная версия Android — 8.0 (API 26).

## Структура

| Каталог относительно `ui/Bot4VPS-Mobile` | Назначение |
|---|---|
| `app/src/main` | Код, ресурсы и транспортный контракт |
| `app/src/test` | Unit-тесты |
| `gradle` | Gradle wrapper |
| `tools` | Подготовка инструментов, проверка контракта и генерация иконки |

Эталон интерфейса — мобильная Web-панель. [Сверка сценариев](workflows.md) описывает действия и используемые API. Векторный исходник иконки — [`tools/artwork/launcher.svg`](../../ui/Bot4VPS-Mobile/tools/artwork/launcher.svg); генератор — `python3 tools/launcher_icon.py`, запускаемый из каталога исходников приложения.

Серверная часть доступа находится в `ui/web/_internal/device_access/`, обработчики — в `ui/web/routers/mobile_access.py`, настройка локального файрволла — в `core/_internal/device_access/`, Web-интерфейс — в `ui/web/static/js/_internal/device_access/panel.js`. Эти пакеты входят в установку сервиса и нужны для его запуска даже при выключенном API.

## Инструменты и подпись

Нужны JDK 17, Gradle 8.9, Android SDK 35 и Build Tools 35.0.0. Помощник `tools/android_check.sh` скачивает официальные инструменты и проверяет контрольные суммы. Каталог среды задаётся переменной `BOT4VPS_BUILD_ENV`; без неё используется `.build-env` внутри исходников.

Ключ подписи храните вне исходников и публичного репозитория. Задайте абсолютный путь к существующему хранилищу через `BOT4VPS_SIGNING_STORE`. При необходимости используются `BOT4VPS_SIGNING_STORE_PASSWORD`, `BOT4VPS_SIGNING_KEY_ALIAS` и `BOT4VPS_SIGNING_KEY_PASSWORD`. Их значения передавайте через локальное окружение или секреты сборки. В документацию и коммиты они не входят.

В текущей конфигурации локальный путь по умолчанию — `.local-build/mobile/signing/debug.keystore` в корне основного проекта. Для обновления установленного приложения необходим прежний ключ подписи. Сохраните его отдельно: замена ключа не позволит установить APK поверх существующего приложения.

## Сборка и проверки

Из корня Bot4VPS задайте каталог инструментов вне исходников и перейдите в Android-проект:

```bash
export BOT4VPS_BUILD_ENV="$PWD/.local-build/mobile"
cd ui/Bot4VPS-Mobile
bash tools/android_check.sh --project-cache-dir "$BOT4VPS_BUILD_ENV/project-cache" :app:assembleRelease
bash tools/android_check.sh --project-cache-dir "$BOT4VPS_BUILD_ENV/project-cache" :app:testReleaseUnitTest
bash tools/android_check.sh --project-cache-dir "$BOT4VPS_BUILD_ENV/project-cache" :app:lintRelease
python3 tools/test_contract.py
```

Запускайте команды последовательно. Помощник использует один Gradle worker, heap 1024 МБ и metaspace 384 МБ. Результат — `app/build/outputs/apk/release/app-release.apk`; release собирается без отладки, с R8 и сокращением ресурсов.

С установленными инструментами проект можно открыть в Android Studio или собрать через `./gradlew --no-daemon :app:assembleRelease`, указав SDK и параметры подписи.

Unit-тесты и контрактные проверки проверяют логику и API. Для выпуска также проверьте на Android-устройстве установку и обновление, PIN и биометрию, клавиатуру терминала и уведомления. Эти проверки не заменяют независимый аудит безопасности.

## Публикация APK и обновлений

Приложение проверяет `https://raw.githubusercontent.com/crashdmd/Bot4VPS/main/ui/mobile/release.json` и скачивает APK из того же каталога. Учётные данные панели в эти запросы не передаются.

1. Увеличьте `versionName` и `versionCode` в `app/build.gradle.kts`, соберите и проверьте release APK с прежним ключом подписи.
2. Поместите проверенный APK в `ui/mobile` с именем вида `Bot4VPS-Mobile-<версия>-release.apk`.
3. Обновите [`ui/mobile/release.json`](../../ui/mobile/release.json): `version`, `versionCode`, `filename`, `size`, `sha256` и `changelog` должны соответствовать APK.
4. Опубликуйте APK и метаданные вместе. Отдельный мобильный GitHub-релиз и изменение версии сервиса не требуются.

Ручная проверка и выключатель автоматической проверки находятся в **Ещё → Настройки → Обновления → Приложение Bot4VPS Mobile**. Автоматическая проверка выполняется при открытии приложения не чаще раза в сутки. Если GitHub недоступен, работа с панелью продолжается.

## Что переносить в публичный проект

Переносите исходники, ресурсы, файлы сборки, эту документацию и проверенные APK с метаданными. Общие правила исключения находятся в корневом [`.gitignore`](../../.gitignore); отдельный `.gitignore` внутри Android-проекта не требуется.

Ключи подписи, пароли, токены, коды привязки, данные устройств и сессий, конфигурации рабочей панели, локальные заметки и отчёты остаются вне публичного проекта. Среда SDK, кэши и результаты сборки также не входят в исходники для переноса. Не исключайте весь `ui/mobile`: APK и метаданные нужны для скачивания и обновлений.
