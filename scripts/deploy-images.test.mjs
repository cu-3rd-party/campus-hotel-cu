import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {replaceImage} from './deploy-images.mjs';

const helper=fileURLToPath(new URL('./deploy-images.mjs',import.meta.url));
const workflow=fileURLToPath(new URL('../.forgejo/workflows/ci-cd.yml',import.meta.url));
const sha='a'.repeat(40),services=['backend','frontend','bot'];
const env={...process.env,GIT_CONFIG_GLOBAL:'/dev/null',GIT_CONFIG_SYSTEM:'/dev/null',GIT_TERMINAL_PROMPT:'0'};
function git(cwd,...args){
 const r=spawnSync('git',['-c','user.name=Fixture','-c','user.email=fixture@example.invalid',...args],{cwd,env,encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);return r.stdout.trim();
}
function values(service,environment){return `# Keep layout and comments\nreplicaCount: 2\nimage:\n  repository: ghcr.io/old/${service} # registry\n  tag: "old-${environment}" # pin\n  pullPolicy: IfNotPresent\n  nested:\n    repository: keep.internal/sidecar\n    tag: keep\nother:\n  repository: keep.external/other\n  tag: never\nservice:\n  port: 80\n`;}
function fixture(t){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'neighbors-gitops-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const remote=path.join(root,'origin.git'),seed=path.join(root,'seed'),work=path.join(root,'work');
 git(root,'init','--bare','--initial-branch=main',remote);git(root,'clone',remote,seed);
 const original=new Map();
 for(const environment of ['dev','prod'])for(const service of services){
  const file=`apps/campus-hotel-${environment}-${service}/values.yaml`,text=values(service,environment);
  fs.mkdirSync(path.dirname(path.join(seed,file)),{recursive:true});fs.writeFileSync(path.join(seed,file),text);original.set(file,text);
 }
 fs.mkdirSync(path.join(seed,'apps/unrelated'),{recursive:true});fs.writeFileSync(path.join(seed,'apps/unrelated/values.yaml'),'image:\n  repository: foreign/app\n  tag: do-not-touch\n');
 git(seed,'add','.');git(seed,'commit','-m','fixture');git(seed,'push','-u','origin','main');git(root,'clone',remote,work);
 return {root,remote,work,original,head:()=>git(work,'rev-parse','HEAD'),remoteHead:()=>git(root,'--git-dir',remote,'rev-parse','HEAD'),run:(environment='dev',tag=sha,extra=[])=>spawnSync(process.execPath,[helper,'--repo',work,'--environment',environment,'--tag',tag,...extra],{env,encoding:'utf8'})};
}
function snapshot(f){return Object.fromEntries([...f.original.keys(),'apps/unrelated/values.yaml'].filter(k=>fs.existsSync(path.join(f.work,k))).map(k=>[k,fs.readFileSync(path.join(f.work,k),'utf8')]));}

for(const environment of ['dev','prod'])test('publish only the three '+environment+' images; preserve other fields/apps/environment',t=>{
 const f=fixture(t),before=snapshot(f),remoteBefore=f.remoteHead(),r=f.run(environment);assert.equal(r.status,0,r.stderr);
 const changed=git(f.work,'diff','--name-only',remoteBefore,'HEAD').split('\n').sort();
 assert.deepEqual(changed,services.map(s=>`apps/campus-hotel-${environment}-${s}/values.yaml`).sort());
 for(const [file,original]of Object.entries(before)){
  const service=services.find(s=>file===`apps/campus-hotel-${environment}-${s}/values.yaml`);
  const expected=service?original.replace(`ghcr.io/old/${service}`,`git.cu3rd.ru/cu3rd/campus-hotel-cu-${service}`).replace(`"old-${environment}"`,`"${sha}"`):original;
  assert.equal(fs.readFileSync(path.join(f.work,file),'utf8'),expected,file);
 }
 assert.equal(f.head(),f.remoteHead());assert.equal(git(f.work,'status','--porcelain'),'');
 // An idempotent call must not try to push again.
 fs.writeFileSync(path.join(f.work,'.git/hooks/pre-push'),'#!/bin/sh\nexit 1\n',{mode:0o755});
 const head=f.head();assert.equal(f.run(environment).status,0);assert.equal(f.head(),head);
});

test('dry run validates the complete plan without writes, staging, commits or pushes',t=>{
 const f=fixture(t),before=snapshot(f),head=f.head(),r=f.run('dev',sha,['--dry-run']);
 assert.equal(r.status,0,r.stderr);assert.equal(JSON.parse(r.stdout).changed.length,3);assert.deepEqual(snapshot(f),before);assert.equal(f.head(),head);assert.equal(f.remoteHead(),head);assert.equal(git(f.work,'status','--porcelain'),'');
});

test('invalid environment and non-full/non-hex tags fail before any mutation',t=>{
 const f=fixture(t),before=snapshot(f),head=f.head();
 for(const [environment,tag]of[['../prod',sha],['staging',sha],['dev','abc1234'],['prod','Z'.repeat(40)],['prod','a'.repeat(39)+';']]){
  assert.notEqual(f.run(environment,tag).status,0);assert.deepEqual(snapshot(f),before);assert.equal(f.head(),head);assert.equal(f.remoteHead(),head);
 }
});

for(const failure of ['missing','bad-mapping','symlink'])test('validate all files before writing when the third file is '+failure,t=>{
 const f=fixture(t),file='apps/campus-hotel-dev-bot/values.yaml',target=path.join(f.work,file);
 if(failure==='missing')fs.unlinkSync(target);
 else if(failure==='bad-mapping')fs.writeFileSync(target,'image:\n  repository: old/bot\nmissingTag: true\n');
 else {fs.unlinkSync(target);fs.symlinkSync('../unrelated/values.yaml',target);}
 git(f.work,'add','--',file);git(f.work,'commit','-m','invalid fixture');const before=snapshot(f),head=f.head();
 const r=f.run();assert.notEqual(r.status,0);assert.deepEqual(snapshot(f),before);assert.equal(f.head(),head);assert.equal(git(f.work,'status','--porcelain'),'');
});

test('refuse pre-existing foreign staged/unstaged changes without consuming them',t=>{
 const f=fixture(t),file='apps/unrelated/values.yaml',before=f.head();
 fs.appendFileSync(path.join(f.work,file),'owner: someone-else\n');git(f.work,'add','--',file);
 const status=git(f.work,'status','--porcelain'),valuesBefore=snapshot(f);assert.notEqual(f.run().status,0);assert.deepEqual(snapshot(f),valuesBefore);assert.equal(git(f.work,'status','--porcelain'),status);assert.equal(f.head(),before);
});

test('non-fast-forward push rebases once and preserves a concurrent field change',t=>{
 const f=fixture(t),peer=path.join(f.root,'peer');git(f.root,'clone',f.remote,peer);
 const file='apps/campus-hotel-dev-backend/values.yaml';fs.writeFileSync(path.join(peer,file),values('backend','dev').replace('port: 80','port: 8081'));
 git(peer,'add','--',file);git(peer,'commit','-m','concurrent service setting');git(peer,'push');const peerHead=git(peer,'rev-parse','HEAD');
 const r=f.run();assert.equal(r.status,0,r.stderr);assert.match(r.stdout,/push 2\/3/);assert.equal(f.head(),f.remoteHead());assert.equal(git(f.work,'log','-1','--format=%ce'),'cu3rd-ci@noreply.git.cu3rd.ru');assert(fs.readFileSync(path.join(f.work,file),'utf8').includes('port: 8081'));assert(fs.readFileSync(path.join(f.work,file),'utf8').includes(sha));git(f.work,'merge-base','--is-ancestor',peerHead,'HEAD');
});

test('push failure remains a failure after exactly three bounded attempts',t=>{
 const f=fixture(t),head=f.remoteHead(),counter=path.join(f.root,'pushes');
 fs.writeFileSync(path.join(f.work,'.git/hooks/pre-push'),'#!/bin/sh\necho attempt >> "'+counter+'"\nexit 1\n',{mode:0o755});
 const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/failed after 3 attempts/);assert.equal(fs.readFileSync(counter,'utf8').trim().split('\n').length,3);assert.equal(f.remoteHead(),head);
});

