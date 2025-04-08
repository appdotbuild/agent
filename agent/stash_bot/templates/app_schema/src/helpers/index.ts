import { db } from '../db';
import { sql } from 'drizzle-orm';
import * as application_schema from '../db/schema/application';
import * as common_schema from '../db/schema/common';
import { generateDrizzleJson, generateMigration } from 'drizzle-kit/api';

export const resetDB = async () => {
  await db.execute(sql`drop schema if exists public cascade`);
  await db.execute(sql`create schema public`);
  await db.execute(sql`drop schema if exists drizzle cascade`);
};

export const createDB = async () => {
  const migrationStatements = await generateMigration(
    generateDrizzleJson({}),
    generateDrizzleJson({ ...common_schema, ...application_schema })
  );
  await db.execute(migrationStatements.join('\n'));
};
