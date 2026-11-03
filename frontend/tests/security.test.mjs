import test from 'node:test';
import assert from 'node:assert/strict';
import {telegramLink, profilePhoto} from '../src/links.mjs';
import {requestJSON} from '../src/request.mjs';

test('legacy fields cannot turn a contact link into a Telegram action or load an unsafe image scheme',()=>{
  for(const value of ['share/url?url=https://fixture.invalid','../login','javascript:alert(1)','hello#fragment','user/path'])assert.equal(telegramLink(value),undefined);
  assert.equal(telegramLink('@fixture_user'),'https://t.me/fixture_user');
  for(const value of ['javascript:alert(1)','data:image/svg+xml,<svg/>','//fixture.invalid/photo','https://user:pass@fixture.invalid/x','/api/config'])assert.equal(profilePhoto(value),'');
  assert.equal(profilePhoto('/api/media/'+'a'.repeat(32)+'.jpg'),'/api/media/'+'a'.repeat(32)+'.jpg');
  assert.equal(profilePhoto('https://fixture.invalid/photo.jpg'),'https://fixture.invalid/photo.jpg');
});

test('validation errors identify the field without echoing submitted personal data',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:[{loc:['body','bio'],type:'string_too_long',input:'PRIVATE FIXTURE'}]}),{status:422});
  try {await assert.rejects(requestJSON('/fixture','Failed'),error=>error.status===422&&error.message.includes('О себе')&&!error.message.includes('PRIVATE'));}
  finally {globalThis.fetch=original;}
});
