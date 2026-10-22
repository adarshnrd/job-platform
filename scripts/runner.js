const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');

const target = process.argv[2] || 'start';
const rootDir = process.cwd();

switch (target.toLowerCase()) {
  case 'start':
    require('./start.js');
    break;

  case 'api':
  case 'backend':
    process.argv.push('--backend-only');
    require('./start.js');
    break;

  case 'web':
  case 'frontend':
    process.argv.push('--frontend-only');
    require('./start.js');
    break;

  case 'install':
    require('./install.js');
    break;

  case 'stop': {
    console.log('🛑 Stopping background processes...');
    if (process.platform === 'win32') {
      try {
        execSync('taskkill /F /IM uvicorn.exe /T', { stdio: 'ignore' });
      } catch (e) {}
      try {
        execSync('taskkill /F /IM python.exe /FI "WINDOWTITLE eq uvicorn*" /T', { stdio: 'ignore' });
      } catch (e) {}
      try {
        execSync('taskkill /F /IM node.exe /FI "WINDOWTITLE eq next*" /T', { stdio: 'ignore' });
      } catch (e) {}
    } else {
      try {
        execSync('pkill -f "uvicorn main:app"', { stdio: 'ignore' });
        execSync('pkill -f "next dev"', { stdio: 'ignore' });
      } catch (e) {}
    }
    console.log('✅ Stopped.');
    break;
  }

  case 'help':
  default:
    console.log('Job Platform Command Runner:');
    console.log('  make start    - Start both FastAPI backend and Next.js frontend');
    console.log('  make api      - Start FastAPI backend only');
    console.log('  make web      - Start Next.js frontend only');
    console.log('  make install  - Install all dependencies (Python + Node + Playwright)');
    console.log('  make stop     - Stop running server processes');
    break;
}
