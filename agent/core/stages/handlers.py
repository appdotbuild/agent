from typing import TypedDict
import re


PROMPT = """
Based on TypeSpec application definition and drizzle schema, generate a handler for {{function_name}} function.
Handler always accepts single argument. It should be declared at the beginning as interface Options;
Handler should satisfy following interface:

<handler>
interface Message {
    role: 'user' | 'assistant';
    content: string;
};

interface Handler<Options, Output> {
    preProcessor: (input: Message[]) => Options | Promise<Options>;
    handle: (options: Options) => Output | Promise<Output>;
    postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>;
}

class GenericHandler<Options, Output> implements Handler<Options, Output> {
    constructor(
        public handle: (options: Options) => Output | Promise<Output>,
        public preProcessor: (input: Message[]) => Options | Promise<Options>,
        public postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>
    ) {}

    async execute(input: Message[]): Promise<Message[] | Output> {
        const options = await this.preProcessor(input);
        const result = await this.handle(options);
        return this.postProcessor ? await this.postProcessor(result, input) : result;
    }
}
</handler>

Example handler implementation:

<handler>
import { db } from "../db";
import { customTable } from '../db/schema/application'; // all drizzle tables are defined in this file

interface Options {
    content: string;
};

const handle = (options: Options): string => {
    await db.insert(customTable).values({ content: options.content }).execute();
    return input;
};
</handler>

TypeSpec is extended with special decorator that indicates that this function
is processed by language model parametrized with number of previous messages passed to the LLM.

extern dec llm_func(target: unknown, history: valueof int32);

Application Definitions:

<typescript_schema>
{{typescript_schema}}
</typescript_schema>

<drizzle>
{{drizzle_schema}}
</drizzle>

Handler to implement: {{function_name}}

Return output within <handler> tag. Generate only the handler function and table imports from drizzle schema, omit pre- and post-processors.
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
