import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

const DATA_DIR = path.join(process.cwd(), 'data');
const ROOT = path.join(process.cwd(), 'openclaw-data');

function walk(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const n of fs.readdirSync(dir)) {
    const p = path.join(dir, n);
    const st = fs.statSync(p);
    if (st.isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}
function safeJson(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}
function safeCmd(cmd, fallback = '') {
  try { return execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); } catch { return fallback; }
}

const now = new Date().toISOString();
const files = walk(ROOT).filter(f => f.endsWith('.md'));
const docs = files.map(abs => {
  const rel = path.relative(ROOT, abs).replace(/\\/g, '/');
  const txt = fs.readFileSync(abs, 'utf8');
  const m = txt.match(/^#\s+(.+)$/m);
  const title = m ? m[1] : rel;
  const category = rel.startsWith('mail_reports/') ? 'mail_reports' : rel.startsWith('memory/') ? 'memory' : 'core';
  return {
    path: rel,
    title,
    category,
    lines: txt.split('\n').length,
    updatedAt: fs.statSync(abs).mtime.toISOString()
  };
}).sort((a, b) => a.path.localeCompare(b.path));

const providers = ['gmail', 'daum', 'naver'];
const providerSummary = providers.map(p => {
  const list = docs.filter(d => d.path.includes('mail_reports/') && d.path.includes(p));
  return { provider: p, files: list.length, status: list.length > 0 ? 'active' : 'missing' };
});

const cron = safeJson(path.join(DATA_DIR, 'cron-jobs.json'), { total: 0, enabled: 0, groups: [] });
const mailAgents = providerSummary.map(p => ({
  id: `mail-${p.provider}`,
  name: `Mail ${p.provider.toUpperCase()} Analyzer`,
  type: 'mail-analyzer',
  status: p.status,
  files: p.files
}));

const agents = [
  { id: 'atlas-main', name: 'Atlas Main', type: 'orchestrator', status: 'active' },
  { id: 'sync-worker', name: 'Workspace Sync Worker', type: 'sync-automation', status: cron.total > 0 ? 'active' : 'unknown' },
  ...mailAgents
];

const commitsTotal = Number(safeCmd('git rev-list --count HEAD', '0'));
const commits7d = Number(safeCmd("git rev-list --count --since='7 days ago' HEAD", '0'));
const mailReportDocs = docs.filter(d => d.path.startsWith('mail_reports/')).length;
const automationScore = Math.min(1, (cron.enabled || 0) / 20);
const dataTraceScore = Math.min(1, docs.length / 40);
const reportScore = mailReportDocs > 0 ? 1 : 0;
const activityScore = Math.min(1, commits7d / 10);
const structureScore = agents.length >= 4 ? 1 : 0.5;
const maturityScore = Math.round(
  25 * structureScore +
  25 * automationScore +
  20 * dataTraceScore +
  15 * reportScore +
  15 * activityScore
);

const kpi = {
  generatedAt: now,
  metrics: {
    activeAgents: agents.filter(a => a.status === 'active').length,
    totalAgents: agents.length,
    automationJobs: cron.enabled || 0,
    indexedDocs: docs.length,
    mailReportDocs,
    commitsTotal,
    commits7d,
    maturityScore
  }
};

const automation = {
  generatedAt: now,
  pipelines: [
    {
      id: 'workspace-sync',
      name: 'Workspace → GitHub Sync',
      status: cron.total > 0 ? 'active' : 'manual',
      frequency: '30m',
      output: ['openclaw-data/*', 'data/md-index.json', 'data/agents.json', 'data/kpi.json']
    },
    {
      id: 'mail-intel',
      name: 'Mail Intelligence Pipeline',
      status: mailReportDocs > 0 ? 'active' : 'inactive',
      frequency: 'AM/PM batch',
      output: ['mail_reports/titles/*', 'mail_reports/requests/*', 'mail_reports/details/*']
    }
  ]
};

fs.mkdirSync(DATA_DIR, { recursive: true });
fs.writeFileSync(path.join(DATA_DIR, 'md-index.json'), JSON.stringify({ generatedAt: now, root: 'openclaw-data', docs }, null, 2));
fs.writeFileSync(path.join(DATA_DIR, 'agents.json'), JSON.stringify({ generatedAt: now, agents, providerSummary }, null, 2));
fs.writeFileSync(path.join(DATA_DIR, 'kpi.json'), JSON.stringify(kpi, null, 2));
fs.writeFileSync(path.join(DATA_DIR, 'automation.json'), JSON.stringify(automation, null, 2));

const syncLogPath = path.join(DATA_DIR, 'sync-log.json');
let old = [];
if (fs.existsSync(syncLogPath)) {
  try { old = JSON.parse(fs.readFileSync(syncLogPath, 'utf8')).logs || []; } catch {}
}
old.unshift({ time: now, type: 'sync', title: 'openclaw-data + dashboard datasets regenerated', status: 'done' });
old = old.slice(0, 200);
fs.writeFileSync(syncLogPath, JSON.stringify({ generatedAt: now, logs: old }, null, 2));

console.log('Built dashboard datasets: md-index, agents, kpi, automation, sync-log');
