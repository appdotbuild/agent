import { createClient } from '@libsql/client';
import { drizzle } from 'drizzle-orm/libsql';
import { internalMessagesTable, internalUsersTable } from './schema';
import type { ContentBlock } from '../../common/llm';

// Create an in-memory SQLite database for testing
const client = createClient({
  url: 'file::memory:',
});

export const db = drizzle(client);

// Initialize the database schema
export async function initDatabase() {
  // Create tables
  await client.execute(`
    CREATE TABLE IF NOT EXISTS _internal_users (
      id TEXT PRIMARY KEY
    )
  `);

  await client.execute(`
    CREATE TABLE IF NOT EXISTS _internal_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT REFERENCES _internal_users(id),
      role TEXT NOT NULL,
      content TEXT NOT NULL
    )
  `);
}

// Functions that mirror the CRUD operations but for the SQLite database
export async function putMessage(
  user_id: string,
  role: 'user' | 'assistant',
  content: string | Array<ContentBlock>
) {
  // First ensure user exists
  await db
    .insert(internalUsersTable)
    .values({ id: user_id })
    .onConflictDoNothing();

  // Then insert the message
  await db.insert(internalMessagesTable).values({
    user_id,
    role,
    content: content as any, // SQLite stores JSON as string
  });
}

export async function putMessageBatch(
  batch: Array<{
    user_id: string;
    role: 'user' | 'assistant';
    content: string | Array<ContentBlock>;
  }>
) {
  // First ensure all users exist
  const userIds = [...new Set(batch.map(({ user_id }) => user_id))];
  if (userIds.length > 0) {
    await db
      .insert(internalUsersTable)
      .values(userIds.map((id) => ({ id })))
      .onConflictDoNothing();
  }

  // Then insert all messages
  if (batch.length > 0) {
    await db.insert(internalMessagesTable).values(
      batch.map(({ user_id, role, content }) => ({
        user_id,
        role,
        content: content as any, // SQLite stores JSON as string
      }))
    );
  }
}

export async function getHistory(
  user_id: string,
  history: number = 1,
  role?: 'user' | 'assistant'
) {
  // Build the query conditions
  const conditions = [];
  conditions.push(`user_id = '${user_id}'`);
  if (role) {
    conditions.push(`role = '${role}'`);
  }

  // Execute the query
  const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
  const result = await client.execute({
    sql: `
      SELECT role, content
      FROM _internal_messages
      ${whereClause}
      ORDER BY id DESC
      LIMIT ${history}
    `,
  });

  // Parse the results
  return result.rows
    .map(row => ({
      role: row.role as 'user' | 'assistant',
      content: JSON.parse(row.content as string),
    }))
    .reverse();
}