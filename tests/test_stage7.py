"""Этап 7: жизненный цикл, остановка, health, файловые логи, --check, run.sh."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tests.test_stage4 as s4
from config.settings import load_settings
from core import doctor
from core.background import BackgroundManager
from core.health import DEGRADED, DOWN, OK, build_health, format_uptime
from core.lifecycle import (
    FAILED,
    NEW,
    RUNNING,
    STARTING,
    STOPPED,
    STOPPING,
    Lifecycle,
    LifecycleError,
)
from core.modules import ModuleManager
from core.shutdown import ShutdownSequence
from core.version import CORE_VERSION
from utils import logger as log_utils

try:
    from core.app import UserbotApp
except ImportError:
    UserbotApp = None

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ lifecycle


class LifecycleTests(unittest.TestCase):
    def test_normal_path(self):
        life = Lifecycle()
        self.assertEqual(life.state, NEW)
        for state in (STARTING, RUNNING, STOPPING, STOPPED):
            life.move(state)
        self.assertEqual(life.history, [NEW, STARTING, RUNNING, STOPPING, STOPPED])
        self.assertTrue(life.is_terminal)

    def test_invalid_transition_raises(self):
        life = Lifecycle()
        with self.assertRaises(LifecycleError):
            life.move(RUNNING)
        with self.assertRaises(LifecycleError):
            life.move("bogus")

    def test_stopped_is_final(self):
        life = Lifecycle()
        life.move(STOPPED)
        self.assertFalse(life.can_move(STARTING))
        self.assertFalse(life.try_move(STARTING))

    def test_try_move_never_raises(self):
        life = Lifecycle()
        self.assertFalse(life.try_move(RUNNING))
        self.assertTrue(life.try_move(STARTING))
        self.assertFalse(life.try_move(STARTING))  # то же состояние: ничего не меняется

    def test_stop_allowed_from_every_active_state(self):
        for path in ([], [STARTING], [STARTING, RUNNING], [STARTING, FAILED]):
            life = Lifecycle()
            for state in path:
                life.move(state)
            life.move(STOPPING)

    def test_uptime_counts_from_running(self):
        now = [100.0]
        life = Lifecycle(clock=lambda: now[0])
        self.assertIsNone(life.uptime)
        life.move(STARTING)
        now[0] = 110.0
        life.move(RUNNING)
        now[0] = 125.5
        self.assertEqual(life.uptime, 15.5)


# ------------------------------------------------------------------- shutdown


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_in_order_with_sync_and_async_steps(self):
        order = []

        async def async_step():
            order.append("b")

        seq = ShutdownSequence(1)
        seq.add("a", lambda: order.append("a"))
        seq.add("b", async_step)
        seq.add("c", lambda: order.append("c"))
        results = await seq.run()
        self.assertEqual(order, ["a", "b", "c"])
        self.assertTrue(all(r.ok for r in results))

    async def test_failure_does_not_stop_the_rest(self):
        order = []

        def broken():
            raise RuntimeError("упал")

        seq = ShutdownSequence(1)
        seq.add("broken", broken)
        seq.add("after", lambda: order.append("after"))
        with self.assertLogs("candy", level="ERROR"):
            results = await seq.run()
        self.assertEqual(order, ["after"])
        self.assertFalse(results[0].ok)
        self.assertIn("упал", results[0].error)
        self.assertTrue(results[1].ok)

    async def test_hanging_step_times_out(self):
        order = []

        async def hang():
            await asyncio.Event().wait()

        seq = ShutdownSequence(0.05)
        seq.add("hang", hang)
        seq.add("after", lambda: order.append("after"))
        with self.assertLogs("candy", level="ERROR"):
            results = await seq.run()
        self.assertTrue(results[0].timed_out)
        self.assertEqual(order, ["after"])

    async def test_zero_timeout_means_no_limit(self):
        async def slow():
            await asyncio.sleep(0.05)

        seq = ShutdownSequence(0)
        seq.add("slow", slow)
        self.assertTrue((await seq.run())[0].ok)

    async def test_cancellation_is_not_swallowed(self):
        async def hang():
            await asyncio.Event().wait()

        seq = ShutdownSequence(5)
        seq.add("hang", hang)
        task = asyncio.ensure_future(seq.run())
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


# --------------------------------------------------------------------- health


def make_health_app(*, modules=(), plugins=(), connected=True, db_open=True, life=None):
    manager = ModuleManager(SimpleNamespace())
    for module in modules:
        manager.register(module)
    return SimpleNamespace(
        lifecycle=life,
        client=SimpleNamespace(is_connected=lambda: connected),
        storage=SimpleNamespace(database=SimpleNamespace(is_open=db_open)),
        modules=manager,
        plugins=SimpleNamespace(states=lambda: list(plugins)),
        background=BackgroundManager(),
    )


def running_life():
    life = Lifecycle()
    life.move(STARTING)
    life.move(RUNNING)
    return life


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_ok(self):
        app = make_health_app(modules=[s4.make_module("a", required=True)], life=running_life())
        await app.modules.start_all()
        report = build_health(app)
        self.assertEqual(report.status, OK)
        self.assertTrue(report.ok)
        self.assertEqual((report.modules_started, report.modules_total), (1, 1))
        self.assertEqual(report.version, CORE_VERSION)
        self.assertIn("работает", report.lines()[0])

    async def test_optional_module_failure_is_degraded(self):
        app = make_health_app(
            modules=[s4.make_module("a"), s4.make_module("bad", start=RuntimeError("упал"))],
            life=running_life(),
        )
        with self.assertLogs("candy", level="ERROR"):
            await app.modules.start_all()
        report = build_health(app)
        self.assertEqual(report.status, DEGRADED)
        self.assertTrue(any("bad" in p and "упал" in p for p in report.problems))

    async def test_required_module_down_is_down(self):
        app = make_health_app(modules=[s4.make_module("core", required=True)], life=running_life())
        # модуль зарегистрирован, но не запущен
        report = build_health(app)
        self.assertEqual(report.status, DOWN)

    async def test_failed_plugin_and_failing_task_are_degraded(self):
        plugin = SimpleNamespace(name="demo", failed=True, loaded=False, error="ImportError")
        app = make_health_app(plugins=[plugin], life=running_life())

        async def broken():
            raise ValueError("x")

        app.background.register("t", broken, interval=0.01)
        with self.assertLogs("candy", level="DEBUG"):
            await app.background.start("t")
            await asyncio.sleep(0.06)
        try:
            report = build_health(app)
        finally:
            await app.background.stop_all()
        self.assertEqual(report.status, DEGRADED)
        self.assertEqual(report.tasks_failing, 1)
        self.assertTrue(any("плагин demo" in p for p in report.problems))

    async def test_no_connection_or_closed_db_is_down(self):
        self.assertEqual(build_health(make_health_app(connected=False, life=running_life())).status, DOWN)
        self.assertEqual(build_health(make_health_app(db_open=False, life=running_life())).status, DOWN)

    async def test_not_running_state_is_down(self):
        life = Lifecycle()
        life.move(STARTING)
        self.assertEqual(build_health(make_health_app(life=life)).status, DOWN)

    async def test_never_raises_on_broken_app(self):
        broken = MagicMock()
        broken.modules.states.side_effect = RuntimeError("x")
        broken.plugins.states.side_effect = RuntimeError("x")
        broken.background.list.side_effect = RuntimeError("x")
        broken.client.is_connected.side_effect = RuntimeError("x")
        report = build_health(broken)
        self.assertEqual(report.status, DOWN)
        self.assertTrue(report.lines())

    def test_format_uptime(self):
        self.assertEqual(format_uptime(5), "5 с")
        self.assertEqual(format_uptime(125), "2 мин 5 с")
        self.assertEqual(format_uptime(3 * 3600 + 120), "3 ч 2 мин")
        self.assertEqual(format_uptime(2 * 86400 + 5 * 3600), "2 д 5 ч")


# ------------------------------------------------------------------- app


@unittest.skipIf(UserbotApp is None, "Telethon не установлен")
class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, tmp, modules, client):
        return s4.AppStartupPolicyTests.make_app(self, tmp, modules, client)

    async def test_full_cycle_and_health(self):
        client = s4.FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [s4.make_module("good", required=True)], client)
            self.assertEqual(app.lifecycle.state, NEW)
            await app.start()
            self.assertEqual(app.lifecycle.state, RUNNING)
            self.assertEqual(app.health().status, OK)
            await app.stop()
            self.assertEqual(app.lifecycle.state, STOPPED)
            self.assertEqual(app.lifecycle.history, [NEW, STARTING, RUNNING, STOPPING, STOPPED])
            self.assertFalse(client.connected)
            self.assertFalse(app.storage.database.is_open)

    async def test_failed_start_ends_failed_then_stopped(self):
        client = s4.FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(
                tmp, [s4.make_module("core", required=True, start=RuntimeError("критично"))], client
            )
            with self.assertLogs("candy", level="ERROR"), self.assertRaises(Exception):
                await app.start()
            self.assertEqual(app.lifecycle.state, FAILED)
            self.assertFalse(client.connected)
            await app.stop()
            self.assertEqual(app.lifecycle.state, STOPPED)

    async def test_stop_is_idempotent(self):
        client = s4.FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [], client)
            await app.start()
            await asyncio.gather(app.stop(), app.stop())
            await app.stop()
            self.assertEqual(client.disconnect.await_count, 1)

    async def test_stop_survives_failing_disconnect_and_storage_still_closes(self):
        client = s4.FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [], client)
            await app.start()
            client.disconnect.side_effect = RuntimeError("сеть")
            with self.assertLogs("candy", level="ERROR"):
                await app.stop()
            self.assertFalse(app.storage.database.is_open)
            self.assertEqual(app.lifecycle.state, STOPPED)

    async def test_status_command_replaces_health(self):
        client = s4.FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp, [], client)
            from modules.system.status import StatusModule

            module = StatusModule(app)
            await module.start()
            edits = []

            async def edit(text):
                edits.append(text)

            await app.dispatcher.dispatch_command(SimpleNamespace(raw_text=".status", edit=edit))
            self.assertIn("Состояние", edits[-1])
            self.assertNotIn("Модули:", edits[-1])  # кратко: подробности только в .status all
            await app.dispatcher.dispatch_command(SimpleNamespace(raw_text=".status all", edit=edit))
            self.assertIn("Модули:", edits[-1])
            self.assertNotIn("health", app.dispatcher.commands)  # .health больше нет
            await module.stop()
            self.assertNotIn("status", app.dispatcher.commands)


# ---------------------------------------------------------------- file logs


class FileLoggingTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(log_utils.disable_file_logging)

    def test_writes_to_file_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = log_utils.setup_file_logging(Path(tmp) / "logs")
            self.assertEqual(path, Path(tmp) / "logs" / "candy.log")
            log_utils.logger.info("привет из теста")
            for handler in log_utils._file_handlers():
                handler.flush()
            self.assertIn("привет из теста", path.read_text(encoding="utf-8"))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            log_utils.disable_file_logging()
            self.assertEqual(log_utils._file_handlers(), [])

    def test_repeated_setup_keeps_single_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_utils.setup_file_logging(Path(tmp))
            log_utils.setup_file_logging(Path(tmp))
            self.assertEqual(len(log_utils._file_handlers()), 1)
            log_utils.disable_file_logging()

    def test_none_disables(self):
        self.assertIsNone(log_utils.setup_file_logging(None))
        self.assertEqual(log_utils._file_handlers(), [])

    def test_unwritable_directory_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            with self.assertLogs("candy", level="WARNING"):
                self.assertIsNone(log_utils.setup_file_logging(blocker / "logs"))
            self.assertEqual(log_utils._file_handlers(), [])

    def test_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = log_utils.setup_file_logging(Path(tmp), max_bytes=1024, backups=2)
            for i in range(200):
                log_utils.logger.info("строка %d %s", i, "x" * 50)
            log_utils.disable_file_logging()
            names = sorted(p.name for p in Path(tmp).iterdir())
            self.assertIn("candy.log.1", names)
            self.assertNotIn("candy.log.3", names)
            self.assertTrue(path.exists())


class LogSettingsTests(unittest.TestCase):
    def load(self, **env):
        return load_settings(env, Path("/base"))

    def test_defaults(self):
        s = self.load()
        self.assertEqual(s.log_dir, Path("/base/logs"))
        self.assertEqual(s.log_backups, 3)
        self.assertEqual(s.stop_timeout, 20.0)
        self.assertEqual(s.warnings, ())

    def test_off_and_custom(self):
        self.assertIsNone(self.load(CANDY_LOG_DIR="off").log_dir)
        self.assertEqual(self.load(CANDY_LOG_DIR="/var/log/c").log_dir, Path("/var/log/c"))
        self.assertEqual(self.load(CANDY_LOG_DIR="mylogs").log_dir, Path("/base/mylogs"))

    def test_invalid_values_fall_back_with_warnings(self):
        s = self.load(CANDY_LOG_MAX_BYTES="abc", CANDY_LOG_BACKUPS="-1", CANDY_STOP_TIMEOUT="-5")
        self.assertEqual((s.log_max_bytes, s.log_backups, s.stop_timeout), (1_000_000, 3, 20.0))
        self.assertEqual(len(s.warnings), 3)

    def test_zero_backups_allowed(self):
        self.assertEqual(self.load(CANDY_LOG_BACKUPS="0").log_backups, 0)


# --------------------------------------------------------------------- doctor


class DoctorTests(unittest.TestCase):
    def run_checks(self, base: Path, *, accounts=None, db_version=None, **env):
        from accounts.manager import AccountManager

        data = base / "data"
        settings = load_settings({"CANDY_DATA_DIR": str(data), **env}, base)
        manager = accounts or AccountManager(settings.accounts_dir)
        with patch.multiple(
            "config.settings",
            DATA_DIR=settings.data_dir,
            DATABASE_DIR=settings.database_dir,
            DATABASE_PATH=settings.database_path,
            settings=settings,
        ):
            return doctor.collect_checks(manager), settings

    def levels(self, checks):
        return [level for level, _ in checks]

    def test_fresh_install_has_no_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks, _ = self.run_checks(Path(tmp), CANDY_LOG_DIR=str(Path(tmp) / "l"))
        self.assertNotIn(doctor.FAIL, [l for l, t in checks if "Telethon" not in t])
        self.assertTrue(any("активного аккаунта нет" in t for _, t in checks))

    def test_exit_code(self):
        out = []
        with patch.object(doctor, "collect_checks", return_value=[(doctor.OK, "a")]):
            self.assertEqual(doctor.run_checks(None, out.append), 0)
        with patch.object(doctor, "collect_checks", return_value=[(doctor.FAIL, "b")]):
            self.assertEqual(doctor.run_checks(None, out.append), 2)
        self.assertTrue(any("не пройдена" in line for line in out))

    def test_database_newer_than_program_fails(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite3"
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            con.execute("INSERT INTO metadata VALUES ('schema_version', '999')")
            con.commit()
            con.close()
            level, text = doctor._database_check(path)
        self.assertEqual(level, doctor.FAIL)
        self.assertIn("новее", text)

    def test_database_garbage_fails_and_missing_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.sqlite3"
            bad.write_bytes(b"not a database" * 100)
            self.assertEqual(doctor._database_check(bad)[0], doctor.FAIL)
            self.assertEqual(doctor._database_check(Path(tmp) / "none.sqlite3")[0], doctor.OK)

    def test_check_does_not_modify_database(self):
        from storage.database import Database

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite3"
            db = Database(path)
            db.open()
            db.close()
            before = path.read_bytes()
            level, _ = doctor._database_check(path)
            self.assertEqual(level, doctor.OK)
            self.assertEqual(path.read_bytes(), before)

    def test_unwritable_log_dir_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "f"
            blocker.write_text("x")
            checks, _ = self.run_checks(Path(tmp), CANDY_LOG_DIR=str(blocker / "logs"))
        self.assertTrue(any(l == doctor.WARN and "логов" in t for l, t in checks))

    def test_active_account_without_session_fails(self):
        from accounts.manager import AccountManager
        from tests.helpers import make_account

        with tempfile.TemporaryDirectory() as tmp:
            accounts_dir = Path(tmp) / "data" / "accounts"
            make_account(accounts_dir, 5)
            manager = AccountManager(accounts_dir)
            manager.load()
            account = manager.list()[0]
            manager.set_active(account)
            account.session_path.unlink()  # сессию удалили уже после загрузки
            with patch.object(manager, "load"):
                checks, _ = self.run_checks(Path(tmp), accounts=manager)
        self.assertTrue(any(l == doctor.FAIL and "сессии" in t for l, t in checks))

    def test_active_account_with_session_ok(self):
        from accounts.manager import AccountManager
        from tests.helpers import make_account

        with tempfile.TemporaryDirectory() as tmp:
            accounts_dir = Path(tmp) / "data" / "accounts"
            make_account(accounts_dir, 5)
            manager = AccountManager(accounts_dir)
            manager.load()
            manager.set_active(manager.list()[0])
            checks, _ = self.run_checks(Path(tmp), accounts=manager)
        self.assertTrue(any(l == doctor.OK and "сессия на месте" in t for l, t in checks))


class MainStage7Tests(unittest.TestCase):
    def test_check_flag_parses_and_is_exclusive(self):
        import main

        self.assertTrue(main.parse_args(["--check"]).check)
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            main.parse_args(["--check", "--add-account"])

    def test_report_codes(self):
        import main
        from core.errors import UserError

        with self.assertLogs("candy", level="ERROR"):
            self.assertEqual(main._report(UserError("x")), main.EXIT_CONFIG)
            self.assertEqual(main._report(EOFError()), main.EXIT_CONFIG)
            self.assertEqual(main._report(RuntimeError("boom")), main.EXIT_ERROR)


class VersionTests(unittest.TestCase):
    def test_core_is_stable_release(self):
        from core.version import at_least

        self.assertTrue(at_least(CORE_VERSION, "1.0"))


# ---------------------------------------------------------------------- run.sh


@unittest.skipUnless(shutil.which("bash") and os.name == "posix", "нужен bash")
class RunScriptTests(unittest.TestCase):
    """Подменяем python скриптом, который отдаёт заранее заданные коды выхода."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(ROOT / "run.sh", self.tmp / "run.sh")
        (self.tmp / "main.py").write_text("")
        self.fake = self.tmp / "fakepython"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'n=$(cat "{self.tmp}/count" 2>/dev/null || echo 0)\n'
            'n=$((n+1)); echo $n > "' + str(self.tmp) + '/count"\n'
            f'code=$(sed -n "${{n}}p" "{self.tmp}/codes")\n'
            'exit "${code:-0}"\n'
        )
        self.fake.chmod(0o755)

    def run_script(self, codes, **env):
        (self.tmp / "codes").write_text("\n".join(map(str, codes)) + "\n")
        full = {**os.environ, "PYTHON": str(self.fake), "CANDY_RESTART_MIN": "0", "CANDY_RESTART_MAX": "0", **env}
        result = subprocess.run(
            ["bash", str(self.tmp / "run.sh")], capture_output=True, text=True, timeout=30, env=full
        )
        runs = int((self.tmp / "count").read_text())
        return result, runs

    def test_clean_exit_is_not_restarted(self):
        result, runs = self.run_script([0])
        self.assertEqual((result.returncode, runs), (0, 1))

    def test_config_error_is_not_restarted(self):
        result, runs = self.run_script([2])
        self.assertEqual((result.returncode, runs), (2, 1))

    def test_forced_exit_is_not_restarted(self):
        result, runs = self.run_script([130])
        self.assertEqual((result.returncode, runs), (130, 1))

    def test_failures_restart_until_clean_exit(self):
        result, runs = self.run_script([1, 1, 0])
        self.assertEqual((result.returncode, runs), (0, 3))
        self.assertIn("перезапуск", result.stderr)

    def test_fast_fail_limit_stops_loop(self):
        result, runs = self.run_script([1, 1, 1, 1, 1], CANDY_MAX_FAST_FAILS="3")
        self.assertEqual((result.returncode, runs), (1, 3))

    def test_sigterm_stops_supervisor_and_child(self):
        import signal
        import time

        hang = self.tmp / "hangpython"
        hang.write_text('#!/bin/sh\ntrap "exit 0" TERM\nwhile true; do sleep 0.1; done\n')
        hang.chmod(0o755)
        env = {**os.environ, "PYTHON": str(hang)}
        proc = subprocess.Popen(["bash", str(self.tmp / "run.sh")], env=env, stderr=subprocess.PIPE)
        time.sleep(0.6)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 0)
        proc.stderr.close()


    def test_stdin_reaches_main_script(self):
        """Регресс: фоновый потомок без <&0 получал /dev/null, и вход в аккаунт был невозможен."""
        reader = self.tmp / "readerpython"
        reader.write_text('#!/bin/sh\nread line\n[ "$line" = secret ] && exit 0\nexit 2\n')
        reader.chmod(0o755)
        env = {**os.environ, "PYTHON": str(reader)}
        result = subprocess.run(
            ["bash", str(self.tmp / "run.sh")], input="secret\n", capture_output=True,
            text=True, timeout=20, env=env,
        )
        self.assertEqual(result.returncode, 0)

    def test_sigint_to_process_group_sends_child_a_single_signal(self):
        """Ctrl+C приходит и супервизору, и потомку: потомок не должен получить ещё и SIGTERM."""
        import signal
        import sys
        import time

        marker = self.tmp / "got_term"
        # Настоящий Python: фоновые потомки неинтерактивного bash стартуют с игнорируемым SIGINT,
        # и только свой обработчик (как у main.py) это переопределяет.
        (self.tmp / "main.py").write_text(
            "import signal, sys, time, pathlib\n"
            "def on_int(*a): sys.exit(0)\n"
            f"def on_term(*a): pathlib.Path({str(marker)!r}).touch(); sys.exit(1)\n"
            "signal.signal(signal.SIGINT, on_int)\n"
            "signal.signal(signal.SIGTERM, on_term)\n"
            "print('ready', flush=True)\n"
            "while True: time.sleep(0.05)\n"
        )
        env = {**os.environ, "PYTHON": sys.executable}
        proc = subprocess.Popen(
            ["bash", str(self.tmp / "run.sh")], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        self.addCleanup(lambda: proc.poll() is None and os.killpg(proc.pid, signal.SIGKILL))
        proc.stdout.readline()  # дождались «ready»: обработчики уже стоят
        time.sleep(0.2)
        os.killpg(proc.pid, signal.SIGINT)
        self.assertEqual(proc.wait(timeout=10), 0)
        proc.stdout.close()
        proc.stderr.close()
        self.assertFalse(marker.exists())


class DeployFilesTests(unittest.TestCase):
    @staticmethod
    def _fs_supports_exec_bit() -> bool:
        """На общем хранилище Android (/sdcard) chmod не действует: бит x выставить нельзя."""
        try:
            with tempfile.NamedTemporaryFile(dir=ROOT) as probe:
                os.chmod(probe.name, 0o755)
                return os.access(probe.name, os.X_OK)
        except OSError:
            return False

    def test_run_script_is_executable_and_syntax_ok(self):
        if self._fs_supports_exec_bit():
            self.assertTrue(os.access(ROOT / "run.sh", os.X_OK))
        if shutil.which("bash"):
            self.assertEqual(subprocess.run(["bash", "-n", str(ROOT / "run.sh")]).returncode, 0)

    def test_systemd_unit_does_not_restart_config_errors(self):
        text = (ROOT / "deploy" / "candy-userbot.service").read_text(encoding="utf-8")
        self.assertIn("Restart=on-failure", text)
        self.assertIn("RestartPreventExitStatus=2", text)


if __name__ == "__main__":
    unittest.main()
