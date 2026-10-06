import { execSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'

export default async function globalSetup() {
  const root = path.resolve(__dirname, '..', '..')
  const testDbPath = path.join(root, 'e2e', 'test.db')
  const seedSql = path.join(root, 'e2e', 'fixtures', 'seed.sql')

  // Remove old test DB if present
  if (fs.existsSync(testDbPath)) {
    fs.unlinkSync(testDbPath)
  }

  // Create DB and apply migrations via alembic, then load seed
  const backendDir = path.join(root, 'backend')
  const dbUrl = `sqlite:///${testDbPath.replace(/\\/g, '/')}`

  execSync(`uv run alembic upgrade head`, {
    cwd: backendDir,
    env: { ...process.env, DATABASE_URL: dbUrl },
    stdio: 'pipe',
  })

  // Load seed SQL via Python sqlite3
  const seedScript = `
import sqlite3, pathlib
db = sqlite3.connect(r'${testDbPath}')
sql = pathlib.Path(r'${seedSql}').read_text(encoding='utf-8')
db.executescript(sql)
db.commit()
db.close()
print('Seed loaded.')
`
  execSync(`uv run python -c "${seedScript.replace(/\n/g, ' ')}"`, {
    cwd: backendDir,
    stdio: 'pipe',
  })

  // Write env file for webServer to pick up
  const envPath = path.join(root, 'e2e', '.env.test')
  fs.writeFileSync(envPath, `DATABASE_URL=${dbUrl}\n`)

  console.log(`[e2e] Seed DB created at ${testDbPath}`)
}
