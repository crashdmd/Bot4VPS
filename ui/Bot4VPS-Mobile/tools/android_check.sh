#!/usr/bin/env bash
set -euo pipefail
mobile_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_env="${BOT4VPS_BUILD_ENV:-$mobile_dir/.build-env}"
export BOT4VPS_BUILD_ENV="$build_env"
python3 "$mobile_dir/tools/prepare_android.py"
export JAVA_HOME="$build_env/jdk"
export ANDROID_HOME="$build_env/android-sdk"
export ANDROID_USER_HOME="$build_env/android-user"
export GRADLE_USER_HOME="$build_env/gradle-cache"
export PATH="$JAVA_HOME/bin:$PATH"
cd -- "$mobile_dir"
if [[ $# -eq 0 ]]; then set -- :app:assembleRelease; fi
exec nice -n 10 "$build_env/gradle-8.9/bin/gradle" --no-daemon --max-workers=1 --console=plain \
    -Dorg.gradle.vfs.watch=false '-Dorg.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=384m' \
    -Pkotlin.compiler.execution.strategy=in-process "$@"
