import tempfile
import logging
import os
import subprocess
import docker
import random
import string
import time

from unittest.mock import MagicMock
from anthropic import AnthropicBedrock
from anthropic.types import Message, TextBlock, Usage, ToolUseBlock
from application import Application, langfuse_context, feature_flags
from compiler.core import Compiler
from core.interpolator import Interpolator

logging.basicConfig(level=logging.INFO)


def _wrap_anthropic_response(text: str | None = None, tool_use: dict | None = None):
    if text is not None:
        content = [TextBlock(type="text", text=text)]
    else:
        content = [ToolUseBlock(id="tool_use", input=tool_use, name="extract_user_functions", type="tool_use")]

    return Message(
        id="msg_123",
        type="message",
        role="assistant",
        content=content,
        model="claude-3-5-sonnet-20241022",
        usage=Usage(
            input_tokens=10,
            output_tokens=20
        )
    )


def get_real_antropic_response(prompt: str | None = None, messages: list[dict] | None = None):
    if messages is None:
        messages = [{"role": "user", "content": prompt or ""}]
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    response = client.messages.create(messages=messages,
        max_tokens=8192,
        model="anthropic.claude-3-5-sonnet-20241022-v2:0"

    )
    return response.content[-1].text


def _get_pseudo_llm_response(*args, **kwargs):
    messages = kwargs["messages"]
    prompt = messages[-1]["content"]
    text = None
    tool_use = None

    if "generate TypeSpec models" in prompt:
        print("\tLLM: generate TypeSpec models")
        text = """
        <reasoning>
        Based on the description, I'll create a simple response bot with following considerations:
        1. Need a single function to handle inputs
        2. Input model should contain the message to validate
        3. Response model should contain the reply message
        4. No need for complex data structures as the bot has simple logic
        5. Function should maintain minimal history (1 message) to potentially handle empty input cases
        6. No need for date/time types as there's no temporal logic
        7. Input validation will be handled by LLM before passing to the handler
        </reasoning>

        <typespec>
        model InputMessage {
            content: string;
        }

        model ResponseMessage {
            reply: string;
        }

        interface SimpleResponseBot {
        @llm_func("process user input and generate response")
            processInput(options: InputMessage): ResponseMessage;
        }
        </typespec>
        """
    elif "Refine the following prompt" in prompt:
        print("\tLLM: refine prompt")
        text = """
        <reasoning>
        This is a simple chatbot with very basic logic. Let's break down the core requirements while keeping it minimal and clear. The bot needs to recognize input types and provide specific responses. No need for complex processing or state management. Just input validation and two possible outputs. Need to specify what happens with mixed input or edge cases to avoid ambiguity.
        </reasoning>

        <requirements>
        A simple response bot that follows these rules:

        Input Handling:
        - Accepts any user input
        - Validates if input is text-only or numeric-only
        - Mixed inputs (containing both numbers and text) should be treated as text

        Responses:
        - Returns "hello" for any text-based input
        - Returns "42" for any numeric input (whole numbers or decimals)
        - Empty inputs should prompt user to enter something

        Excluded from MVP:
        - Special character handling
        - Multiple language support
        - Response variations
        - Input history
        - Complex calculations
        </requirements>
        """

    elif "generate Zod TypeScript data types" in prompt:
        print("\tLLM: generate TS data types")
        text = """
        <reasoning>
        The application is a simple bot that processes input messages and generates responses.
        It consists of:
        - InputMessage model for receiving user input with content
        - ResponseMessage model for generating bot replies
        - SimpleResponseBot interface that processes the input and returns a response
        The processing is done using LLM functionality as indicated by the @llm_func decorator.
        </reasoning>

        <typescript>
        import { z } from 'zod';

        export const inputMessageSchema = z.object({
            content: z.string(),
        });

        export type InputMessage = z.infer<typeof inputMessageSchema>;

        export const responseMessageSchema = z.object({
            reply: z.string(),
        });

        export type ResponseMessage = z.infer<typeof responseMessageSchema>;

        export declare function processInput(options: InputMessage): Promise<ResponseMessage>;
        </typescript>
        """
    elif "generate Drizzle schema" in prompt:
        print("\tLLM: generate Drizzle schema")
        text = """
        <reasoning>
        hello world
        </reasoning>

        <drizzle>
        import { integer, pgTable, text, timestamp, boolean } from "drizzle-orm/pg-core";

        export const messagesTable = pgTable("messages", {
          id: integer().primaryKey().generatedAlwaysAsIdentity(),
          content: text().notNull(),
          is_response: boolean().default(false).notNull(),
          created_at: timestamp().defaultNow().notNull(),
        });

        export const conversationsTable = pgTable("conversations", {
          id: integer().primaryKey().generatedAlwaysAsIdentity(),
          created_at: timestamp().defaultNow().notNull(),
        });

        export const conversationMessagesTable = pgTable("conversation_messages", {
          id: integer().primaryKey().generatedAlwaysAsIdentity(),
          conversation_id: integer()
            .references(() => conversationsTable.id)
            .notNull(),
          message_id: integer()
            .references(() => messagesTable.id)
            .notNull(),
          sequence_number: integer().notNull(),
          created_at: timestamp().defaultNow().notNull(),
        });
        </drizzle>
        """
    elif "generate prompt for the LLM to classify which function should handle user request" in prompt:
        print("\tLLM: generate prompt for the LLM to classify which function should handle user request")
        tool_use = {
          "user_functions":
              [
                  {
                      "name": "processInput",
                      "description": "Process user input messages and generate appropriate responses. This function handles general conversational interactions by taking a text input and returning a relevant response.",
                      "examples": [
                          "Hello, how are you?",
                          "What's the weather like?",
                          "Can you help me with something?",
                          "Tell me a joke",
                          "What can you do?",
                          "What is your name?"
                      ]
                  }
              ]
        }

    elif "generate a unit test suite" in prompt:
        print("\tLLM: generate a unit test suite for")
        text = """
        I'll help generate unit tests for the processInput function based on the provided schemas. Here's the test suite:

        <imports>
        import { expect, it } from "bun:test";
        import { db } from "../../db";
        import { messagesTable, conversationMessagesTable, conversationsTable } from "../../db/schema/application";
        import { eq } from "drizzle-orm";
        import type { InputMessage, ResponseMessage } from "../../common/schema";
        </imports>

        <test>
        it("should process input and return response", async () => {
          const input: InputMessage = { content: "Hello AI" };
          const response = await processInput(input);
          expect(response).toBeDefined();
          expect(response.reply).toBeDefined();
          expect(typeof response.reply).toBe("string");
        });
        </test>

        <test>
        it("should store input message in database", async () => {
          const input: InputMessage = { content: "Test message" };
          await processInput(input);

          const messages = await db
            .select()
            .from(messagesTable)
            .where(eq(messagesTable.is_response, false))
            .execute();

          expect(messages).toHaveLength(1);
          expect(messages[0].content).toBe("Test message");
        });
        </test>

        <test>
        it("should store response message in database", async () => {
          const input: InputMessage = { content: "Test question" };
          const response = await processInput(input);

          const messages = await db
            .select()
            .from(messagesTable)
            .where(eq(messagesTable.is_response, true))
            .execute();

          expect(messages).toHaveLength(1);
          expect(messages[0].content).toBe(response.reply);
        });
        </test>

        <test>
        it("should create conversation with proper message sequence", async () => {
          const input: InputMessage = { content: "New conversation" };
          await processInput(input);

          const conversations = await db
            .select()
            .from(conversationsTable)
            .execute();

          expect(conversations).toHaveLength(1);

          const conversationMessages = await db
            .select()
            .from(conversationMessagesTable)
            .where(eq(conversationMessagesTable.conversation_id, conversations[0].id))
            .execute();

          expect(conversationMessages).toHaveLength(2);
          expect(conversationMessages[0].sequence_number).toBe(1);
          expect(conversationMessages[1].sequence_number).toBe(2);
        });
        </test>

        """

    elif "generate a handler" in prompt:
        print("\tLLM: generate a handler")
        text = """
        I'll help you create a handler for the processInput function that follows the given requirements and style guidelines.

        <handler>
        import { type InputMessage } from "../common/schema";
        import { processInput } from "../common/schema";
        import { db } from "../db";
        import { messagesTable, conversationsTable, conversationMessagesTable } from "../db/schema/application";

        export const handle: typeof processInput = async (options: InputMessage): Promise<{ reply: string }> => {
            // Start a transaction to ensure data consistency
            return await db.transaction(async (tx) => {
                // Create a new conversation
                const [conversation] = await tx
                    .insert(conversationsTable)
                    .values({})
                    .returning({ id: conversationsTable.id });

                // Store the input message
                const [inputMessage] = await tx
                    .insert(messagesTable)
                    .values({
                        content: options.content,
                        is_response: false,
                    })
                    .returning({ id: messagesTable.id });

                // Link input message to conversation
                await tx
                    .insert(conversationMessagesTable)
                    .values({
                        conversation_id: conversation.id,
                        message_id: inputMessage.id,
                        sequence_number: 1,
                    });

                // Generate response
                const responseText = `Received: ${options.content}`;

                // Store the response message
                const [responseMessage] = await tx
                    .insert(messagesTable)
                    .values({
                        content: responseText,
                        is_response: true,
                    })
                    .returning({ id: messagesTable.id });

                // Link response message to conversation
                await tx
                    .insert(conversationMessagesTable)
                    .values({
                        conversation_id: conversation.id,
                        message_id: responseMessage.id,
                        sequence_number: 2,
                    });

                return {
                    reply: responseText,
                };
            });
        };
        </handler>
        """

    else:
        raise ValueError(f"Unrecognized prompt: {prompt}")

    return _wrap_anthropic_response(text=text, tool_use=tool_use)

