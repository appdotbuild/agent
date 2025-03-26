import { integer, text, sqliteTable } from 'drizzle-orm/sqlite-core';
import type { ContentBlock } from '../../common/llm';

export const internalUsersTable = sqliteTable('_internal_users', {
  id: text('id').primaryKey(),
});

export const internalMessagesTable = sqliteTable('_internal_messages', {
  id: integer('id', { mode: 'number' }).primaryKey({ autoIncrement: true }),
  user_id: text('user_id').references(() => internalUsersTable.id),
  role: text('role').notNull(),
  content: text('content', { mode: 'json' }).$type<string | Array<ContentBlock>>().notNull(),
});