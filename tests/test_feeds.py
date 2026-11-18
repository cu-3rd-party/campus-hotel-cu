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
        self.dev = patch.dict(os.environ, {'APP_ENV': 'development', 'ALLOW_INSECURE_DEV_AUTH': '1'})
        self.dev.start()
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
        self.dev.stop()
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
            for endpoint in ['/api/profiles', '/api/profiles?recruiting=true', '/api/groups', '/api/blocks']:
                self.assertEqual(self.client.get(endpoint).status_code, 401)

    def test_recruiting_feed_counts_room_members_before_filtering_profiles(self):
        with self.Session() as db:
            open_room = Group(capacity=4, gender='male', campus='disk')
            full_room = Group(capacity=2, gender='male', campus='disk')
            other_campus = Group(capacity=3, gender='male', campus='cloud')
            other_gender = Group(capacity=3, gender='female', campus='disk')
            fixtures = [
                ('Matching member', open_room, 'male', 'disk', '2'),
                ('Another member', open_room, 'male', 'disk', '2'),
                ('Full first', full_room, 'male', 'disk', '2'),
                ('Full second', full_room, 'male', 'disk', '2'),
                ('Matching single', None, 'male', 'disk', '3,4'),
                ('Matching other campus', other_campus, 'male', 'cloud', ''),
                ('Matching other gender', other_gender, 'female', 'disk', ''),
            ]
            db.add_all([
                Profile(name=name, telegram=f'fixture{i}', group=room, gender=gender,
                        campus=campus, room_capacities=sizes)
                for i, (name, room, gender, campus, sizes) in enumerate(fixtures)
            ])
            db.commit()

        self.count = 0
        response = self.client.get('/api/profiles', params={
            'recruiting': True, 'gender': 'male', 'campus': 'disk',
            'search': 'Matching', 'room_capacity': 4,
        })
        self.assertEqual(response.status_code, 200, response.text)
        found = {p['name']: p for p in response.json()}
        self.assertEqual(set(found), {'Matching member', 'Matching single'})
        self.assertEqual(found['Matching member']['open_room'], {'capacity': 4, 'spots_left': 2})
        self.assertNotIn('open_room', found['Matching single'])
        self.assertEqual(self.count, 1)

        feed = self.client.get('/api/profiles?recruiting=true&gender=male&campus=disk').json()
        self.assertEqual({p['name'] for p in feed}, {'Matching member', 'Another member', 'Matching single'})
        legacy = self.client.get('/api/profiles?without_group=true&gender=male&campus=disk').json()
        self.assertEqual([p['name'] for p in legacy], ['Matching single'])

        with self.Session() as db:
            room = db.get(Group, found['Matching member']['group_id'])
            room.capacity = 2
            db.commit()
        feed = self.client.get('/api/profiles?recruiting=true&gender=male&campus=disk').json()
        self.assertEqual([p['name'] for p in feed], ['Matching single'])

if __name__ == '__main__': unittest.main()
