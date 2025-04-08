import { boolean, pgTable, text, timestamp, integer } from "drizzle-orm/pg-core";

export const translationRequestsTable = pgTable("translation_requests", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  text: text().notNull(),
  is_formal: boolean().notNull().default(false),
  include_pinyin: boolean().notNull().default(true),
  context: text(),
  created_at: timestamp().notNull().defaultNow(),
});

export const translationsTable = pgTable("translations", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  request_id: integer().references(() => translationRequestsTable.id),
  english: text().notNull(),
  chinese: text().notNull(),
  pinyin: text(),
  usage_notes: text(),
  created_at: timestamp().notNull().defaultNow(),
});