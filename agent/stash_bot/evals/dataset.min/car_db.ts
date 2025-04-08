import { 
  integer, 
  pgTable, 
  text, 
  timestamp,
  varchar,
  uuid
} from "drizzle-orm/pg-core";

export const carDetailsTable = pgTable("car_details", {
  id: uuid("id").primaryKey().defaultRandom(),
  make: varchar("make", { length: 100 }).notNull(),
  model_name: varchar("model_name", { length: 100 }).notNull(),
  year: integer("year").notNull(),
  type: varchar("type", { length: 50 }).notNull(),
});

export const poemStylesTable = pgTable("poem_styles", {
  id: uuid("id").primaryKey().defaultRandom(),
  style_type: varchar("style_type", { length: 50 }).notNull(),
  length: integer("length").notNull(),
  mood: varchar("mood", { length: 50 }).notNull(),
});

export const poemsTable = pgTable("poems", {
  id: uuid("id").primaryKey().defaultRandom(),
  content: text("content").notNull(),
  car_id: uuid("car_id")
    .references(() => carDetailsTable.id)
    .notNull(),
  style_id: uuid("style_id")
    .references(() => poemStylesTable.id)
    .notNull(),
  created_at: timestamp("created_at").notNull().defaultNow(),
});