import { decimal, pgTable, text, uuid, primaryKey } from "drizzle-orm/pg-core";

export const physicalConstantsTable = pgTable("physical_constants", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull().unique(),
  symbol: text("symbol").notNull(),
  value: decimal("value", { precision: 65, scale: 30 }).notNull(),
  unit: text("unit").notNull(),
  uncertainty: decimal("uncertainty", { precision: 65, scale: 30 }).notNull(),
  description: text("description").notNull(),
});

export const constantRelationsTable = pgTable("constant_relations", {
  id: uuid("id").primaryKey().defaultRandom(),
  target_constant_id: uuid("target_constant_id")
    .references(() => physicalConstantsTable.id)
    .notNull(),
  formula: text("formula").notNull(),
});

export const sourceConstantsRelationsTable = pgTable("source_constants_relations", {
  constant_id: uuid("constant_id")
    .references(() => physicalConstantsTable.id)
    .notNull(),
  relation_id: uuid("relation_id")
    .references(() => constantRelationsTable.id)
    .notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.constant_id, table.relation_id] }),
}));