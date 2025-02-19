// TODO: REMOVE THIS FILE
import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { resetDB, createDB } from "../../helpers";
import { db } from "../../db";
import { greetingRequestsTable } from "../../db/schema/application";
import type { GreetingRequest } from "../../common/schema";
import { handle as greet } from "../../handlers/greet_handler";

describe("greet handler", () => {
    beforeEach(async () => {
        await createDB();
    });

    afterEach(async () => {
        await resetDB();
    });

    it("should return a greeting", async () => {
        const input: GreetingRequest = { name: "Alice", greeting: "Hello" };
        const greeting = await greet(input);
        expect(greeting).toEqual("Hello, Alice!");
    });

    it("should store the greeting request", async () => {
        const input: GreetingRequest = { name: "Alice", greeting: "Hello" };
        await greet(input);

        const requests = await db.select().from(greetingRequestsTable).execute();
        expect(requests).toHaveLength(1);
        expect(requests[0].name).toEqual("Alice");
        expect(requests[0].greeting).toEqual("Hello");
    });
});

