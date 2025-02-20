import tempfile
import logging

from unittest.mock import MagicMock
from anthropic import AnthropicBedrock
from anthropic.types import Message, TextBlock, Usage, ToolUseBlock
from application import Application, langfuse_context
from compiler.core import Compiler

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

def _get_pseudo_llm_response(*args, **kwargs):
    messages = kwargs["messages"]
    prompt = messages[-1]["content"]
    text = None
    tool_use = None

    if "generate TypeSpec models" in prompt:
        print("\tLLM: generate TypeSpec models")
        text = """
        <reasoning>I am a test lol</reasoning>
        <typespec>
        model Dish {
            name: string;
            ingredients: Ingredient[];
        }

        model Ingredient {
            name: string;
            calories: integer;
        }

        interface DietBot {
            @llm_func(1)
            recordDish(dish: Dish): void;

        }
        </typespec>
        """
    elif "generate TypeScript data types" in prompt:
        print("\tLLM: generate TS data types")
        text = """
        <reasoning>I am a test lol</reasoning>
        <typescript>
        export interface User {
            id: string;
        }

        export interface Message {
            role: 'user' | 'assistant';
            content: string;
        }
        </typescript>
        """
    elif "generate Drizzle schema" in prompt:
        print("\tLLM: generate Drizzle schema")
        text = """
        <reasoning>I am a test lol</reasoning>
        <drizzle>
        import { integer, pgTable, pgEnum, text } from "drizzle-orm/pg-core";

        export const usersTable = pgTable("users", {
          id: text().primaryKey(),
        });

        export const msgRolesEnum = pgEnum("msg_roles", ["user", "assistant"]);

        export const messagesTable = pgTable("messages", {
          id: integer().primaryKey().generatedAlwaysAsIdentity(),
          user_id: text().references(() => usersTable.id),
          role: msgRolesEnum(),
          content: text(),
        });
        </drizzle>"""
    elif "generate prompt for the LLM to classify which function should handle user request" in prompt:
        print("\tLLM: generate prompt for the LLM to classify which function should handle user request")
        tool_use = {
          "user_functions":
              [
                {
                  "name": "logUsersDish",
                  "description": "Log users dish.",
                  "examples": [
                    "I ate a burger.",
                    "I had a salad for lunch.",
                    "Chili con carne"],
                }
              ]
        }

    elif "generate a handler" in prompt:
        print("\tLLM: generate a handler")
        text = """
        <handler>
        import { db } from "../db";
        import { messagesTable } from "../db/schema/application";

        export const handle = async (options: { user_id: string; message: string }): Promise<{ recorded: boolean }> => {
            try {
                // Insert the message into the database with required fields
                await db.insert(messagesTable).values({
                    user_id: options.user_id,
                    content: options.message,
                    role: "user" // Add required role field
                });

                return {
                    recorded: true
                };
            } catch (error) {
                console.error('Error recording message:', error);
                return {
                    recorded: false
                };
            }
        };
        </handler>        """

    else:
        print("Failed processing LLM", messages)
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

    with tempfile.TemporaryDirectory() as tempdir:
        application = Application(client, compiler, "templates", tempdir)
        my_bot = application.create_bot("Create a bot that does something please")

        assert client.messages.create.call_count == 5  # typespec, ts, drizzle, router, handler - no refinement and gherkin by default
        assert my_bot.refined_description is not None
        assert my_bot.typespec.error_output is None
        assert my_bot.gherkin is not None
        assert my_bot.typescript_schema.error_output is None
        assert my_bot.drizzle.error_output is None
        assert my_bot.router.error_output is None
        for x in my_bot.handlers.values():
            assert x.error_output is None
