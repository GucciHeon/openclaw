import fs from 'fs';
import path from 'path';

const SRC = '/home/user/.openclaw/workspace';
const DST = path.join(process.cwd(), 'openclaw-data');

const ROOT_FILES = ['AGENTS.md','SOUL.md','USER.md','IDENTITY.md','TOOLS.md','HEARTBEAT.md'];
const DIRS = ['mail_reports','memory'];

function ensureDir(p){ fs.mkdirSync(p,{recursive:true}); }
function copyFile(src,dst){ ensureDir(path.dirname(dst)); fs.copyFileSync(src,dst); }
function copyDir(src,dst){
  if(!fs.existsSync(src)) return;
  ensureDir(dst);
  for(const name of fs.readdirSync(src)){
    const s=path.join(src,name), d=path.join(dst,name);
    const st=fs.statSync(s);
    if(st.isDirectory()) copyDir(s,d); else copyFile(s,d);
  }
}

ensureDir(DST);
for(const f of ROOT_FILES){
  const s=path.join(SRC,f);
  if(fs.existsSync(s)) copyFile(s,path.join(DST,f));
}
for(const dir of DIRS) copyDir(path.join(SRC,dir), path.join(DST,dir));

console.log('Synced OpenClaw workspace data -> openclaw-data');
