import { integer, pgTable, pgEnum, text, json } from 'drizzle-orm/pg-core';
import { type ContentBlock } from '../../common/llm';

export const internalUsersTable = pgTable('_internal_users', {
  id: text().primaryKey(),
});

export const msgRolesEnum = pgEnum('msg_roles', ['user', 'assistant']);

export const internalMessagesTable = pgTable('_internal_messages', {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  user_id: text().references(() => internalUsersTable.id),
  role: msgRolesEnum().notNull(),
  content: json().$type<string | Array<ContentBlock>>().notNull(),
});