test('a rebase conflict fails without overwriting the remote image or forcing a push',t=>{
 const f=fixture(t),peer=path.join(f.root,'peer');git(f.root,'clone',f.remote,peer);
 const file='apps/campus-hotel-dev-backend/values.yaml';fs.writeFileSync(path.join(peer,file),values('backend','dev').replace('"old-dev"','"concurrent-tag"'));
 git(peer,'add','--',file);git(peer,'commit','-m','concurrent image');git(peer,'push');const head=f.remoteHead();
 const r=f.run();assert.notEqual(r.status,0);assert.match(r.stderr,/git pull failed/);assert.equal(f.remoteHead(),head);assert(git(peer,'show','HEAD:'+file).includes('concurrent-tag'));
});

test('mapping update preserves CRLF/quotes/comments and never rewrites nested images',()=>{
 const text="image: # image settings\r\n    repository: 'old/repository' # old registry\r\n    tag: # default\r\n    extra:\r\n      repository: nested/untouched\r\nother: true\r\n";
 assert.equal(replaceImage(text,'new/repository',sha),text.replace("'old/repository'","'new/repository'").replace('tag: # default','tag: '+sha+' # default'));
 for(const invalid of ['image: {repository: old, tag: old}\n','image:\n  repository: old\n  tag: x\n  tag: y\n','image:\n  repository: old\n  tag: |\n    text\n','image:\n  repository: old\n  tag: old\nimage:\n  repository: other\n  tag: other\n'])assert.throws(()=>replaceImage(invalid,'new/repository',sha));
});

