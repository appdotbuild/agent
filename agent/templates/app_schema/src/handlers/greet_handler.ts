// TODO: REMOVE THIS FILE
import { db } from "../db";
import { type GreetingRequest, greet } from "../common/schema";
import { greetingRequestsTable, greetingResponsesTable } from "../db/schema/application";

export const handle: typeof greet = async (options: GreetingRequest): Promise<string> => {
    // Insert the greeting request
    const [insertedRequest] = await db
        .insert(greetingRequestsTable)
        .values({
            name: options.name,
            greeting: options.greeting,
        })
        .returning();

    // Construct the response text
    const responseText = `${options.greeting}, ${options.name}!`;

    // Store the response
    await db
        .insert(greetingResponsesTable)
        .values({
            request_id: insertedRequest.id,
            response_text: responseText,
        });

    return responseText;
};