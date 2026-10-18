#!/usr/bin/env bash
# Супервизор Candy Userbot для Termux и Linux: перезапускает после сбоя.
#
# Коды выхода main.py:
#   0    штатная остановка       -> выходим
#   2    ошибка настройки/входа  -> выходим (повтор не поможет, смотрите лог)
#   130  принудительный выход    -> выходим
#   иное сбой или потеря связи   -> перезапуск с нарастающей паузой
#
# Переменные: PYTHON (интерпретатор; по умолчанию .venv/bin/python или python3), CANDY_RESTART_MIN / CANDY_RESTART_MAX (паузы, с),
# CANDY_STABLE_AFTER (сколько секунд работы считаются «стабильным запуском»),
# CANDY_MAX_FAST_FAILS (0: без ограничения; иначе сколько быстрых сбоев подряд терпеть).

cd "$(dirname "$0")" || exit 1

# Интерпретатор: PYTHON из окружения, иначе виртуальное окружение .venv (его создаёт
# installer.sh в Linux), иначе системный python3.
if [ -z "${PYTHON:-}" ]; then
    if [ -x .venv/bin/python ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="python3"
    fi
fi
delay_min="${CANDY_RESTART_MIN:-5}"
delay_max="${CANDY_RESTART_MAX:-120}"
stable_after="${CANDY_STABLE_AFTER:-60}"
max_fast="${CANDY_MAX_FAST_FAILS:-0}"

child=""
stopping=0

# SIGTERM/SIGHUP пересылаем потомку. Ctrl+C (SIGINT) терминал уже доставил всей группе
# процессов, включая потомка: второй сигнал main.py понял бы как «выйти принудительно».
forward() {
    stopping=1
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null
    fi
}
interrupted() {
    stopping=1
}
trap forward TERM HUP
trap interrupted INT

# Termux: не даём Android усыпить процесс (если есть termux-api).
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

delay="$delay_min"
fast_fails=0

while true; do
    started=$SECONDS
    # <&0: иначе фоновый процесс получает stdin=/dev/null и не может спросить API ID, код и 2FA.
    "$PYTHON" main.py "$@" <&0 &
    child=$!
    wait "$child"
    code=$?
    # Первый wait прерывается сигналом: дожидаемся настоящего завершения потомка.
    while kill -0 "$child" 2>/dev/null; do
        wait "$child" 2>/dev/null
        code=$?
    done
    child=""

    if [ "$stopping" -eq 1 ]; then
        exit 0
    fi
    case "$code" in
        0|2|130) exit "$code" ;;
    esac

    ran=$((SECONDS - started))
    if [ "$ran" -ge "$stable_after" ]; then
        delay="$delay_min"
        fast_fails=0
    else
        fast_fails=$((fast_fails + 1))
        if [ "$max_fast" -gt 0 ] && [ "$fast_fails" -ge "$max_fast" ]; then
            echo "[run.sh] $fast_fails быстрых сбоев подряд, останавливаюсь (код $code)." >&2
            exit "$code"
        fi
    fi

    echo "[run.sh] main.py завершился с кодом $code через ${ran} с, перезапуск через ${delay} с." >&2
    sleep "$delay" &
    child=$!
    wait "$child"
    child=""
    if [ "$stopping" -eq 1 ]; then
        exit 0
    fi
    delay=$((delay * 2))
    [ "$delay" -gt "$delay_max" ] && delay="$delay_max"
done
