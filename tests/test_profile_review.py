"""Проверка на вымышленных анкетах и ответах Telegram."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
import notifier
import profile_review as review
import telegram_auth
from database import Base, get_db
from main import app
from models import Group, Profile


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.utcnow()
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine)
        self.settings = patch.multiple(
            config, BOT_SECRET="fixture", TELEGRAM_BOT_TOKEN="fixture", DISK_PROFILE_REVIEW_ENABLED=True,
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)

        def db_override():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = db_override
        self.addCleanup(app.dependency_overrides.pop, get_db)
        self.client = TestClient(app, headers={"X-Bot-Secret": "fixture"})
        self.addCleanup(self.client.close)
        self.addCleanup(self.engine.dispose)

    def add_profile(self, identity, **values):
        data = {
            "name": "Fixture",
            "telegram": "",
            "gender": "female",
            "telegram_id": identity,
            "telegram_verified": True,
            "last_activity_at": self.now - timedelta(days=31),
        }
        with self.Session.begin() as db:
            profile = Profile(**(data | values))
            db.add(profile)
            db.flush()
            return profile.id

    def claim(self):
        with self.Session.begin() as db:
            return review.claim_review(db, self.now)

    def finish(self, profile_id, token, status):
        with self.Session.begin() as db:
            return review.finish_delivery(db, profile_id, token, status, self.now)

    def expire(self, after):
        with self.Session.begin() as db:
            return review.expire_review(db, self.now + after)

    def test_activity_from_either_source_prevents_a_question(self):
        web_id = self.add_profile(101)
        bot_id = self.add_profile(102)
        self.add_profile(103, campus="cloud")
        self.add_profile(104, telegram_verified=False)
        with patch.object(telegram_auth, "verify_webapp_init_data", return_value={"id": 101}):
            self.assertEqual(self.client.post("/api/profiles/me", json={"init_data": "fixture"}).status_code, 200)
        self.assertEqual(self.client.post("/api/bot/activity", json={"telegram_id": 102}).status_code, 204)
        with self.Session() as db:
            for profile_id in (web_id, bot_id):
                self.assertGreaterEqual(db.get(Profile, profile_id).last_activity_at, self.now)
        self.assertIsNone(self.claim())

    def test_only_delivered_questions_expire_after_48_hours(self):
        failed = self.add_profile(101)
        sent = self.add_profile(102)
        _, _, failed_token = self.claim()
        self.finish(failed, failed_token, "failed")
        _, _, sent_token = self.claim()
        self.finish(sent, sent_token, "sent")
        self.assertIsNone(self.claim())
        self.assertIsNone(self.expire(timedelta(hours=47, minutes=59)))
        self.assertIsNotNone(self.expire(timedelta(hours=48)))
        self.assertIsNone(self.expire(timedelta(days=3)))
        with self.Session() as db:
            self.assertIsNotNone(db.get(Profile, failed))
            self.assertIsNone(db.get(Profile, sent))

    def test_keep_restarts_the_clock_and_is_bound_to_the_owner(self):
        profile_id = self.add_profile(101)
        _, _, token = self.claim()
        self.finish(profile_id, token, "sent")
        endpoint = "/api/bot/activity-review"
        answer = {"telegram_id": 101, "token": token, "answer": "keep"}
        self.assertEqual(self.client.post(endpoint, json=answer, headers={"X-Bot-Secret": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post(endpoint, json=answer | {"telegram_id": 102}).status_code, 410)
        self.assertEqual(self.client.post(endpoint, json=answer).json(), {"status": "kept"})
        self.assertEqual(self.client.post(endpoint, json=answer).status_code, 410)
        self.assertIsNone(self.expire(timedelta(days=3)))
        self.assertIsNone(self.claim())

    def test_decline_removes_the_profile_and_releases_the_room(self):
        with self.Session.begin() as db:
            room = Group(capacity=3, gender="female", campus="disk")
            db.add(room)
            db.flush()
            room_id = room.id
        profile_id = self.add_profile(101, group_id=room_id)
        remaining_id = self.add_profile(102, group_id=room_id, last_activity_at=self.now)
        _, _, token = self.claim()
        self.finish(profile_id, token, "sent")
        result = self.client.post(
            "/api/bot/activity-review",
            json={"telegram_id": 101, "token": token, "answer": "done"},
        )
        self.assertEqual(result.json(), {"status": "deleted"})
        with self.Session() as db:
            self.assertIsNone(db.get(Profile, profile_id))
            self.assertEqual([p.id for p in db.get(Group, room_id).members], [remaining_id])

    def test_confirmed_block_removes_only_disk_profiles_while_enabled(self):
        blocked = self.add_profile(101)
        cloud = self.add_profile(102, campus="cloud")
        endpoint = "/api/bot/activity"
        with patch.object(config, "DISK_PROFILE_REVIEW_ENABLED", False):
            self.assertEqual(self.client.post(endpoint, json={"telegram_id": 101, "blocked": True}).status_code, 204)
        with self.Session() as db:
            self.assertIsNotNone(db.get(Profile, blocked))
        for identity in (101, 102):
            self.assertEqual(self.client.post(endpoint, json={"telegram_id": identity, "blocked": True}).status_code, 204)
        with self.Session() as db:
            self.assertIsNone(db.get(Profile, blocked))
            self.assertIsNotNone(db.get(Profile, cloud))

    def test_block_reported_during_delivery_removes_the_profile(self):
        profile_id = self.add_profile(101)
        _, _, token = self.claim()
        self.finish(profile_id, token, "blocked")
        with self.Session() as db:
            self.assertIsNone(db.get(Profile, profile_id))


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_distinguishes_confirmed_block_from_other_failures(self):
        cases = [
            (None, ("failed", 0)),
            (httpx.Response(403, json={"description": "Forbidden: bot can't initiate conversation with a user"}), ("failed", 0)),
            (httpx.Response(403, json={"description": "Forbidden: bot was blocked by the user"}), ("blocked", 0)),
            (httpx.Response(429, json={"parameters": {"retry_after": 42}}), ("failed", 42)),
            (httpx.Response(200, json={"ok": True}), ("sent", 0)),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected), patch.object(notifier, "_post_message", AsyncMock(return_value=response)) as post:
                self.assertEqual(await notifier.send_profile_review(101, "a" * 24), expected)
                self.assertEqual(post.await_args.args[0], 101)
                buttons = post.await_args.args[2]["inline_keyboard"]
                self.assertEqual([row[0]["callback_data"].rsplit(":", 1)[1] for row in buttons], ["keep", "leaving", "done"])
