#!/usr/bin/env bash
# Публикация Candy Userbot на GitHub без личных данных.
#
#   bash tools/publish.sh [--dry-run] [владелец/репозиторий]             первая публикация
#   bash tools/publish.sh --release [--dry-run] [владелец/репозиторий]   выпуск обновления
#
# Скрипт сам ничего не удаляет и не переписывает чужую историю. Он:
#   1. копирует проект в НОВУЮ папку (без .git, data/, logs/, .env, кэша);
#   2. задаёт анонимного автора (имя Candy, адрес noreply GitHub);
#   3. проверяет, что в публикуемых файлах нет секретов, адресов почты и запретных слов;
#   4. отправляет код и тег версии.
# Первая публикация: создаёт свежий репозиторий с одним коммитом. Если репозиторий уже
# существует, скрипт останавливается: удалите его вручную на сайте (Settings, Danger Zone),
# иначе в старой истории останутся прежние коммиты.
# Выпуск обновления (--release): скачивает уже опубликованный репозиторий, заменяет его
# файлы текущими и добавляет ОДИН новый коммит сверху (история не переписывается). Версия
# CORE_VERSION должна быть выше опубликованной, иначе .update обновления не увидит.
#
# --dry-run: выполнить всё, кроме отправки (и создания репозитория).
#
# Запретные слова (например, настоящее имя) скрипт читает из файла ~/.candy-forbidden:
# по одному регулярному выражению в строке, регистр не важен. Сами слова нигде в проекте
# не хранятся, поэтому не попадут в публикацию.
#
# Переменные для тестов и особых случаев:
#   PUBLISH_LOGIN, PUBLISH_ID     логин и числовой ID GitHub (иначе берутся через gh)
#   PUBLISH_FORBIDDEN_FILE        другой путь к файлу запретных слов
#   PUBLISH_WORK                  своя рабочая папка (должна не существовать)
#   PUBLISH_ALLOW_NO_FORBIDDEN=1  не требовать файл запретных слов (не рекомендуется)
#   PUBLISH_ALLOW_SAME_VERSION=1  при --release не требовать повышения версии

set -euo pipefail

# Кириллица в проверках (регистр, имена файлов): нужна UTF-8 локаль; если её нет, grep работает побайтно.
export LC_ALL="$(locale -a 2>/dev/null | grep -i -m1 -E '^(c|en_us)\.utf-?8$' || echo C)"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="Vital-Candy/Candy-userbot"
DRY=0
MODE=publish

die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --release) MODE=release ;;
        -h|--help) usage; exit 0 ;;
        */*) REPO="$arg" ;;
        *) die "неизвестный аргумент: $arg (нужно --dry-run, --release или владелец/репозиторий)" ;;
    esac
done

command -v git >/dev/null 2>&1 || die "не найден git (pkg install git)."
command -v tar >/dev/null 2>&1 || die "не найден tar."

# --- Личность автора -----------------------------------------------------------------
LOGIN="${PUBLISH_LOGIN:-}"
ID="${PUBLISH_ID:-}"
if [ -z "$LOGIN" ] || [ -z "$ID" ]; then
    command -v gh >/dev/null 2>&1 || die "не найден gh (pkg install gh) и не заданы PUBLISH_LOGIN/PUBLISH_ID."
    gh auth status >/dev/null 2>&1 || die "вы не вошли в GitHub: выполните gh auth login."
    LOGIN="$(gh api user --jq .login)"
    ID="$(gh api user --jq .id)"
fi
case "$ID" in ''|*[!0-9]*) die "числовой ID GitHub получен неверно: '$ID'" ;; esac
AUTHOR_NAME="Candy"
AUTHOR_EMAIL="${ID}+${LOGIN}@users.noreply.github.com"

# --- Версия --------------------------------------------------------------------------
VERSION="$(sed -n 's/^CORE_VERSION *= *"\([^"]*\)".*/\1/p' "$SRC/core/version.py" | head -n 1)"
[ -n "$VERSION" ] || die "не удалось прочитать CORE_VERSION из core/version.py."

