"""Synthetic signed actors, isolated SQLite and temporary files. No live services."""
import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from urllib.parse import urlencode
import zipfile

os.environ.setdefault('DATABASE_URL', 'sqlite://')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import admin_export
import config
import notifier
import storage
import telegram_auth
from database import Base, get_db
from main import app
from models import Group, Profile

TOKEN = 'synthetic-token-not-a-credential'


def signed(user_id=111, username='fixture_owner', issued=None, **extra):
    data = {'auth_date': str(int(time.time()) if issued is None else issued),
            'user': json.dumps({'id': user_id, 'username': username, 'first_name': 'Fixture'}, separators=(',', ':')), **extra}
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def headers(user_id=111, **kwargs):
    return {'X-Telegram-Init-Data': signed(user_id, **kwargs)}


def widget(issued=None):
    data = {'id': 444, 'username': 'widget_fixture', 'first_name': 'Fixture', 'auth_date': int(time.time()) if issued is None else issued}
    secret = hashlib.sha256(TOKEN.encode()).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return data


PROFILE = {'name': 'Fixture owner', 'telegram': 'fixture_owner', 'gender': 'male', 'campus': 'disk', 'bio': 'Synthetic only'}
ACTOR_ROUTES = [
    ('PUT', '/api/profiles/1', PROFILE), ('DELETE', '/api/profiles/1', None),
    ('POST', '/api/groups', {'profile_id': 1, 'capacity': 3}),
    ('POST', '/api/groups/1/requests', {'profile_id': 1}),
    ('POST', '/api/groups/1/leave', {'profile_id': 1}),
    ('POST', '/api/groups/1/capacity', {'profile_id': 1, 'capacity': 2}),
    ('POST', '/api/requests/1/vote', {'profile_id': 1, 'approve': True}),
    ('POST', '/api/requests/1/cancel', {'profile_id': 1}),
    ('POST', '/api/invites', {'from_profile_id': 1, 'to_profile_id': 2, 'capacity': 3}),
    ('POST', '/api/invites/1/respond', {'profile_id': 1, 'accept': True}),
    ('POST', '/api/invites/1/cancel', {'profile_id': 1}),
    ('POST', '/api/blocks/requests', {'profile_id': 1, 'to_group_id': 1}),
    ('POST', '/api/blocks/requests/1/vote', {'profile_id': 1, 'approve': True}),
    ('POST', '/api/blocks/requests/1/cancel', {'profile_id': 1}),
    ('POST', '/api/blocks/1/leave', {'profile_id': 1}),
    ('GET', '/api/groups/1/requests', None), ('GET', '/api/groups/1/block-requests', None),
    ('GET', '/api/profiles/1/requests', None), ('GET', '/api/profiles/1/invites', None),
]


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'APP_ENV': 'production', 'ALLOW_INSECURE_DEV_AUTH': '0'})
        self.env.start()
        self.patches = [patch.object(config, 'TELEGRAM_BOT_TOKEN', TOKEN), patch.object(telegram_auth, 'TELEGRAM_BOT_TOKEN', TOKEN),
                        patch.object(config, 'ADMIN_TELEGRAM_IDS', {777}), patch.object(config, 'BOT_SECRET', 'fixture-secret'),
                        patch.object(notifier, 'deliver', new=AsyncMock())]
        for p in self.patches: p.start()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        def session():
            with self.Session() as db: yield db
        app.dependency_overrides[get_db] = session
        with self.Session() as db:
            room = Group(id=1, capacity=3, gender='male', campus='disk')
            db.add_all([room, Profile(id=1, **PROFILE, telegram_id=111, telegram_verified=True, group=room),
                        Profile(id=2, name='Other fixture', telegram='fixture_other', gender='male', telegram_id=222)])
            db.commit()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); app.dependency_overrides.clear(); self.engine.dispose()
        for p in reversed(self.patches): p.stop()
        self.env.stop()

    def test_signed_newcomer_and_another_owner_cannot_act_for_victim(self):
        for actor in (333, 222):
            for method, path, body in ACTOR_ROUTES:
                with self.subTest(actor=actor, path=path, method=method):
                    r = self.client.request(method, path, json=body, headers=headers(actor))
                    self.assertEqual(r.status_code, 403, r.text)
        with self.Session() as db:
            self.assertEqual(db.get(Profile, 1).name, PROFILE['name'])
            self.assertEqual(db.get(Profile, 1).group_id, 1)
            self.assertEqual(db.query(Profile).count(), 2)

    def test_valid_owner_can_edit_and_create_own_room(self):
        self.assertEqual(self.client.get('/api/profiles/ideal', headers=headers()).status_code, 200)
        for path in ('/api/groups/1/requests', '/api/groups/1/block-requests', '/api/profiles/1/requests', '/api/profiles/1/invites'):
            self.assertEqual(self.client.get(path, headers=headers()).status_code, 200, path)
        r = self.client.put('/api/profiles/1', json={**PROFILE, 'bio': 'Updated fixture'}, headers=headers())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['bio'], 'Updated fixture')
        r = self.client.post('/api/groups', json={'profile_id': 2, 'capacity': 2}, headers=headers(222))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()['members'][0]['id'], 2)

    def test_missing_production_token_does_not_grant_access_or_admin(self):
        with patch.object(config, 'TELEGRAM_BOT_TOKEN', ''):
            for path in ('/api/profiles', '/api/groups', '/api/blocks', '/api/profiles/1', '/api/profiles/1/requests'):
                self.assertEqual(self.client.get(path).status_code, 503, path)
            self.assertFalse(self.client.get('/api/config').json()['is_admin'])
            self.assertEqual(self.client.get('/api/admin/stats').status_code, 403)
            self.assertEqual(self.client.post('/api/profiles', json=PROFILE).status_code, 503)
            with patch.dict(os.environ, {'ALLOW_INSECURE_DEV_AUTH': '1'}):
                self.assertEqual(self.client.get('/api/profiles').status_code, 503)
            with patch.dict(os.environ, {'APP_ENV': 'development', 'ALLOW_INSECURE_DEV_AUTH': '1'}):
                self.assertEqual(self.client.get('/api/profiles').status_code, 200)
                self.assertFalse(self.client.get('/api/config').json()['is_admin'])

    def test_unauthenticated_reads_writes_upload_and_admin_are_rejected(self):
        for method, path, body in ACTOR_ROUTES:
            self.assertEqual(self.client.request(method, path, json=body).status_code, 401, path)
        for path in ('/api/profiles', '/api/groups', '/api/blocks', '/api/groups/1/block-candidates'):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/uploads/photo', files={'file': ('x.jpg', b'bad')}).status_code, 401)
        for path in ('/api/admin/stats', '/api/admin/profiles', '/api/admin/export'):
            self.assertEqual(self.client.get(path, headers=headers(333)).status_code, 403)
        self.assertEqual(self.client.get('/api/admin/stats', headers=headers(777)).status_code, 200)
        self.assertEqual(self.client.post('/api/bot/link', json={'telegram_id': 111, 'chat_id': 111}).status_code, 401)

    def test_username_reassignment_or_legacy_nickname_never_claims_identity(self):
        for actor in (333,):
            h = headers(actor, username='fixture_owner')
            self.assertEqual(self.client.delete('/api/profiles/1', headers=h).status_code, 403)
            self.assertEqual(self.client.post('/api/profiles/me', json={'init_data': h['X-Telegram-Init-Data']}).status_code, 404)
        with self.Session() as db:
            db.get(Profile, 1).telegram_id = None
            db.commit()
        self.assertEqual(self.client.post('/api/profiles/me', json={'init_data': signed()}).status_code, 404)
        with self.Session() as db: self.assertIsNone(db.get(Profile, 1).telegram_id)

    def test_creation_requires_identity_binds_it_and_prevents_duplicates(self):
        self.assertEqual(self.client.post('/api/profiles', json=PROFILE).status_code, 401)
        r = self.client.post('/api/profiles', json={**PROFILE, 'telegram': 'someone_else', 'telegram_verified': False}, headers=headers(333, username='real_fixture'))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()['telegram_id'], r.json()['telegram'], r.json()['telegram_verified']), (333, 'real_fixture', True))
        self.assertEqual(self.client.post('/api/profiles', json=PROFILE, headers=headers(333)).status_code, 409)

    def test_verified_account_without_username_never_claims_supplied_contact(self):
        r = self.client.post('/api/profiles', json={**PROFILE,'telegram':'fixture_owner'},headers=headers(333,username=''))
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()['telegram'],'')
        self.assertTrue(r.json()['telegram_verified'])
        r = self.client.put('/api/profiles/'+str(r.json()['id']),json={**PROFILE,'telegram':'fixture_owner'},headers=headers(333,username=''))
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['telegram'],'')

    def test_signed_owner_contact_refresh_does_not_reassign_other_profiles(self):
        r = self.client.post('/api/profiles/me',json={'init_data':signed(111,username='renamed_fixture')})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['id'],1)
        self.assertEqual(r.json()['telegram'],'renamed_fixture')
        with self.Session() as db:self.assertEqual(db.get(Profile,2).telegram,'fixture_other')

    def test_invalid_expired_future_ambiguous_and_bad_user_signatures(self):
        bad = [signed(issued=int(time.time())-config.AUTH_MAX_AGE_SECONDS-10), signed(issued=int(time.time())+3600),
               signed()[:-1]+'x', signed()+'&user=%7B%22id%22%3A333%7D', signed(user_id=True), signed(user_id=-1), 'x'*16385]
        for value in bad:
            with self.subTest(value=value[:30]):
                self.assertEqual(self.client.get('/api/profiles', headers={'X-Telegram-Init-Data': value}).status_code, 401)
        self.assertEqual(self.client.get('/api/profiles', headers=headers()).status_code, 200)

    def test_widget_signature_freshness_and_header_identity_are_checked_on_create(self):
        for auth in (widget(int(time.time())-config.AUTH_MAX_AGE_SECONDS-10), widget(int(time.time())+3600), {**widget(), 'id': 111}):
            self.assertEqual(self.client.post('/api/profiles', json={**PROFILE, 'telegram_auth': auth}).status_code, 401)
        self.assertEqual(self.client.post('/api/profiles', json={**PROFILE, 'telegram_auth': widget()}, headers=headers(333)).status_code, 403)
        r = self.client.post('/api/profiles', json={**PROFILE, 'telegram_auth': widget()})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()['telegram_id'], 444)

    def test_input_limits_and_unsafe_urls_are_rejected_without_breaking_legacy_read(self):
        for changed in ({'name': '  '}, {'bio': 'x'*501}, {'telegram': 'share/url?url=https://evil.test'}, {'photo_url': '//evil.test/x'}, {'photo_url': 'javascript:alert(1)'}):
            self.assertEqual(self.client.put('/api/profiles/1', json={**PROFILE, **changed}, headers=headers()).status_code, 422)
        with self.Session() as db:
            db.get(Profile, 1).photo_url = 'javascript:legacy'; db.commit()
        self.assertEqual(self.client.get('/api/profiles/1', headers=headers()).status_code, 200)

    def test_bounded_upload_and_image_decoding(self):
        raw = io.BytesIO(); Image.new('RGB', (3, 3), 'white').save(raw, 'PNG')
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'UPLOAD_DIR', Path(directory)):
            corrupt = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=')
            self.assertEqual(self.client.post('/api/uploads/photo', headers=headers(333), files={'file': ('corrupt.png', corrupt)}).status_code, 400)
            self.assertEqual(self.client.post('/api/uploads/photo', headers=headers(333), files={'file': ('bad.svg', b'<svg/>')}).status_code, 400)
            with patch.object(storage, 'MAX_PIXELS', 4):
                self.assertEqual(self.client.post('/api/uploads/photo', headers=headers(333), files={'file': ('large.png', raw.getvalue())}).status_code, 400)
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch.object(config, 'MAX_UPLOAD_BYTES', 8):
                self.assertEqual(self.client.post('/api/uploads/photo', headers=headers(333), files={'file': ('x.png', raw.getvalue())}).status_code, 413)
            r = self.client.post('/api/uploads/photo', headers=headers(333), files={'file': ('x.png', raw.getvalue())})
            self.assertEqual(r.status_code, 201, r.text)
            saved = Path(directory)/r.json()['photo_url'].split('/')[-1]
            with Image.open(saved) as image: self.assertEqual(image.format, 'JPEG')
        oversized = self.client.post('/api/profiles', content=iter([b'x'*70000]), headers={**headers(), 'Content-Type': 'application/json'})
        self.assertEqual(oversized.status_code, 413, oversized.text)

    def test_avatar_download_does_not_follow_redirects_to_private_hosts(self):
        requests = []
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/internal'})
        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch.object(telegram_auth.httpx, 'AsyncClient', return_value=client):
                self.assertIsNone(await telegram_auth.download_avatar('https://t.me/i/userpic/320/fixture.jpg'))
        asyncio.run(run())
        self.assertEqual(requests, ['https://t.me/i/userpic/320/fixture.jpg'])

    def test_avatar_stream_is_bounded_and_unsafe_targets_are_never_requested(self):
        requests = []
        def respond(request):
            requests.append(str(request.url)); return httpx.Response(200, content=b'x'*10)
        async def run(url):
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch.object(telegram_auth.httpx, 'AsyncClient', return_value=client), patch.object(telegram_auth, 'MAX_UPLOAD_BYTES', 8):
                self.assertIsNone(await telegram_auth.download_avatar(url))
        for url in ('http://127.0.0.1/', 'https://t.me.evil.invalid/i/userpic/x', 'https://user:pass@t.me/i/userpic/x', 'https://t.me:8080/i/userpic/x'):
            asyncio.run(run(url))
        self.assertEqual(requests, [])
        asyncio.run(run('https://t.me/i/userpic/x'))
        self.assertEqual(len(requests), 1)

    def test_bot_api_photo_download_is_bounded_too(self):
        def respond(request):
            if request.url.path.endswith('getUserProfilePhotos'):
                return httpx.Response(200, json={'ok':True,'result':{'total_count':1,'photos':[[{'file_id':'fixture'}]]}})
            if request.url.path.endswith('getFile'):
                return httpx.Response(200, json={'ok':True,'result':{'file_path':'fixture.png'}})
            return httpx.Response(200, content=b'x'*10)
        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch.object(telegram_auth.httpx, 'AsyncClient', return_value=client), patch.object(telegram_auth, 'MAX_UPLOAD_BYTES', 8):
                self.assertEqual(await telegram_auth.fetch_profile_photos(111), ([],1))
        asyncio.run(run())

    def test_bot_secret_is_required_for_every_service_action(self):
        actions = [('GET', '/api/bot/pending?telegram_id=111', None),
                   ('POST', '/api/bot/link', {'telegram_id':111, 'chat_id':111}),
                   ('POST', '/api/bot/vote', {'telegram_id':111, 'request_id':1, 'approve':True}),
                   ('POST', '/api/bot/block', {'telegram_id':111, 'request_id':1, 'approve':True}),
                   ('POST', '/api/bot/invite', {'telegram_id':111, 'invite_id':1, 'accept':True})]
        for method, path, body in actions:
            self.assertEqual(self.client.request(method, path, json=body, headers={'X-Bot-Secret':'wrong'}).status_code, 401)
        with patch.object(config, 'BOT_SECRET', ''):
            self.assertEqual(self.client.get('/api/bot/pending?telegram_id=111', headers={'X-Bot-Secret':'fixture-secret'}).status_code, 503)
        self.assertEqual(self.client.post('/api/bot/link', json={'telegram_id':111,'chat_id':-100123},headers={'X-Bot-Secret':'fixture-secret'}).status_code,400)
        from helpers import _msg
        self.assertIsNone(_msg(-100123,'private')['chat_id'])

    def test_spreadsheet_export_keeps_user_text_as_text_not_formulas(self):
        from openpyxl import load_workbook
        with self.Session() as db:
            p = db.get(Profile, 1); p.name = '=HYPERLINK("https://fixture.invalid")'; p.bio = ' \t=1+1'
            book = load_workbook(io.BytesIO(admin_export.to_xlsx([p], [], 'full')))
            self.assertEqual(book['Пользователи']['B2'].data_type, 's')
            with zipfile.ZipFile(io.BytesIO(admin_export.to_csv_zip([p], [], 'full'))) as z:
                self.assertIn("'=HYPERLINK", z.read('users.csv').decode('utf-8-sig'))

    def test_private_api_responses_are_not_cacheable(self):
        r = self.client.get('/api/profiles', headers=headers())
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(r.headers['x-content-type-options'], 'nosniff')

    def test_telegram_failure_logs_do_not_contain_tokens_or_private_response_text(self):
        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500, text='PRIVATE FIXTURE RESPONSE')))
            with patch.object(notifier, 'TELEGRAM_BOT_TOKEN', 'SYNTHETIC_SECRET'), patch.object(notifier.httpx, 'AsyncClient', return_value=client):
                with self.assertLogs(notifier.log, level='WARNING') as captured:
                    self.assertFalse(await notifier.send_message(111, 'PRIVATE FIXTURE MESSAGE'))
                self.assertNotIn('SYNTHETIC_SECRET', str(captured.output))
                self.assertNotIn('PRIVATE', str(captured.output))
        asyncio.run(run())


if __name__ == '__main__': unittest.main()
