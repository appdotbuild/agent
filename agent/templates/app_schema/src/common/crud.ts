import { db } from '../db';
import { messagesTable, usersTable } from '../db/schema/application';
import { and, desc, eq } from 'drizzle-orm';

export const putMessage = async (user_id: string, role: 'user' | 'assistant', content: string) => {
    await db.insert(usersTable).values({ id: user_id }).onConflictDoNothing();
    await db.insert(messagesTable).values({ user_id, role, content });
}

export const getHistory = async (user_id: string, history: number = 1, role?: 'user' | 'assistant') => {
    const rows = await db.select({
        role: messagesTable.role,
        content: messagesTable.content,
    })
        .from(messagesTable)
        .where(and(eq(messagesTable.user_id, user_id), role ? eq(messagesTable.role, role) : undefined))
        .orderBy(desc(messagesTable.id))
        .limit(history);
    return rows.reverse();
}