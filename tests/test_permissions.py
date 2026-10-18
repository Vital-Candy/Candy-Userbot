"""Этап 5: уровни доступа, require(), открытые команды, .perm."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.access import AccessService, require
from core.dispatcher import Dispatcher
from core.reply import answer
from modules.permissions.module import PermissionsModule
from storage.permissions import PermissionLevel
from storage.service import Storage

try:
    from core.events import EventBridge
except ImportError:  # Telethon не установлен
    EventBridge = None

OWNER = 1
FRIEND = 100
STRANGER = 200


class Fixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "candy.sqlite3")
        self.storage.open()
        self.identity = SimpleNamespace(account_id=AsyncMock(return_value=OWNER))
        self.app = SimpleNamespace(
            dispatcher=Dispatcher(),
            storage=self.storage,
            identity=self.identity,
            access=AccessService(self.storage.permissions, self.identity),
        )

    def grant(self, subject, level):
        self.storage.permissions.grant(
            account_id=OWNER, subject_id=subject, permission=level, granted_by=OWNER
        )

    def close(self):
        self.storage.close()
        self.tmp.cleanup()


class LevelTests(unittest.TestCase):
    def test_ordering(self):
        U, T, A = PermissionLevel.USER, PermissionLevel.TRUSTED, PermissionLevel.ADMIN
        self.assertTrue(A > T > U)
        self.assertTrue(A >= A and T <= T and U < A and A >= U)
        self.assertFalse(U >= T)
        self.assertEqual([A, U, T].__len__(), 3)
        self.assertEqual(sorted([A, U, T]), [U, T, A])
        self.assertEqual(PermissionLevel("admin"), A)

    def test_comparison_with_foreign_type_is_not_supported(self):
        with self.assertRaises(TypeError):
            PermissionLevel.USER < 3  # noqa: B015


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.store = self.fx.storage.permissions

    def tearDown(self):
        self.fx.close()

    def test_highest_level(self):
        self.assertEqual(self.store.highest_level(account_id=OWNER, subject_id=FRIEND), PermissionLevel.USER)
        self.fx.grant(FRIEND, "trusted")
        self.assertEqual(self.store.highest_level(account_id=OWNER, subject_id=FRIEND), PermissionLevel.TRUSTED)
        self.fx.grant(FRIEND, "admin")
        self.assertEqual(self.store.highest_level(account_id=OWNER, subject_id=FRIEND), PermissionLevel.ADMIN)
        self.store.revoke(account_id=OWNER, subject_id=FRIEND, permission="admin")
        self.assertEqual(self.store.highest_level(account_id=OWNER, subject_id=FRIEND), PermissionLevel.TRUSTED)

    def test_unknown_stored_permission_never_raises_rights(self):
        self.fx.storage.database.execute(
            "INSERT INTO permissions(account_id, subject_id, permission, granted_by, created_at) "
            "VALUES(?, ?, 'superuser', 1, '2026-01-01T00:00:00+00:00')",
            (OWNER, FRIEND),
        )
        self.assertEqual(self.store.highest_level(account_id=OWNER, subject_id=FRIEND), PermissionLevel.USER)

    def test_grant_is_upsert(self):
        self.fx.grant(FRIEND, "trusted")
        self.fx.grant(FRIEND, "trusted")
        self.assertEqual(len(self.store.list_all(account_id=OWNER)), 1)

    def test_invalid_level_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.grant(account_id=OWNER, subject_id=FRIEND, permission="root", granted_by=OWNER)

    def test_revoke_all_and_list_all_ordering(self):
        self.fx.grant(FRIEND, "trusted")
        self.fx.grant(FRIEND, "admin")
        self.fx.grant(50, "trusted")
        self.assertEqual([(p.subject_id, p.permission) for p in self.store.list_all(account_id=OWNER)],
                         [(50, "trusted"), (FRIEND, "admin"), (FRIEND, "trusted")])
        self.assertEqual(self.store.revoke_all(account_id=OWNER, subject_id=FRIEND), 2)
        self.assertEqual(self.store.revoke_all(account_id=OWNER, subject_id=FRIEND), 0)
        self.assertEqual(len(self.store.list_all(account_id=OWNER)), 1)

    def test_accounts_are_isolated(self):
        self.fx.grant(FRIEND, "admin")
        self.assertEqual(self.store.list_all(account_id=2), [])
        self.assertEqual(self.store.highest_level(account_id=2, subject_id=FRIEND), PermissionLevel.USER)


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.access = self.fx.app.access

    async def asyncTearDown(self):
        self.fx.close()

    async def test_owner_is_admin_without_database_record(self):
        self.assertEqual(self.fx.storage.permissions.list_all(account_id=OWNER), [])
        self.assertEqual(await self.access.level_of(OWNER), PermissionLevel.ADMIN)
        self.assertTrue(await self.access.has_level(OWNER, "admin"))

    async def test_levels(self):
        self.fx.grant(FRIEND, "trusted")
        self.assertEqual(await self.access.level_of(FRIEND), PermissionLevel.TRUSTED)
        self.assertEqual(await self.access.level_of(STRANGER), PermissionLevel.USER)
        self.assertTrue(await self.access.has_level(FRIEND, "trusted"))
        self.assertTrue(await self.access.has_level(FRIEND, PermissionLevel.USER))
        self.assertFalse(await self.access.has_level(FRIEND, "admin"))

    async def test_rights_follow_the_active_account(self):
        self.fx.grant(FRIEND, "admin")
        self.fx.identity.account_id.return_value = 2  # другой аккаунт: чужие права не действуют
        self.assertEqual(await self.access.level_of(FRIEND), PermissionLevel.USER)


class RequireFilterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.fx.grant(FRIEND, "trusted")

    async def asyncTearDown(self):
        self.fx.close()

    def event(self, sender, out=False):
        return SimpleNamespace(sender_id=sender, out=out)

    async def test_owner_outgoing_always_passes(self):
        check = require(self.fx.app, "admin")
        self.assertTrue(await check(self.event(None, out=True)))
        self.assertTrue(await check(self.event(OWNER)))  # собственный id и без out

    async def test_levels_are_enforced(self):
        trusted = require(self.fx.app, "trusted")
        admin = require(self.fx.app, PermissionLevel.ADMIN)
        self.assertTrue(await trusted(self.event(FRIEND)))
        self.assertFalse(await admin(self.event(FRIEND)))
        self.assertFalse(await trusted(self.event(STRANGER)))

    async def test_user_level_lets_everyone_with_sender(self):
        self.assertTrue(await require(self.fx.app, "user")(self.event(STRANGER)))

    async def test_missing_sender_is_denied(self):
        self.assertFalse(await require(self.fx.app, "user")(self.event(None)))
        self.assertFalse(await require(self.fx.app, "user")(SimpleNamespace()))

    async def test_missing_access_service_denies(self):
        app = SimpleNamespace()
        self.assertFalse(await require(app, "trusted")(self.event(FRIEND)))

    async def test_error_in_check_denies(self):
        self.fx.app.access.has_level = AsyncMock(side_effect=RuntimeError("db gone"))
        with self.assertLogs("candy", level="ERROR"):
            self.assertFalse(await require(self.fx.app, "trusted")(self.event(FRIEND)))

    async def test_invalid_level_name_fails_at_creation(self):
        with self.assertRaises(ValueError):
            require(self.fx.app, "root")

    async def test_filter_is_found_by_name_in_logs(self):
        self.assertEqual(require(self.fx.app, "trusted").__name__, "require_trusted")

    async def test_access_created_after_filter_is_still_used(self):
        app = SimpleNamespace(access=None)
        check = require(app, "trusted")
        self.assertFalse(await check(self.event(FRIEND)))
        app.access = self.fx.app.access
        self.assertTrue(await check(self.event(FRIEND)))


def make_event(text, sender=None, out=False, reply_sender=None):
    sent: list[tuple[str, str]] = []

    async def edit(value):
        sent.append(("edit", value))

    async def reply(value):
        sent.append(("reply", value))

    async def respond(value):
        sent.append(("respond", value))

    reply_message = SimpleNamespace(sender_id=reply_sender) if reply_sender is not None else None
    event = SimpleNamespace(
        raw_text=text,
        sender_id=sender,
        out=out,
        edit=edit,
        reply=reply,
        respond=respond,
        get_reply_message=AsyncMock(return_value=reply_message),
        sent=sent,
    )
    return event


class IncomingCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.fx.grant(FRIEND, "trusted")
        self.dispatcher = self.fx.app.dispatcher
        self.calls: list[str] = []

        async def handler(event):
            self.calls.append(event.raw_text)
            await answer(event, "ok")

        self.handler = handler

    async def asyncTearDown(self):
        self.fx.close()

    async def test_commands_are_not_open_by_default(self):
        self.dispatcher.register_command("secret", self.handler)
        event = make_event(".secret", sender=STRANGER, out=False)
        await self.dispatcher.dispatch_command(event, incoming=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(event.sent, [])

    async def test_open_command_requires_filters(self):
        with self.assertRaises(ValueError):
            self.dispatcher.register_command("open", self.handler, allow_incoming=True)

    async def test_open_command_obeys_require(self):
        self.dispatcher.register_command(
            "ping", self.handler, allow_incoming=True, filters=(require(self.fx.app, "trusted"),)
        )
        stranger = make_event(".ping", sender=STRANGER)
        friend = make_event(".ping", sender=FRIEND)
        await self.dispatcher.dispatch_command(stranger, incoming=True)
        await self.dispatcher.dispatch_command(friend, incoming=True)
        self.assertEqual(self.calls, [".ping"])
        self.assertEqual(stranger.sent, [])
        self.assertEqual(friend.sent, [("reply", "ok")])  # чужое сообщение не правим, а отвечаем на него

    async def test_own_message_is_still_edited(self):
        self.dispatcher.register_command("mine", self.handler)
        event = make_event(".mine", sender=OWNER, out=True)
        await self.dispatcher.dispatch_command(event)
        self.assertEqual(event.sent, [("edit", "ok")])

    async def test_incoming_flag_never_runs_closed_commands_even_for_trusted(self):
        self.dispatcher.register_command("closed", self.handler)
        await self.dispatcher.dispatch_command(make_event(".closed", sender=FRIEND), incoming=True)
        self.assertEqual(self.calls, [])

    async def test_open_command_flag_is_recorded(self):
        command = self.dispatcher.register_command(
            "p", self.handler, allow_incoming=True, filters=(require(self.fx.app, "trusted"),)
        )
        self.assertTrue(command.allow_incoming)
        self.assertFalse(self.dispatcher.register_command("q", self.handler).allow_incoming)

    @unittest.skipIf(EventBridge is None, "Telethon не установлен")
    async def test_bridge_routes_incoming_messages_to_open_commands_only(self):
        client = SimpleNamespace(add_event_handler=lambda *a: None, remove_event_handler=lambda *a: None)
        bridge = EventBridge(client, self.dispatcher)
        self.dispatcher.register_command("closed", self.handler)
        self.dispatcher.register_command(
            "ping", self.handler, allow_incoming=True, filters=(require(self.fx.app, "trusted"),)
        )
        await bridge._new_message(make_event(".closed", sender=FRIEND))
        await bridge._new_message(make_event(".ping", sender=STRANGER))
        await bridge._new_message(make_event(".ping", sender=FRIEND))
        await bridge._new_message(make_event(".closed", sender=OWNER, out=True))
        self.assertEqual(self.calls, [".ping", ".closed"])


class PermCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = Fixture()
        self.module = PermissionsModule(self.fx.app)
        await self.module.start()

    async def asyncTearDown(self):
        self.fx.close()

    async def run_cmd(self, text, *, sender=OWNER, out=True, reply_sender=None):
        event = make_event(text, sender=sender, out=out, reply_sender=reply_sender)
        await self.fx.app.dispatcher.dispatch_command(event)
        return event.sent[-1][1] if event.sent else None

    def level(self, subject):
        return self.fx.storage.permissions.highest_level(account_id=OWNER, subject_id=subject)

    async def test_grant_by_id_and_by_reply(self):
        self.assertIn("trusted", await self.run_cmd(".perm grant 100 trusted"))
        self.assertEqual(self.level(100), PermissionLevel.TRUSTED)
        self.assertIn("admin", await self.run_cmd(".perm grant admin", reply_sender=300))
        self.assertEqual(self.level(300), PermissionLevel.ADMIN)

    async def test_grant_errors(self):
        self.assertIn("укажите уровень", await self.run_cmd(".perm grant 100"))
        self.assertIn("trusted и admin", await self.run_cmd(".perm grant 100 user"))
        self.assertIn("числовой ID", await self.run_cmd(".perm grant @name trusted"))
        self.assertIn("укажите ID", await self.run_cmd(".perm grant trusted"))
        self.assertIn("положительным", await self.run_cmd(".perm grant -5 trusted"))
        self.assertIn("и так имеет", await self.run_cmd(f".perm grant {OWNER} admin"))
        self.assertIn("Использование", await self.run_cmd(".perm grant 1 2 trusted"))
        self.assertEqual(self.fx.storage.permissions.list_all(account_id=OWNER), [])

    async def test_revoke_one_level_or_all(self):
        await self.run_cmd(".perm grant 100 trusted")
        await self.run_cmd(".perm grant 100 admin")
        self.assertIn("admin снят", await self.run_cmd(".perm revoke 100 admin"))
        self.assertEqual(self.level(100), PermissionLevel.TRUSTED)
        self.assertIn("нет уровня", await self.run_cmd(".perm revoke 100 admin"))
        self.assertIn("все права сняты", await self.run_cmd(".perm revoke 100"))
        self.assertIn("нет выданных", await self.run_cmd(".perm revoke 100"))
        self.assertEqual(self.level(100), PermissionLevel.USER)

    async def test_owner_rights_cannot_be_revoked(self):
        self.assertIn("владельца", await self.run_cmd(f".perm revoke {OWNER}"))

    async def test_list(self):
        self.assertIn("всегда admin", await self.run_cmd(".perm list"))
        await self.run_cmd(".perm grant 100 trusted")
        listing = await self.run_cmd(".perm list")
        self.assertIn("100 — trusted", listing)
        single = await self.run_cmd(".perm list 100")
        self.assertIn("trusted", single)
        self.assertIn("записей нет", await self.run_cmd(".perm list 999"))
        self.assertIn("admin", await self.run_cmd(f".perm list {OWNER}"))

    async def test_usage(self):
        for text in (".perm", ".perm wat", ".perm list 1 2", ".perm grant 1 2 3 4"):
            self.assertIn("Использование", await self.run_cmd(text), text)

    async def test_only_admin_can_run_it(self):
        # Даже если бы команду открыли, доверенный пользователь не админ.
        self.fx.grant(FRIEND, "trusted")
        event = make_event(".perm grant 5 admin", sender=FRIEND, out=False)
        await self.fx.app.dispatcher.dispatch_command(event, incoming=True)
        self.assertEqual(event.sent, [])
        event = make_event(".perm grant 5 admin", sender=FRIEND, out=False)
        await self.fx.app.dispatcher.dispatch_command(event)  # прямой вызов без incoming
        self.assertEqual(event.sent, [])  # require отказал
        self.assertEqual(self.level(5), PermissionLevel.USER)

    async def test_stop_unregisters(self):
        await self.module.stop()
        self.assertNotIn("perm", self.fx.app.dispatcher.commands)

    async def test_module_is_optional(self):
        self.assertFalse(PermissionsModule.required)


if __name__ == "__main__":
    unittest.main()
