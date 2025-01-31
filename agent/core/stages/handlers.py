from typing import TypedDict
import re


PROMPT = """
Based on TypeSpec application definition and drizzle schema, generate a handler for {{function_name}} function.

Handler should satisfy following interface:

<handler>
interface Message {
    role: 'user' | 'assistant';
    content: string;
};

interface Handler<Args extends any[], Output> {
    preProcessor: (input: Message[]) => Args | Promise<Args>;
    handle: (...args: Args) => Output | Promise<Output>;
    postProcessor: (output: Output) => Message[] | Promise<Message[]>;
}

class GenericHandler<Args extends any[], Output> implements Handler<Args, Output> {
    constructor(
        public handle: (...args: Args) => Output | Promise<Output>,
        public preProcessor: (input: Message[]) => Args | Promise<Args>,
        public postProcessor: (output: Output) => Message[] | Promise<Message[]>
    ) {}

    async execute(input: Message[]): Promise<Message[] | Output> {
        const args = await this.preProcessor(input);
        const result = await this.handle(...args);
        return this.postProcessor ? await this.postProcessor(result) : result;
    }
}
</handler>

Example handler implementation:

<handler>
import { db } from "../db";
import { customTable } from '../db/schema/application'; // all drizzle tables are defined in this file
import { Message, Person } from "../common/schema";

const handle = (input: string): string => {
    await db.insert(customTable).values({ content: input }).execute();
    return input;
};
</handler>

TypeSpec is extended with special decorator that indicates that this function
is processed by language model parametrized with number of previous messages passed to the LLM.

extern dec llm_func(target: unknown, history: valueof int32);

Application Definitions:

<typespec>
{{typespec_definitions}}
</typespec>

<drizzle>
{{drizzle_schema}}
</drizzle>

Handler to implement: {{function_name}}

Return output within <handler> tag. Generate only the handler function and table imports, omit pre- and post-processors.
Handler code should contain just explicit logic such as database operations, performing calculations etc.
""".strip()


class HandlerInput(TypedDict):
    typespec_definitions: str
    drizzle_schema: str
    function_name: str


class HandlerOutput(TypedDict):
    handler: str


def parse_output(output: str) -> HandlerOutput:
    pattern = re.compile(r"<handler>(.*?)</handler>", re.DOTALL)
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output")
    handler = match.group(1).strip()
    return HandlerOutput(handler=handler)
