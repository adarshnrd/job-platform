const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const rootDir = path.resolve(__dirname, '..');
const apiDir = path.join(rootDir, 'apps', 'api');
const webDir = path.join(rootDir, 'apps', 'web');

// 1. Ensure .env files are in place
const rootEnv = path.join(rootDir, '.env');
const rootEnvExample = path.join(rootDir, '.env.example');
const apiEnv = path.join(apiDir, '.env');
const webEnv = path.join(webDir, '.env.local');

if (!fs.existsSync(rootEnv) && fs.existsSync(rootEnvExample)) {
  console.log('⚠️  No root .env found. Copying from .env.example...');
  fs.copyFileSync(rootEnvExample, rootEnv);
}

if (fs.existsSync(rootEnv)) {
  if (!fs.existsSync(apiEnv)) {
    fs.copyFileSync(rootEnv, apiEnv);
  }
  if (!fs.existsSync(webEnv)) {
    fs.copyFileSync(rootEnv, webEnv);
  }
}

// 2. Resolve Python Executable
function getPythonExecutable() {
  const isWindows = process.platform === 'win32';
  const venvPaths = isWindows
    ? [
        path.join(apiDir, 'venv', 'Scripts', 'python.exe'),
        path.join(apiDir, '.venv', 'Scripts', 'python.exe'),
      ]
    : [
        path.join(apiDir, 'venv', 'bin', 'python'),
        path.join(apiDir, '.venv', 'bin', 'python'),
      ];

  for (const p of venvPaths) {
    if (fs.existsSync(p)) return p;
  }
  return isWindows ? 'python' : 'python3';
}

const pythonCmd = getPythonExecutable();
const isWindows = process.platform === 'win32';
const npmCmd = isWindows ? 'npm.cmd' : 'npm';

console.log('==============================================');
console.log('🚀 Starting Job Platform Dev Environment...');
console.log(`📌 Backend Python: ${pythonCmd}`);
console.log(`📌 Frontend Runner: ${npmCmd}`);
console.log('==============================================\n');

const isBackendOnly = process.argv.includes('--backend-only');
const isFrontendOnly = process.argv.includes('--frontend-only');

const processes = [];

function startBackend() {
  console.log('⚡ [API] Starting FastAPI on http://localhost:8000 (docs: http://localhost:8000/docs)...');
  const proc = spawn(pythonCmd, ['-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'], {
    cwd: apiDir,
    stdio: 'inherit',
    shell: true,
  });
  processes.push(proc);
}

function startFrontend() {
  console.log('⚡ [WEB] Starting Next.js on http://localhost:3000...');
  const proc = spawn(npmCmd, ['run', 'dev'], {
    cwd: webDir,
    stdio: 'inherit',
    shell: true,
  });
  processes.push(proc);
}

if (isBackendOnly) {
  startBackend();
} else if (isFrontendOnly) {
  startFrontend();
} else {
  startBackend();
  startFrontend();
}

function cleanup() {
  console.log('\n🛑 Shutting down development servers...');
  for (const proc of processes) {
    if (proc && !proc.killed) {
      if (isWindows && proc.pid) {
        try {
          spawn('taskkill', ['/pid', proc.pid.toString(), '/T', '/F'], { stdio: 'ignore' });
        } catch (e) {}
      } else {
        proc.kill('SIGINT');
      }
    }
  }
  process.exit();
}

process.on('SIGINT', cleanup);
process.on('SIGTERM', cleanup);
process.on('exit', cleanup);
