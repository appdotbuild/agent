import { 
    pgTable, 
    text, 
    integer, 
    timestamp, 
    real,
    primaryKey,
    serial,
    boolean
  } from "drizzle-orm/pg-core";
  
  // Main exercises table
  export const exercisesTable = pgTable("exercises", {
    id: serial("id").primaryKey(),
    name: text("name").notNull(),
    muscle_group: text("muscle_group").notNull(),
    sets: integer("sets").notNull(),
    reps: integer("reps").notNull(),
    weight: real("weight").notNull(),
    timestamp: timestamp("timestamp").notNull().defaultNow()
  });
  
  // Equipment table
  export const equipmentTable = pgTable("equipment", {
    id: serial("id").primaryKey(),
    name: text("name").unique().notNull()
  });
  
  // Junction table for exercise-equipment relationship
  export const exerciseEquipmentTable = pgTable("exercise_equipment", {
    exercise_id: integer("exercise_id")
      .references(() => exercisesTable.id),
    equipment_id: integer("equipment_id")
      .references(() => equipmentTable.id),
  }, (table) => ({
    pk: primaryKey({ columns: [table.exercise_id, table.equipment_id] })
  }));
  
  // Table to track currently available equipment
  export const equipmentAvailabilityTable = pgTable("equipment_availability", {
    equipment_id: integer("equipment_id")
      .references(() => equipmentTable.id)
      .primaryKey(),
    is_available: boolean("is_available").notNull().default(true),
    last_updated: timestamp("last_updated").notNull().defaultNow()
  });
  
  // Table to store workout routines
  export const workoutRoutinesTable = pgTable("workout_routines", {
    id: serial("id").primaryKey(),
    total_duration: integer("total_duration").notNull(), // stored in seconds
    difficulty: text("difficulty").notNull(),
    created_at: timestamp("created_at").notNull().defaultNow()
  });
  
  // Table to store exercises in workout routines
  export const routineExercisesTable = pgTable("routine_exercises", {
    routine_id: integer("routine_id")
      .references(() => workoutRoutinesTable.id),
    exercise_id: integer("exercise_id")
      .references(() => exercisesTable.id),
    sequence_order: integer("sequence_order").notNull(),
  }, (table) => ({
    pk: primaryKey({ columns: [table.routine_id, table.exercise_id] })
  }));