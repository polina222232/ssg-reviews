#!/usr/bin/env python3
"""
push.py — умная загрузка проекта SSG Review на GitHub.

Что делает:
    1. Проверяет, что git установлен и папка — git-репозиторий
    2. Проверяет, что настроен remote origin
    3. Смотрит локальные изменения (git status --short)
    4. Делает git fetch и сравнивает: ahead / behind
    5. Если GitHub ушёл вперёд — предлагает git pull
    6. Показывает diff перед коммитом
    7. Спрашивает сообщение коммита (или авто)
    8. Делает git add -A, git commit, git push
    9. Красивый цветной вывод

Запуск:
    python scripts/push.py
    python scripts/push.py --auto        # без вопросов, авто-сообщение
    python scripts/push.py --dry-run     # только показать, ничего не делать
    python scripts/push.py --yes         # не спрашивать подтверждения
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------- Конфигурация ----------
REPO_URL = "https://github.com/polina222232/ssg-review"
ROOT = Path(__file__).resolve().parent.parent  # корень проекта

# ---------- Цвета ----------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def supports_color() -> bool:
    """Проверяет, поддерживает ли терминал ANSI-цвета."""
    if os.name == "nt":
        # Включаем ANSI в Windows 10+
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return sys.stdout.isatty()


if not supports_color():
    for attr in dir(C):
        if not attr.startswith("_"):
            setattr(C, attr, "")


# ---------- Логирование ----------
def title(msg: str) -> None:
    print(f"{C.MAGENTA}{msg}{C.RESET}")


def step(n: str, msg: str) -> None:
    print(f"\n{C.CYAN}[{n}]{C.RESET} {C.BOLD}{msg}{C.RESET}")


def ok(msg: str) -> None:
    print(f"  {C.GREEN}OK{C.RESET}  {msg}")


def info(msg: str) -> None:
    print(f"  {C.YELLOW}i{C.RESET}   {msg}")


def warn(msg: str) -> None:
    print(f"  {C.YELLOW}!{C.RESET}   {msg}")


def err(msg: str) -> None:
    print(f"  {C.RED}ОШИБКА{C.RESET} {msg}")


def gray(msg: str) -> None:
    print(f"{C.GRAY}{msg}{C.RESET}")


# ---------- Git-обёртки ----------
def run_git(args: list[str], capture: bool = True, check: bool = False) -> str:
    """
    Запускает git-команду.

    Args:
        args: список аргументов, например ['status', '--short']
        capture: захватывать ли stdout (иначе — печатать сразу)
        check: бросать ли исключение при ошибке

    Returns:
        Вывод команды (если capture=True), иначе пустая строка.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=ROOT,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        err("git не найден. Установи: https://git-scm.com/download/win")
        sys.exit(1)

    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"git {' '.join(args)} — код {result.returncode}\n{stderr}")

    return (result.stdout or "").strip() if capture else ""


def run_git_live(args: list[str]) -> int:
    """Запускает git с выводом в реальном времени (для pull/push)."""
    result = subprocess.run(["git"] + args, cwd=ROOT)
    return result.returncode


# ---------- Логика ----------
def ensure_git_repo() -> None:
    """Проверяет, что мы в git-репозитории."""
    if not (ROOT / ".git").exists():
        err(f"Это не git-репозиторий: {ROOT}")
        print(f"     Выполни один раз:")
        gray(f"       git init")
        gray(f"       git branch -M main")
        gray(f"       git remote add origin {REPO_URL}.git")
        sys.exit(1)
    ok(f"Репозиторий найден: {ROOT}")


def ensure_remote() -> None:
    """Проверяет, что origin настроен и указывает на нужный URL."""
    remotes = run_git(["remote", "-v"])
    if "origin" not in remotes:
        err("Remote 'origin' не настроен.")
        gray(f"       git remote add origin {REPO_URL}.git")
        sys.exit(1)

    m = re.search(r"origin\s+(\S+)", remotes)
    url = m.group(1) if m else "(неизвестно)"
    ok(f"Remote origin: {url}")


def get_branch() -> str:
    """Возвращает имя текущей ветки."""
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return branch or "main"


def get_local_changes() -> str:
    """Возвращает вывод git status --porcelain."""
    return run_git(["status", "--porcelain"])


def has_remote_branch(branch: str) -> bool:
    """Есть ли ветка на origin."""
    result = run_git(["ls-remote", "--heads", "origin", branch])
    return bool(result.strip())


def get_ahead_behind(branch: str) -> tuple[int, int]:
    """Возвращает (ahead, behind) относительно origin/branch."""
    if not has_remote_branch(branch):
        return (0, 0)

    ahead_str = run_git(["rev-list", f"origin/{branch}..HEAD", "--count"])
    behind_str = run_git(["rev-list", f"HEAD..origin/{branch}", "--count"])

    try:
        ahead = int(ahead_str or 0)
    except ValueError:
        ahead = 0
    try:
        behind = int(behind_str or 0)
    except ValueError:
        behind = 0

    return (ahead, behind)


def show_short_status() -> None:
    """Красиво печатает git status --short с цветами."""
    output = run_git(["status", "--short"])
    if not output:
        return

    color_map = {
        "M": C.YELLOW,   # modified
        "A": C.GREEN,    # added
        "D": C.RED,      # deleted
        "R": C.CYAN,     # renamed
        "C": C.CYAN,     # copied
        "U": C.MAGENTA,  # unmerged
        "?": C.GRAY,     # untracked
        "!": C.GRAY,     # ignored
    }

    for line in output.splitlines():
        code = line[:2].strip() or "?"
        color = color_map.get(code[0], "")
        print(f"    {color}{line}{C.RESET}")