# --- Рабочая папка (всегда новая) ----------------------------------------------------
WORK="${PUBLISH_WORK:-$HOME/candy-publish-$(date +%Y%m%d-%H%M%S)}"
[ ! -e "$WORK" ] || die "папка $WORK уже существует; удалите её или укажите другую (PUBLISH_WORK)."

if [ "$MODE" = release ]; then
    # Выпуск: берём опубликованную историю и добавляем в неё один коммит.
    command -v gh >/dev/null 2>&1 || die "не найден gh (pkg install gh)."
    gh repo view "$REPO" >/dev/null 2>&1 || die "репозиторий $REPO не найден. Первую публикацию делайте без --release."
    say "Скачиваю опубликованный репозиторий $REPO в $WORK..."
    gh repo clone "$REPO" "$WORK" -- -q || die "не удалось скачать $REPO."
    OLD_VERSION="$(git -C "$WORK" show HEAD:core/version.py 2>/dev/null | sed -n 's/^CORE_VERSION *= *"\([^"]*\)".*/\1/p' | head -n 1)"
    # Версия обязана расти: иначе .update у пользователей ничего не найдёт.
    if [ "${PUBLISH_ALLOW_SAME_VERSION:-0}" != "1" ] && [ -n "$OLD_VERSION" ]; then
        newest="$(printf '%s\n%s\n' "$OLD_VERSION" "$VERSION" | sort -V | tail -n 1)"
        if [ "$OLD_VERSION" = "$VERSION" ] || [ "$newest" != "$VERSION" ]; then
            die "версия $VERSION не выше опубликованной ($OLD_VERSION). Поднимите CORE_VERSION в core/version.py."
        fi
    fi
    # Старые файлы убираем, чтобы удалённые в проекте файлы исчезли и из репозитория.
    find "$WORK" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
else
    mkdir -p "$WORK"
fi

say "Копирую проект в $WORK (без .git, data, logs, .env, кэша)..."
(
    cd "$SRC"
    tar -cf - \
        --exclude='./.git' --exclude='./data' --exclude='./logs' --exclude='./.env' \
        --exclude='./.venv' --exclude='__pycache__' --exclude='*.session' \
        --exclude='*.session-journal' --exclude='*.zip' --exclude='*.bak' .
) | tar -xf - -C "$WORK"

cd "$WORK"
if [ "$MODE" = publish ]; then
    git init -q
    git checkout -q -b main
fi
git config user.name "$AUTHOR_NAME"
git config user.email "$AUTHOR_EMAIL"
git config commit.gpgsign false
git add -A

# --- Проверки перед коммитом ---------------------------------------------------------
FOUND=0
report() { FOUND=1; printf 'НАЙДЕНО: %s\n' "$1" >&2; }

# 1. Файлы, которых в публикации быть не должно.
bad_paths="$(git -c core.quotepath=off ls-files | grep -Ei '(^|/)(data|logs)/|(^|/)\.env$|\.session|profile\.json|\.zip$|\.bak$|sqlite' || true)"
if [ -n "$bad_paths" ]; then
    report "личные или служебные файлы:"
    printf '%s\n' "$bad_paths" >&2
fi

# 2. Секреты: api_hash, токены ботов, приватные ключи.
secrets="$(git grep --cached -I -n -E \
    "api_hash[[:space:]]*[:=][[:space:]]*['\"][0-9a-fA-F]{32}['\"]|[0-9]{8,10}:[A-Za-z0-9_-]{35}|BEGIN [A-Z ]*PRIVATE KEY" \
    || true)"
if [ -n "$secrets" ]; then
    report "похоже на секреты:"
    printf '%s\n' "$secrets" >&2
fi

# 3. Адреса электронной почты (разрешён только noreply GitHub).
emails="$(git grep --cached -I -n -E \
    '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+' | grep -v 'users\.noreply\.github\.com' || true)"
if [ -n "$emails" ]; then
    report "адреса электронной почты:"
    printf '%s\n' "$emails" >&2
fi

# 4. Запретные слова из ~/.candy-forbidden (в содержимом и в именах файлов).
FORBIDDEN_FILE="${PUBLISH_FORBIDDEN_FILE:-$HOME/.candy-forbidden}"
if [ -s "$FORBIDDEN_FILE" ]; then
    words="$(git grep --cached -I -n -i -E -f "$FORBIDDEN_FILE" || true)"
    if [ -n "$words" ]; then
        report "запретные слова в файлах:"
        printf '%s\n' "$words" >&2
    fi
    names="$(git -c core.quotepath=off ls-files | grep -i -E -f "$FORBIDDEN_FILE" || true)"
    if [ -n "$names" ]; then
        report "запретные слова в именах файлов:"
        printf '%s\n' "$names" >&2
    fi
elif [ "${PUBLISH_ALLOW_NO_FORBIDDEN:-0}" != "1" ]; then
    if [ "$DRY" -eq 1 ]; then
        say "Предупреждение: нет файла $FORBIDDEN_FILE, проверка запретных слов пропущена."
    else
        die "нет файла запретных слов $FORBIDDEN_FILE. Создайте его (по слову или регулярному выражению в строке), например:
  printf '%s\n' 'слово1' 'слово2' > ~/.candy-forbidden"
    fi
fi

[ "$FOUND" -eq 0 ] || die "в публикуемых файлах найдены личные данные (см. выше). Ничего не отправлено."
say "Проверки пройдены: секретов, почты и запретных слов нет."

# --- Коммит и тег --------------------------------------------------------------------
if [ "$MODE" = release ] && git diff --cached --quiet; then
    die "в проекте нет изменений относительно опубликованной версии. Нечего выпускать."
fi
git commit -q -m "Candy Userbot ${VERSION}"
git tag "v${VERSION}"

# Проверяем, что автор и коммиттер действительно анонимны.
identities="$(git log --format='%an <%ae>%n%cn <%ce>' | sort -u)"
expected="${AUTHOR_NAME} <${AUTHOR_EMAIL}>"
if [ "$identities" != "$expected" ]; then
    die "в коммите неожиданный автор: $identities (ожидался $expected)."
fi
say "Автор коммита: $expected"

# --- Отправка ------------------------------------------------------------------------
if [ "$DRY" -eq 1 ]; then
    say ""
    say "Пробный запуск: ничего не отправлено. Готовая копия: $WORK"
    exit 0
fi

if [ "$MODE" = release ]; then
    say "Отправляю обновление ${VERSION} в $REPO..."
    git push -q origin main
    git push -q origin "v${VERSION}"
    say ""
    say "Готово: версия ${VERSION} опубликована. Пользователи получат её командой .update."
    exit 0
fi

command -v gh >/dev/null 2>&1 || die "не найден gh: нечем создать репозиторий."
if gh repo view "$REPO" >/dev/null 2>&1; then
    die "репозиторий $REPO уже существует. Чтобы в нём не осталось старой истории, удалите его на сайте (Settings, Danger Zone, Delete this repository) и запустите скрипт снова. Копия проекта готова: $WORK"
fi

say "Создаю репозиторий $REPO и отправляю код..."
gh repo create "$REPO" --public --source . --remote origin --push \
    --description "Candy Userbot: модульный Telegram userbot на Telethon"
git push -q origin "v${VERSION}"

say ""
say "Готово: https://github.com/${REPO}"
say "Проверьте на GitHub в Settings, Emails: включено «Keep my email addresses private» и «Block command line pushes that expose my email»."
say "В профиле (Settings, Public profile) в поле Name не должно быть настоящего имени."
