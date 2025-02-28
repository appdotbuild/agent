import { db } from '../db';
import { and, desc, eq } from 'drizzle-orm';
import { internalMessagesTable, internalUsersTable } from '../db/schema/common';
import { type ContentBlock } from '../common/llm';

export const putMessage = async (user_id: string, role: 'user' | 'assistant', content: string | Array<ContentBlock>) => {
    await db.insert(internalUsersTable).values({ id: user_id }).onConflictDoNothing();
    await db.insert(internalMessagesTable).values({ user_id, role, content });
}

export const putMessageBatch = async (batch : Array<{user_id: string, role: 'user' | 'assistant', content: string | Array<ContentBlock>}>) => {
    const userIds = batch.map(({user_id}) => user_id);
    await db.insert(internalUsersTable).values(userIds.map(id => ({ id }))).onConflictDoNothing();
    await db.insert(internalMessagesTable).values(batch.map(({user_id, role, content}) => ({ user_id, role, content })));
}

export const getHistory = async (user_id: string, history: number = 1, role?: 'user' | 'assistant') => {
    const rows = await db.select({
        role: internalMessagesTable.role,
        content: internalMessagesTable.content,
    })
        .from(internalMessagesTable)
        .where(and(eq(internalMessagesTable.user_id, user_id), role ? eq(internalMessagesTable.role, role) : undefined))
        .orderBy(desc(internalMessagesTable.id))
        .limit(history);
    return rows.reverse();
}