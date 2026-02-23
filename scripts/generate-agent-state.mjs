import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const ROOT = '/home/user/.openclaw/workspace';
const TARGETS = [
  'AGENTS.md',
  'SOUL.md',
  'USER.md',
  'IDENTITY.md',
  'HEARTBEAT.md',
  'TOOLS.md'
];

function sha256(content) {
  return crypto.createHash('sha256').update(content).digest('hex');
}

function safeRead(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch {
    return null;
  }
}

const files = [];
for (const rel of TARGETS) {
  const abs = path.join(ROOT, rel);
  const content = safeRead(abs);
  if (content == null) {
    files.push({ path: rel, exists: false });
    continue;
  }
  files.push({
    path: rel,
    exists: true,
    bytes: Buffer.byteLength(content, 'utf8'),
    lines: content.split('\n').length,
    sha256: sha256(content)
  });
}

const memoryDir = path.join(ROOT, 'memory');
let memoryFiles = [];
try {
  const names = fs.readdirSync(memoryDir).filter(n => n.endsWith('.md')).sort();
  memoryFiles = names.map(name => {
    const abs = path.join(memoryDir, name);
    const content = safeRead(abs) ?? '';
    return {
      path: `memory/${name}`,
      bytes: Buffer.byteLength(content, 'utf8'),
      lines: content.split('\n').length,
      sha256: sha256(content)
    };
  });
} catch {
  memoryFiles = [];
}

const combined = sha256(JSON.stringify({ files, memoryFiles }));
const output = {
  generatedAt: new Date().toISOString(),
  sourceRoot: ROOT,
  policy: 'Hashes are computed from real runtime MD files used by Jarvis.',
  combinedSha256: combined,
  files,
  memoryFiles
};

fs.writeFileSync(
  path.join(process.cwd(), 'data', 'agent-state.json'),
  JSON.stringify(output, null, 2),
  'utf8'
);

console.log('Generated data/agent-state.json');
