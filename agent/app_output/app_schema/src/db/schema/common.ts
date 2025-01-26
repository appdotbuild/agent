import { integer, pgTable, pgEnum, text } from "drizzle-orm/pg-core";

export const usersTable = pgTable("users", {
  id: text().primaryKey(),
});

export const msgRolesEnum = pgEnum("msg_roles", ["user", "assistant"]);

export const messagesTable = pgTable("messages", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  user_id: text().references(() => usersTable.id),
  role: msgRolesEnum(),
  content: text(),
});