test('Forgejo deployment is two real runner jobs with scoped checkouts and manual prod gate',()=>{
 const text=fs.readFileSync(workflow,'utf8');
 for(const environment of ['dev','prod']){
  const block=text.match(new RegExp('^  deploy-'+environment+':\\n([\\s\\S]*?)(?=^  [a-z-]+:|$(?![\\s\\S]))','m'))?.[1];assert(block);
  assert.match(block,/^    runs-on: ubuntu-latest$/m);assert(!/^    uses:/m.test(block));assert(!/^    secrets:/m.test(block));assert.match(block,/path: source\n          persist-credentials: false/);assert.match(block,/github-server-url: https:\/\/github.com\n          repository: pxc1984\/homelab\n          ssh-key: \$\{\{ secrets.HOMELAB_DEPLOY_KEY \}\}\n          path: homelab/);
  assert(block.includes('--environment '+environment+' --tag "$TAG"'));assert(block.includes('group: deploy-'+environment));assert(block.includes('needs: '+(environment==='dev'?'build':'deploy-dev')));
  if(environment==='prod')assert.match(block,/if: github.event_name == 'workflow_dispatch' && \(inputs.deploy_prod == true \|\| inputs.deploy_prod == 'true'\)/);
 }
 for(const id of ['check','build','deploy-dev','deploy-prod']){
  const block=text.match(new RegExp('^  '+id+':\\n([\\s\\S]*?)(?=^  [a-z-]+:|$(?![\\s\\S]))','m'))?.[1];assert(block);
  if(id==='check'||id==='build')assert.match(block,/^    runs-on: homelab-docker$/m);
  assert(block.includes('container:\n      image: ghcr.io/catthehacker/ubuntu@sha256:62d572b92f9f32d3427b6d220ad1f9dca9c7b6ffad37d295425037dbff78abaf'));
 }
 assert(text.includes('run: node --test scripts/deploy-images.test.mjs'));
});
