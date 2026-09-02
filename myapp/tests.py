"""Права на вкладку «Рационы Claude».

Ограниченный редактор — читатель с галочкой «Может вести рационы Claude»:
правит только свои группы и рационы плюс группы, отмеченные shared_editing
(это группы ДИАБЕТ). Чужое остаётся только для чтения, остальные вкладки —
как у обычного читателя.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import ClaudeRation, ClaudeRationGroup, UserRights
from .roles import READERS_GROUP, can_edit_claude_group, can_edit_claude_ration


class ClaudeEditorRightsTests(TestCase):
    def setUp(self):
        readers, _ = Group.objects.get_or_create(name=READERS_GROUP)

        self.limited = User.objects.create_user("roman", password="x")
        self.limited.groups.add(readers)
        UserRights.objects.create(user=self.limited, can_edit_claude_rations=True)

        self.plain_reader = User.objects.create_user("saule", password="x")
        self.plain_reader.groups.add(readers)

        self.editor = User.objects.create_user("adil", password="x")  # не читатель

        self.diabet = ClaudeRationGroup.objects.create(
            name="ДИАБЕТ 1800", shared_editing=True,
        )
        self.foreign = ClaudeRationGroup.objects.create(name="Рационы 1200 (тест)")
        self.own = ClaudeRationGroup.objects.create(
            name="Моя группа", created_by=self.limited,
        )

        self.foreign_ration = ClaudeRation.objects.create(
            group=self.foreign, name="Чужой рацион", kcal_category=1200,
        )
        self.own_ration = ClaudeRation.objects.create(
            group=self.own, name="Свой рацион", kcal_category=1200,
            created_by=self.limited,
        )
        self.diabet_ration = ClaudeRation.objects.create(
            group=self.diabet, name="Диабет рацион", kcal_category=1800,
        )

    # ── правила доступа ──────────────────────────────────────────────────────

    def test_limited_editor_scope(self):
        self.assertTrue(can_edit_claude_group(self.limited, self.diabet))
        self.assertTrue(can_edit_claude_group(self.limited, self.own))
        self.assertFalse(can_edit_claude_group(self.limited, self.foreign))

        self.assertTrue(can_edit_claude_ration(self.limited, self.own_ration))
        self.assertTrue(can_edit_claude_ration(self.limited, self.diabet_ration))
        self.assertFalse(can_edit_claude_ration(self.limited, self.foreign_ration))

    def test_plain_reader_has_no_access(self):
        self.assertFalse(can_edit_claude_group(self.plain_reader, self.diabet))
        self.assertFalse(can_edit_claude_ration(self.plain_reader, self.diabet_ration))

    def test_editor_edits_everything_including_limited_editors_work(self):
        for group in (self.diabet, self.foreign, self.own):
            self.assertTrue(can_edit_claude_group(self.editor, group))
        for ration in (self.own_ration, self.foreign_ration, self.diabet_ration):
            self.assertTrue(can_edit_claude_ration(self.editor, ration))

    # ── запросы ──────────────────────────────────────────────────────────────

    def test_limited_editor_cannot_touch_foreign_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_delete", args=[self.foreign_ration.pk])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(ClaudeRation.objects.filter(pk=self.foreign_ration.pk).exists())

    def test_limited_editor_deletes_own_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_delete", args=[self.own_ration.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ClaudeRation.objects.filter(pk=self.own_ration.pk).exists())

    def test_limited_editor_edits_diabet_group(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_group_edit", args=[self.diabet.pk]),
            {"name": "ДИАБЕТ 1800 (правка)", "description": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.diabet.refresh_from_db()
        self.assertEqual(self.diabet.name, "ДИАБЕТ 1800 (правка)")

    def test_limited_editor_cannot_edit_foreign_group(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_group_edit", args=[self.foreign.pk]),
            {"name": "Переименовал чужое", "description": ""},
        )
        self.assertEqual(resp.status_code, 403)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.name, "Рационы 1200 (тест)")

    def test_created_group_belongs_to_author(self):
        self.client.force_login(self.limited)
        self.client.post(reverse("claude_group_create"), {"name": "Новая", "description": ""})
        created = ClaudeRationGroup.objects.get(name="Новая")
        self.assertEqual(created.created_by, self.limited)
        self.assertTrue(can_edit_claude_group(self.limited, created))

    def test_plain_reader_blocked_by_middleware(self):
        self.client.force_login(self.plain_reader)
        resp = self.client.post(reverse("claude_group_create"), {"name": "Нельзя"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ClaudeRationGroup.objects.filter(name="Нельзя").exists())

    def test_limited_editor_still_blocked_outside_claude(self):
        """Право открывает только вкладку Claude — калоражи остаются закрыты."""
        self.client.force_login(self.limited)
        resp = self.client.post(reverse("calorie_create"), {"name": "1300", "kcal": 1300})
        self.assertEqual(resp.status_code, 403)

    def test_limited_editor_cannot_move_foreign_ration(self):
        self.client.force_login(self.limited)
        resp = self.client.post(
            reverse("claude_ration_reorder"),
            data={
                "ration_id": self.foreign_ration.pk,
                "target_group_id": self.own.pk,
                "ordered_ids": [self.foreign_ration.pk],
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.foreign_ration.refresh_from_db()
        self.assertEqual(self.foreign_ration.group_id, self.foreign.pk)
