import 'dotenv/config';
import { defineConfig } from 'drizzle-kit';
import { env } from './src/env';

export default defineConfig({
  out: './drizzle',
  schema: './src/db/schema',
  dialect: 'postgresql',
  dbCredentials: {
    url: env.APP_DATABASE_URL,
  },
  strict: true,
});
