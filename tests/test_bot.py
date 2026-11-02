import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
import httpx
from bot import bot

class BotTests(IsolatedAsyncioTestCase):
    async def test_callback_acknowledges_before_waiting_for_backend_and_preserves_actor(self):
        order = []
        async def ack(*args, **kwargs): order.append('ack')
        async def post(path, **kwargs):
            order.append('post')
            self.assertEqual(path, '/api/bot/vote')
            self.assertEqual(kwargs['json'], {'telegram_id': 42, 'request_id': 7, 'approve': True})
            return httpx.Response(200, json={'status': 'approved', 'who': 'Fixture <name>'})
        @asynccontextmanager
        async def client(): yield SimpleNamespace(post=post)
        message = SimpleNamespace(html_text='Заявка', edit_text=AsyncMock(), answer=AsyncMock())
        call = SimpleNamespace(data='vote:7:yes', from_user=SimpleNamespace(id=42), answer=ack, message=message)
        with patch.object(bot, 'api_client', client): await bot.on_vote(call)
        self.assertEqual(order, ['ack', 'post'])
        self.assertIn('&lt;name&gt;', message.edit_text.call_args.args[0])
    async def test_stale_callback_cannot_trigger_a_vote(self):
        call = SimpleNamespace(data='vote:bad:yes', answer=AsyncMock())
        with patch.object(bot, 'api_client') as client:
            await bot.on_vote(call)
            client.assert_not_called()
        call.answer.assert_awaited_once()
    async def test_transient_failure_does_not_retry_a_mutation_or_claim_success(self):
        post = AsyncMock(side_effect=httpx.ConnectTimeout('fixture timeout'))
        @asynccontextmanager
        async def client(): yield SimpleNamespace(post=post)
        message = SimpleNamespace(html_text='Приглашение', edit_text=AsyncMock(), answer=AsyncMock())
        call = SimpleNamespace(data='invite:4:no', from_user=SimpleNamespace(id=42), answer=AsyncMock(), message=message)
        with patch.object(bot, 'api_client', client): await bot.on_invite(call)
        self.assertEqual(post.await_count, 1)
        message.edit_text.assert_not_awaited()
        self.assertIn('проверить результат', message.answer.call_args.args[0])
    async def test_shared_api_client_is_not_closed_per_callback(self):
        pool = object()
        with patch.object(bot, '_api', pool):
            async with bot.api_client() as client: self.assertIs(client, pool)
            async with bot.api_client() as client: self.assertIs(client, pool)
