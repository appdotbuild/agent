import { index, integer, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const carsTable = pgTable("cars", {
  id: uuid("id").primaryKey().defaultRandom(),
  make: text("make").notNull(),
  model: text("model").notNull(),
  year: integer("year").notNull(),
});

export const poemsTable = pgTable("poems", {
  id: uuid("id").primaryKey().defaultRandom(),
  content: text("content").notNull(),
  car_id: uuid("car_id")
    .notNull()
    .references(() => carsTable.id),
  created_at: timestamp("created_at").notNull().defaultNow(),
});

export const favoritePoemsTable = pgTable("favorite_poems", {
  poem_id: uuid("poem_id")
    .primaryKey()
    .references(() => poemsTable.id),
  marked_at: timestamp("marked_at").notNull().defaultNow(),
});

// Indexes for better query performance
export const carSearchIndex = index("car_search_idx", carsTable, ["make", "model", "year"]);
export const poemDateIndex = index("poem_date_idx", poemsTable, ["created_at"]);
export const favoriteDateIndex = index("favorite_date_idx", favoritePoemsTable, ["marked_at"]);