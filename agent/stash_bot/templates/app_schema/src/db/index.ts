import { env } from '../env';
import { drizzle } from 'drizzle-orm/node-postgres';

export const db = drizzle(env.APP_DATABASE_URL);
