import { db } from "../db";
import { sql } from 'drizzle-orm';

export const resetDB = async () => {
    await db.execute(sql`drop schema if exists public cascade`);
    await db.execute(sql`create schema public`);
    await db.execute(sql`drop schema if exists drizzle cascade`);
};

resetDB().then(() => console.log("DB reset successfully"));