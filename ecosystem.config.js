// ============================================================
// Influencer Trigger — PM2 process management configuration
//
// Usage:
//   pm2 start ecosystem.config.js          # start all
//   pm2 restart ecosystem.config.js        # restart all
//   pm2 stop ecosystem.config.js           # stop all
//   pm2 save && pm2 startup                # auto-start on reboot
// ============================================================

module.exports = {
  apps: [
    {
      name: 'influencer-backend',
      script: '.venv/bin/python',
      args: '-m uvicorn app.main:app --host 0.0.0.0 --port 8000',
      cwd: './server',
      interpreter: 'none',            // Python manages its own interpreter
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
      env: {
        NODE_ENV: 'production',
      },
      error_file: './logs/backend-error.log',
      out_file: './logs/backend-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
    {
      // Optional: serve frontend via a simple static server (prefer nginx in prod)
      name: 'influencer-frontend',
      script: 'npx',
      args: 'serve -s dist -l 3000',
      cwd: './client',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      env: {
        NODE_ENV: 'production',
      },
      error_file: './logs/frontend-error.log',
      out_file: './logs/frontend-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
}
