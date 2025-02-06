//{{drizzle_definitions}}
import { serial, text, timestamp, pgTable } from "drizzle-orm/pg-core";

export const greetingsTable = pgTable("greetings", {
  id: serial("id").primaryKey(),
  greeting: text("greeting").notNull(),
  user_name: text("user_name"),
  created_at: timestamp("created_at").defaultNow().notNull()
});

export const responsesTable = pgTable("responses", {
  id: serial("id").primaryKey(),
  greeting_id: serial("greeting_id")
    .references(() => greetingsTable.id)
    .notNull(),
  response_text: text("response_text").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});