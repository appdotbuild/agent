import re
from pathlib import Path

def analyze_handler_tables(handler_code):
    """
    Extract all table references from a handler file
    """
    # Regular expression to find table imports from application.ts
    import_pattern = re.compile(r'import\s+{([^}]+)}\s+from\s+"../db/schema/application"')
    import_match = import_pattern.search(handler_code)
    
    if not import_match:
        return []
    
    # Parse the imports
    imports_text = import_match.group(1)
    table_names = [name.strip() for name in imports_text.split(',')]
    return table_names

def analyze_drizzle_schema(schema_code):
    """
    Extract all table definitions from a drizzle schema file
    """
    # Regular expression to find table exports
    table_pattern = re.compile(r'export\s+const\s+(\w+)\s*=\s*pgTable')
    table_matches = table_pattern.findall(schema_code)
    
    return table_matches

def validate_handler_schema_compatibility(handler_code, schema_code):
    """
    Validate that all tables referenced in the handler are defined in the schema
    """
    handler_tables = analyze_handler_tables(handler_code)
    schema_tables = analyze_drizzle_schema(schema_code)
    
    missing_tables = [table for table in handler_tables if table not in schema_tables]
    return {
        "handler_tables": handler_tables,
        "schema_tables": schema_tables,
        "missing_tables": missing_tables,
        "is_compatible": len(missing_tables) == 0
    }

# Example test data
# The drizzle schema from our original example
example_schema = """
import { pgTable, text, timestamp, uuid, varchar, serial } from "drizzle-orm/pg-core";

// Users table to store registered user information
export const usersTable = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: varchar("name", { length: 255 }).notNull(),
  created_at: timestamp("created_at").defaultNow().notNull(),
  updated_at: timestamp("updated_at").defaultNow().notNull()
});

// Greeting preferences table to store customization options per user
export const greetingPreferencesTable = pgTable("greeting_preferences", {
  id: serial("id").primaryKey(),
  user_id: uuid("user_id").references(() => usersTable.id).notNull(),
  preferred_time_of_day: varchar("preferred_time_of_day", { length: 50 }),
  custom_message: text("custom_message"),
  created_at: timestamp("created_at").defaultNow().notNull(),
  updated_at: timestamp("updated_at").defaultNow().notNull()
});

// Greeting history to track bot interactions
export const greetingHistoryTable = pgTable("greeting_history", {
  id: serial("id").primaryKey(),
  user_id: uuid("user_id").references(() => usersTable.id).notNull(),
  input_text: text("input_text"),
  extracted_name: varchar("extracted_name", { length: 255 }),
  time_of_day: varchar("time_of_day", { length: 50 }),
  output_greeting: text("output_greeting"),
  created_at: timestamp("created_at").defaultNow().notNull()
});
"""

# The handler that references nameChangesTable
example_handler = """
import { eq } from "drizzle-orm";
import { db } from "../db";
import { type UpdateUserRequest, updateUserName } from "../common/schema";
import { usersTable, nameChangesTable } from "../db/schema/application";

export const handle: typeof updateUserName = async (options: UpdateUserRequest): Promise<string> => {
  // Find the user with the current name
  const existingUsers = await db
    .select()
    .from(usersTable)
    .where(eq(usersTable.name, options.currentName));

  if (existingUsers.length === 0) {
    throw new Error(`User with name ${options.currentName} not found`);
  }

  const user = existingUsers[0];

  // Update the user's name
  await db
    .update(usersTable)
    .set({ 
      name: options.newName,
      updated_at: new Date()
    })
    .where(eq(usersTable.id, user.id));

  // Record the name change in the history table
  await db
    .insert(nameChangesTable)
    .values({
      user_id: user.id,
      previous_name: options.currentName,
      new_name: options.newName
    });

  return `User name updated from ${options.currentName} to ${options.newName}`;
};
"""

def main():
    # Analyze the compatibility
    result = validate_handler_schema_compatibility(example_handler, example_schema)
    
    # Print results
    print("Handler references these tables:", result["handler_tables"])
    print("Schema defines these tables:", result["schema_tables"])
    
    if result["is_compatible"]:
        print("✅ All tables referenced in the handler are defined in the schema.")
    else:
        print(f"❌ Missing tables in schema: {result['missing_tables']}")
        
        # Suggest a fix: add the missing tables to the schema
        for table in result["missing_tables"]:
            if table == "nameChangesTable":
                print("\nSuggested fix to add to schema:")
                print("""
// Name changes history to track user name updates
export const nameChangesTable = pgTable("name_changes", {
  id: serial("id").primaryKey(),
  user_id: uuid("user_id").references(() => usersTable.id).notNull(),
  previous_name: varchar("previous_name", { length: 255 }).notNull(),
  new_name: varchar("new_name", { length: 255 }).notNull(),
  changed_at: timestamp("changed_at").defaultNow().notNull()
});
""")

if __name__ == "__main__":
    main()