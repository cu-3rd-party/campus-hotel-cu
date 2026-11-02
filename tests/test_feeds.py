"""Synthetic SQLite fixtures only; no production data, Telegram or network."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['TELEGRAM_BOT_TOKEN'] = ''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import config
from database import Base, get_db
from main import app
from models import Block, Group, Profile

class FeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        def session():
            with self.Session() as db: yield db
        app.dependency_overrides[get_db] = session
        self.client = TestClient(app)
        self.count = 0
        event.listen(self.engine, 'before_cursor_execute', self.count_select)
    def count_select(self, conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'): self.count += 1
    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
    def populate(self, rooms=60):
        with self.Session() as db:
            for n in range(rooms):
                block = Block(gender='male', campus='disk') if n % 2 == 0 else None
                for i in range(2 if block else 1):
                    group = Group(gender='male', campus='disk', capacity=3, block=block)
                    group.members = [Profile(name=f'Fixture {n}-{i}', telegram=f'fixture_{n}_{i}', gender='male', campus='disk')]
                    db.add(group)
            db.commit()
        self.count = 0
    def test_room_serialization_uses_two_queries_for_ninety_rooms(self):
        self.populate()
        response = self.client.get('/api/groups?gender=male&campus=disk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 90)
        self.assertTrue(all(g['spots_left'] == 2 and len(g['members']) == 1 for g in response.json()))
        self.assertEqual(self.count, 2)
    def test_blocks_and_all_their_members_use_three_queries(self):
        self.populate()
        response = self.client.get('/api/blocks?gender=male&campus=disk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 30)
        self.assertTrue(all(b['taken'] == 6 and len(b['groups']) == 2 for b in response.json()))
        self.assertEqual(self.count, 3)
    def test_campus_and_gender_filters_still_apply(self):
        self.populate(2)
        self.assertEqual(self.client.get('/api/groups?gender=female&campus=disk').json(), [])
        self.assertEqual(self.client.get('/api/blocks?gender=male&campus=cloud').json(), [])
    def test_authenticated_feed_is_not_made_public_by_the_optimization(self):
        with patch.object(config, 'TELEGRAM_BOT_TOKEN', 'fixture-token'):
            for endpoint in ['/api/profiles', '/api/groups', '/api/blocks']:
                self.assertEqual(self.client.get(endpoint).status_code, 401)

if __name__ == '__main__': unittest.main()
