const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const rootDir = path.resolve(__dirname, '..');
const apiDir = path.join(rootDir, 'apps', 'api');
const webDir = path.join(rootDir, 'apps', 'web');
const isWindows = process.platform === 'win32';

function run(cmd, cwd = rootDir) {
  console.log(`> ${cmd}`);
  execSync(cmd, { cwd, stdio: 'inherit' });
}

console.log('📦 Setting up Python virtual environment...');
const venvDir = path.join(apiDir, 'venv');
if (!fs.existsSync(venvDir)) {
  try {
    run('python -m venv venv', apiDir);
  } catch (e) {
    run('python3 -m venv venv', apiDir);
  }
}

const pipCmd = isWindows
  ? path.join(venvDir, 'Scripts', 'pip.exe')
  : path.join(venvDir, 'bin', 'pip');

const pythonCmd = isWindows
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');

console.log('\n📦 Installing Python dependencies...');
if (fs.existsSync(pipCmd)) {
  run(`"${pipCmd}" install -r requirements.txt`, apiDir);
} else {
  run('pip install -r requirements.txt', apiDir);
}

console.log('\n📦 Installing Playwright browsers...');
if (fs.existsSync(pythonCmd)) {
  run(`"${pythonCmd}" -m playwright install chromium`, apiDir);
} else {
  run('python -m playwright install chromium', apiDir);
}

console.log('\n📦 Installing Node dependencies...');
const npmCmd = isWindows ? 'npm.cmd' : 'npm';
run(`${npmCmd} install`, webDir);

console.log('\n✅ All dependencies installed successfully!');
