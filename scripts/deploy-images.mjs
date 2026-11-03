#!/usr/bin/env node
// GitOps changes are scoped to three checked values files. No YAML reserialization.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const services=['backend','frontend','bot'];
const imagePrefix='git.cu3rd.ru/cu3rd/campus-hotel-cu-';

function scalarReplacement(value,replacement){
 if(value.startsWith('"')){
  const match=value.match(/^"(?:\\.|[^"\\])*"([ \t]*(?:#.*)?)$/);
  if(!match)throw Error('Unsupported double-quoted image scalar');
  return '"'+replacement+'"'+match[1];
 }
 if(value.startsWith("'")){
  const match=value.match(/^'(?:''|[^'])*'([ \t]*(?:#.*)?)$/);
  if(!match)throw Error('Unsupported single-quoted image scalar');
  return "'"+replacement+"'"+match[1];
 }
 const comment=value.search(/(?:^|[ \t]+)#/);
 const scalar=comment<0?value:value.slice(0,comment);
 if(/^[>|\[\]{&*!]/.test(scalar.trim()))throw Error('Image repository/tag must be simple scalars');
 const suffix=comment<0?(value.match(/[ \t]*$/)||[''])[0]:value.slice(comment);
 return replacement+(suffix.startsWith('#')?' ':'')+suffix;
}

export function replaceImage(text,repository,tag){
 const lines=text.split('\n'),body=i=>lines[i].replace(/\r$/,'');
 const roots=lines.map((_,i)=>i).filter(i=>/^image[ \t]*:/.test(body(i)));
 if(roots.length!==1||!/^image:[ \t]*(?:#.*)?$/.test(body(roots[0])))throw Error('Expected one top-level image mapping');
 const start=roots[0]+1;
 let end=start;
 while(end<lines.length&&(!/^\S/.test(body(end))||/^#/.test(body(end))))end++;
 const children=Array.from({length:end-start},(_,i)=>start+i).filter(i=>body(i).trim()&&!/^\s*#/.test(body(i)));
 if(children.some(i=>/^ *\t/.test(body(i))))throw Error('Tabs in image mapping indentation');
 const indent=Math.min(...children.map(i=>body(i).match(/^ */)[0].length));
 if(!Number.isFinite(indent)||indent<1)throw Error('Empty image mapping');
 for(const [key,replacement]of Object.entries({repository,tag})){
  const pattern=new RegExp('^( {'+indent+'})'+key+':([ \\t]*)(.*)$');
  const found=children.filter(i=>pattern.test(body(i)));
  if(found.length!==1)throw Error('Expected exactly one image.'+key);
  const i=found[0],match=body(i).match(pattern),newline=lines[i].endsWith('\r')?'\r':'';
  lines[i]=match[1]+key+':'+(match[2]||' ')+scalarReplacement(match[3],replacement)+newline;
 }
 return lines.join('\n');
}

function git(repo,args,{allowFailure=false}={}){
 const result=spawnSync('git',['-c','user.name=forgejo-actions[bot]','-c','user.email=cu3rd-ci@noreply.git.cu3rd.ru','-C',repo,...args],{encoding:'utf8'});
 if(result.error)throw result.error;
 if(result.status!==0&&!allowFailure)throw Error('git '+args[0]+' failed: '+(result.stderr||result.stdout).trim());
 return result;
}

export function deployImages({repo,environment,tag,dryRun=false}){
 if(!['dev','prod'].includes(environment))throw Error('Environment must be dev or prod');
 if(!/^[a-f0-9]{40}$/.test(tag||''))throw Error('Tag must be a full lowercase 40-character commit SHA');
 const root=fs.realpathSync(repo);
 if(fs.realpathSync(git(root,['rev-parse','--show-toplevel']).stdout.trim())!==root)throw Error('Repository must be a Git worktree root');
 if(!git(root,['symbolic-ref','--quiet','--short','HEAD']).stdout.trim())throw Error('A checked-out branch is required');
 if(git(root,['status','--porcelain=v1','--untracked-files=normal']).stdout.trim())throw Error('GitOps checkout must be clean before updating images');
 const files=services.map(service=>'apps/campus-hotel-'+environment+'-'+service+'/values.yaml');
 // Read, scope-check and transform all three before writing any file.
 const plans=files.map((file,i)=>{
  const target=path.join(root,file);
  if(!fs.lstatSync(target).isFile()||!fs.realpathSync(target).startsWith(root+path.sep))throw Error('Expected regular values file inside checkout: '+file);
  git(root,['ls-files','--error-unmatch','--',file]);
  const original=fs.readFileSync(target,'utf8');
  return {file,target,original,updated:replaceImage(original,imagePrefix+services[i],tag)};
 });
 const changed=plans.filter(p=>p.updated!==p.original);
 if(dryRun){console.log(JSON.stringify({environment,tag,files,changed:changed.map(p=>p.file),dryRun:true}));return {changed:changed.length,dryRun:true};}
 if(!changed.length){console.log('All three images already match '+tag);return {changed:0};}
 for(const p of changed)fs.writeFileSync(p.target,p.updated);
 git(root,['add','--',...files]);
 const staged=git(root,['diff','--cached','--name-only','-z']).stdout.split('\0').filter(Boolean);
 if(!staged.length||staged.some(file=>!files.includes(file)))throw Error('Unexpected staged paths; refusing GitOps commit');
 git(root,['commit','-m','campus-hotel-'+environment+': deploy '+tag.slice(0,7),'--',...files]);
 for(let attempt=1;attempt<=3;attempt++){
  const push=git(root,['push'],{allowFailure:true});
  if(push.status===0){console.log('Published '+environment+' images at '+tag+' (push '+attempt+'/3)');return {changed:changed.length,pushAttempts:attempt};}
  if(attempt===3)throw Error('GitOps push failed after 3 attempts: '+push.stderr.trim());
  console.error('GitOps push '+attempt+'/3 failed; rebasing before retry');
  git(root,['pull','--rebase','--no-autostash']);
 }
}

function parseArgs(args){
 const options={};
 for(let i=0;i<args.length;i++){
  const key=args[i];
  if(key==='--dry-run'){if(options.dryRun)throw Error('Duplicate --dry-run');options.dryRun=true;continue;}
  const field={'--repo':'repo','--environment':'environment','--tag':'tag'}[key];
  if(!field||options[field]!==undefined||!args[i+1]||args[i+1].startsWith('--'))throw Error('Usage: deploy-images.mjs --repo DIR --environment dev|prod --tag SHA [--dry-run]');
  options[field]=args[++i];
 }
 if(!options.repo)throw Error('--repo is required');
 return options;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{deployImages(parseArgs(process.argv.slice(2)));}catch(error){console.error(error.message);process.exitCode=1;}
}
