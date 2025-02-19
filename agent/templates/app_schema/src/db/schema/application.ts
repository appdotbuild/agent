//{{drizzle_definitions}}
// TODO: REMOVE PLACEHOLDER
import { serial, text, pgTable, timestamp } from "drizzle-orm/pg-core";

export const greetingRequestsTable = pgTable("greeting_requests", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  greeting: text("greeting").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});

export const greetingResponsesTable = pgTable("greeting_responses", {
  id: serial("id").primaryKey(),
  request_id: serial("request_id")
    .references(() => greetingRequestsTable.id)
    .notNull(),
  response_text: text("response_text").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});