import fs from 'fs';
import path from 'path';

const DATA_DIR = path.join(process.cwd(),'data');
const ROOT = path.join(process.cwd(),'openclaw-data');

function walk(dir){
  const out=[];
  if(!fs.existsSync(dir)) return out;
  for(const n of fs.readdirSync(dir)){
    const p=path.join(dir,n);
    const st=fs.statSync(p);
    if(st.isDirectory()) out.push(...walk(p)); else out.push(p);
  }
  return out;
}

const files = walk(ROOT).filter(f=>f.endsWith('.md'));
const docs = files.map(abs=>{
  const rel=path.relative(ROOT,abs).replace(/\\/g,'/');
  const txt=fs.readFileSync(abs,'utf8');
  const m=txt.match(/^#\s+(.+)$/m);
  const title=m?m[1]:rel;
  const category = rel.startsWith('mail_reports/') ? 'mail_reports' : rel.startsWith('memory/') ? 'memory' : 'core';
  return {
    path: rel,
    title,
    category,
    lines: txt.split('\n').length,
    updatedAt: fs.statSync(abs).mtime.toISOString()
  };
}).sort((a,b)=>a.path.localeCompare(b.path));

const providers = ['gmail','daum','naver'];
const providerSummary = providers.map(p=>{
  const list=docs.filter(d=>d.path.includes('mail_reports/') && d.path.includes(p));
  return { provider:p, files:list.length, status:list.length>0?'active':'missing' };
});

const agents = [
  { id:'atlas-main', name:'Atlas Main', type:'orchestrator', status:'active' },
  ...providerSummary.map(p=>({ id:`mail-${p.provider}`, name:`Mail ${p.provider.toUpperCase()} Analyzer`, type:'mail-analyzer', status:p.status, files:p.files }))
];

fs.mkdirSync(DATA_DIR,{recursive:true});
fs.writeFileSync(path.join(DATA_DIR,'md-index.json'), JSON.stringify({generatedAt:new Date().toISOString(), root:'openclaw-data', docs},null,2));
fs.writeFileSync(path.join(DATA_DIR,'agents.json'), JSON.stringify({generatedAt:new Date().toISOString(), agents},null,2));

const syncLogPath = path.join(DATA_DIR,'sync-log.json');
let old=[];
if(fs.existsSync(syncLogPath)){
  try{ old=JSON.parse(fs.readFileSync(syncLogPath,'utf8')).logs||[]; }catch{}
}
old.unshift({time:new Date().toISOString(), type:'sync', title:'openclaw-data + md-index regenerated', status:'done'});
old=old.slice(0,200);
fs.writeFileSync(syncLogPath, JSON.stringify({generatedAt:new Date().toISOString(), logs:old},null,2));

console.log('Built data/md-index.json, data/agents.json, data/sync-log.json');