def _anthropic_client(text: str):
    client = MagicMock(spec=AnthropicBedrock)
    client.messages = MagicMock()
    client.messages.create = MagicMock(wraps=_get_pseudo_llm_response)
    return client


def test_end2end():
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = _anthropic_client("some response")
    langfuse_context.configure(enabled=False)
    feature_flags.refine_initial_prompt = True
    

    with tempfile.TemporaryDirectory() as tempdir:
        application = Application(client, compiler)
        my_bot = application.create_bot("Create a bot that does something please")

        interpolator = Interpolator(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        interpolator.bake(my_bot, tempdir)

        assert client.messages.create.call_count == 6
        assert my_bot.refined_description is not None
        assert my_bot.typespec.error_output is None
        assert my_bot.gherkin is not None
        assert my_bot.typescript_schema.error_output is None
        assert my_bot.drizzle.error_output is None

        for x in my_bot.handlers.values():
            assert x.error_output is None

            # change directory to tempdir and run docker compose
            current_dir = os.getcwd()
            os.chdir(tempdir)

            def generate_random_name(prefix, length=8):
                return prefix + ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

            env = os.environ.copy()
            env["APP_CONTAINER_NAME"] = generate_random_name("app_")
            env["POSTGRES_CONTAINER_NAME"] = generate_random_name("db_")
            env["NETWORK_NAME"] = generate_random_name("network_")
            try:
                cmd = ["docker", "compose", "up", "-d"]
                result = subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
                assert result.returncode == 0
                time.sleep(5)
                client = docker.from_env()
                app_container = client.containers.get(env["APP_CONTAINER_NAME"])
                db_container = client.containers.get(env["POSTGRES_CONTAINER_NAME"])

                assert app_container.status == "running", f"App container {env['APP_CONTAINER_NAME']} is not running"
                assert db_container.status == "running", f"Postgres container {env['POSTGRES_CONTAINER_NAME']} is not running"

            finally:
                try:
                    cmd = ["docker", "compose", "down"]
                    subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error downing docker compose: {e}")
                    raise e
                os.chdir(current_dir)