def show_diff_stat() -> None:
    """Показывает статистику изменений (git diff --stat)."""
    output = run_git(["diff", "--stat", "HEAD"])
    if output:
        print()
        gray("    ── Изменения в файлах ──")
        for line in output.splitlines():
            print(f"    {line}")
        print()


def ask(question: str, default: str = "") -> str:
    """Спрашивает у пользователя с опциональным дефолтом."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{C.CYAN}?{C.RESET}   {question}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        info("Прервано пользователем")
        sys.exit(0)
    return answer or default


def confirm(question: str, default: bool = False) -> bool:
    """Yes/No-вопрос."""
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{C.CYAN}?{C.RESET}   {question} [{hint}]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    if not answer:
        return default
    return answer in ("y", "yes", "д", "да")


# ---------- Основная процедура ----------
def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка SSG Review на GitHub")
    parser.add_argument("--auto", action="store_true",
                        help="Без вопросов, авто-сообщение коммита")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Подтверждать всё автоматически")
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать, что будет сделано, ничего не менять")
    parser.add_argument("-m", "--message", type=str, default="",
                        help="Сообщение коммита")
    args = parser.parse_args()

    title("=" * 60)
    title("  SSG Review — загрузка на GitHub")
    title(f"  {REPO_URL}")
    title("=" * 60)

    # ---------- 0. Окружение ----------
    step("0/6", "Проверка окружения")
    ensure_git_repo()
    ensure_remote()

    branch = get_branch()
    info(f"Ветка: {branch}")

    # ---------- 1. Локальные изменения ----------
    step("1/6", "Локальные изменения")
    status = get_local_changes()
    has_local = bool(status)

    if has_local:
        info("Найдены изменения:")
        print()
        show_short_status()
        show_diff_stat()
    else:
        ok("Локальных изменений нет")

    # ---------- 2. Состояние GitHub ----------
    step("2/6", "Проверка GitHub")
    info("git fetch origin…")

    rc = run_git_live(["fetch", "origin", branch, "--quiet"])
    if rc != 0:
        warn("git fetch завершился с предупреждением — продолжаю")

    if not has_remote_branch(branch):
        warn(f"Ветка origin/{branch} отсутствует — это первый push")
        ahead, behind = 0, 0
    else:
        ahead, behind = get_ahead_behind(branch)

    info(f"Локально впереди: {ahead} коммит(ов)")
    info(f"На GitHub новых:  {behind} коммит(ов)")

    # ---------- 3. Pull если нужно ----------
    if behind > 0:
        step("3/6", "На GitHub есть новые коммиты")
        warn(f"origin/{branch} ушёл вперёд на {behind} коммит(ов)")

        print()
        gray("    ── Новые коммиты на GitHub ──")
        log = run_git(["log", f"HEAD..origin/{branch}", "--oneline"])
        for line in log.splitlines():
            print(f"    {C.CYAN}{line}{C.RESET}")
        print()

        if args.dry_run:
            info("[dry-run] Пропускаю git pull")
        elif args.yes or args.auto or confirm("Выполнить git pull?"):
            print()
            rc = run_git_live(["pull", "origin", branch])
            if rc != 0:
                err("git pull завершился с ошибкой — реши конфликты вручную")
                return 1
            ok("Изменения подтянуты")
        else:
            info("Прервано пользователем")
            return 0

    # ---------- 4. Если нечего пушить ----------
    if not has_local and ahead == 0 and behind == 0:
        print()
        title("=" * 60)
        title("  Всё синхронизировано. Загружать нечего.")
        title("=" * 60)
        return 0

    # ---------- 5. Коммит ----------
    if has_local:
        step("4/6", "Подготовка коммита")

        if args.dry_run:
            info("[dry-run] git add -A пропущен")
        else:
            run_git_live(["add", "-A"])
            ok("Файлы добавлены (git add -A)")

        default_msg = args.message or f"update: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        if args.auto or args.yes:
            msg = default_msg
        else:
            msg = ask("Сообщение коммита", default=default_msg)

        if not msg:
            msg = default_msg

        info(f"Сообщение: {msg}")

        if args.dry_run:
            info("[dry-run] git commit пропущен")
        else:
            rc = run_git_live(["commit", "-m", msg])
            if rc != 0:
                warn("Коммит не создан (возможно, нечего коммитить)")
            else:
                ok("Коммит создан")

        step("5/6", "Коммит готов")
    else:
        step("4/6", "Локальных изменений нет — коммит не нужен")
        step("5/6", "Пропущено")

    # ---------- 6. Push ----------
    step("6/6", "Отправка на GitHub")

    if args.dry_run:
        info(f"[dry-run] git push origin {branch} пропущен")
        print()
        title("=" * 60)
        title("  DRY-RUN завершён — ничего не изменено")
        title("=" * 60)
        return 0

    rc = run_git_live(["push", "origin", branch])
    if rc != 0:
        err("git push завершился с ошибкой")
        print()
        gray("    Возможные причины:")
        gray("      • нет прав на репозиторий")
        gray("      • устарел Personal Access Token")
        gray("      • нужен git pull (кто-то коммитил параллельно)")
        return 1

    # ---------- Финал ----------
    print()
    title("=" * 60)
    title("  ГОТОВО! Изменения загружены на GitHub")
    title(f"  {REPO_URL}")
    title("=" * 60)

    # Показываем последний коммит
    print()
    last = run_git(["log", "-1", "--pretty=format:%h  %an  %ar%n%s"])
    if last:
        for line in last.splitlines():
            print(f"  {line}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        info("Прервано")
        sys.exit(130)
    except Exception as e:
        err(str(e))
        sys.exit(1)