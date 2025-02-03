//{{drizzle_definitions}}
import { integer, pgTable, text, timestamp, varchar } from "drizzle-orm/pg-core";

export const poemStylesTable = pgTable("poem_styles", {
  id: integer("id").primaryKey().generatedAlwaysAsIdentity(),
  name: varchar("name", { length: 100 }).notNull().unique(),
  verses_count: integer("verses_count").notNull(),
  lines_per_verse: integer("lines_per_verse").notNull()
});

export const carPoemsTable = pgTable("car_poems", {
  id: integer("id").primaryKey().generatedAlwaysAsIdentity(),
  title: varchar("title", { length: 200 }).notNull(),
  content: text("content").notNull(),
  style_id: integer("style_id")
    .references(() => poemStylesTable.id)
    .notNull(),
  topic: varchar("topic", { length: 100 }).notNull(),
  created_at: timestamp("created_at").notNull().defaultNow()
});