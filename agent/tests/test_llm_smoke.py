import unittest
import os
import tempfile
import shutil
from unittest.mock import MagicMock, patch

from application import Application
from compiler.core import Compiler
from core.interpolator import Interpolator
from anthropic.types import Message, TextBlock, Usage

class TestLLMSmoke(unittest.TestCase):
    """Test the Application class with mocked LLM responses"""
    
    def setUp(self):
        """Set up test environment before each test"""
        self.test_dir = tempfile.mkdtemp()
        
        # Sample responses for each stage
        self.typespec_response = """
        <reasoning>
        This bot will store and search notes with tags.
        </reasoning>

        <typespec>
        model Note {
            content: string;
            tags?: string[];
        }

        model CreateNoteResponse {
            success: boolean;
            noteId?: number;
        }

        model SearchOptions {
            query: string;
        }

        model SearchResults {
            notes: Note[];
        }

        interface NotesBot {
            @scenario("User creates a note")
            @llm_func("Create a new note")
            createNote(note: Note): CreateNoteResponse;
            
            @scenario("User searches notes")
            @llm_func("Search for notes")
            searchNotes(options: SearchOptions): SearchResults;
        }
        </typespec>
        """
        
        self.typescript_response = """
        <typescript>
        import { z } from 'zod';

        export const noteSchema = z.object({
          content: z.string(),
          tags: z.array(z.string()).optional(),
        });

        export type Note = z.infer<typeof noteSchema>;
        
        export const createNoteResponseSchema = z.object({
          success: z.boolean(),
          noteId: z.number().optional(),
        });
        
        export type CreateNoteResponse = z.infer<typeof createNoteResponseSchema>;
        
        export const searchOptionsSchema = z.object({
          query: z.string(),
        });
        
        export type SearchOptions = z.infer<typeof searchOptionsSchema>;
        
        export const searchResultsSchema = z.object({
          notes: z.array(noteSchema),
        });
        
        export type SearchResults = z.infer<typeof searchResultsSchema>;
        
        export declare function createNote(note: Note): Promise<CreateNoteResponse>;
        export declare function searchNotes(options: SearchOptions): Promise<SearchResults>;
        </typescript>
        """
        
        self.drizzle_response = """
        <drizzle>
        import { pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";

        export const notesTable = pgTable("notes", {
          id: serial("id").primaryKey(),
          content: text("content").notNull(),
          created_at: timestamp("created_at").defaultNow().notNull()
        });

        export const tagsTable = pgTable("tags", {
          id: serial("id").primaryKey(),
          note_id: serial("note_id").references(() => notesTable.id).notNull(),
          tag: text("tag").notNull()
        });
        </drizzle>
        """
        
        self.handler_response = """
        <handler>
        import { db } from "../db";
        import { notesTable, tagsTable } from "../db/schema/application";
        import { type Note, type CreateNoteResponse } from "../common/schema";

        export const handle = async (note: Note): Promise<CreateNoteResponse> => {
          const [createdNote] = await db.insert(notesTable)
            .values({ content: note.content })
            .returning({ id: notesTable.id });
            
          if (note.tags) {
            await Promise.all(note.tags.map(tag => 
              db.insert(tagsTable).values({
                note_id: createdNote.id,
                tag
              })
            ));
          }
          
          return {
            success: true,
            noteId: createdNote.id
          };
        };
        </handler>
        """
        
        self.search_handler_response = """
        <handler>
        import { db } from "../db";
        import { notesTable, tagsTable } from "../db/schema/application";
        import { type SearchOptions, type SearchResults } from "../common/schema";
        import { eq, like } from "drizzle-orm";

        export const handle = async (options: SearchOptions): Promise<SearchResults> => {
          const results = await db.select({
            id: notesTable.id,
            content: notesTable.content
          })
          .from(notesTable)
          .where(like(notesTable.content, `%${options.query}%`))
          .execute();
          
          const notes = await Promise.all(
            results.map(async note => {
              const tags = await db.select({
                tag: tagsTable.tag
              })
              .from(tagsTable)
              .where(eq(tagsTable.note_id, note.id))
              .execute();
              
              return {
                content: note.content,
                tags: tags.length > 0 ? tags.map(t => t.tag) : undefined
              };
            })
          );
          
          return { notes };
        };
        </handler>
        """
        
        self.handler_test_response = """
        <imports>
        import { expect, it } from "bun:test";
        import { db } from "../../db";
        import { notesTable, tagsTable } from "../../db/schema/application";
        import { eq } from "drizzle-orm";
        import type { Note } from "../../common/schema";
        </imports>

        <test>
        it("should create a note without tags", async () => {
          const input: Note = { content: "Test note" };
          const result = await createNote(input);
          
          expect(result.success).toBe(true);
          expect(result.noteId).toBeDefined();
          
          const notes = await db.select().from(notesTable).where(eq(notesTable.id, result.noteId!)).execute();
          expect(notes).toHaveLength(1);
        });
        </test>

        <test>
        it("should create a note with tags", async () => {
          const input: Note = { content: "Test note", tags: ["important", "test"] };
          const result = await createNote(input);
          
          expect(result.success).toBe(true);
          
          const tags = await db.select().from(tagsTable).where(eq(tagsTable.note_id, result.noteId!)).execute();
          expect(tags).toHaveLength(2);
        });
        </test>
        """
        
        self.search_test_response = """
        <imports>
        import { expect, it } from "bun:test";
        import { db } from "../../db";
        import { notesTable, tagsTable } from "../../db/schema/application";
        import type { SearchOptions } from "../../common/schema";
        </imports>

        <test>
        it("should search notes by content", async () => {
          // Create test data first
          await createNote({ content: "Test note 1" });
          await createNote({ content: "Another note" });
          
          const options: SearchOptions = { query: "Test" };
          const result = await searchNotes(options);
          
          expect(result.notes.length).toBeGreaterThan(0);
          expect(result.notes[0].content).toContain("Test");
        });
        </test>
        """

    def tearDown(self):
        """Clean up after each test"""
        shutil.rmtree(self.test_dir)

    def _wrap_anthropic_response(self, text):
        """Create a mock Anthropic API response"""
        content = [TextBlock(type="text", text=text)]
        
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

    @patch('langfuse.Langfuse')
    def test_build_sample_bot(self, mock_langfuse_class):
        """Test building a sample bot using the Application class with mocked responses"""
        # Mock Anthropic client
        mock_anthropic = MagicMock()
        mock_anthropic.messages = MagicMock()
        mock_anthropic.messages.create.return_value = self._wrap_anthropic_response("Test response")
        
        # Mock Langfuse
        mock_langfuse = MagicMock()
        mock_langfuse.trace.return_value.id = "mock-trace-id"
        mock_langfuse_class.return_value = mock_langfuse
        
        # Mock compiler to avoid actual TypeScript compilation
        mock_compiler = MagicMock(spec=Compiler)
        mock_compiler.compile_typescript.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
        
        # Create application with mocked components
        application = Application(mock_anthropic, mock_compiler)
        
        # Create mock outputs for prepare_bot and update_bot
        from core.datatypes import (ApplicationPrepareOut, TypespecOut, ApplicationOut, 
                                   DrizzleOut, TypescriptOut, HandlerOut, HandlerTestsOut,
                                   CapabilitiesOut, RefineOut, GherkinOut, LLMFunction,
                                   TypescriptFunction)
                                   
        # Mock the prepare_bot method
        prepared_bot = ApplicationPrepareOut(
            typespec=TypespecOut(
                typespec_definitions=self.typespec_response,
                llm_functions=[
                    LLMFunction(name="createNote", description="Create a note", scenario="User creates a note"),
                    LLMFunction(name="searchNotes", description="Search notes", scenario="User searches notes")
                ],
                reasoning="This is a notes bot",
                error_output=None
            ),
            refined_description=RefineOut(
                refined_description="A bot that stores and searches notes",
                error_output=None
            ),
            capabilities=CapabilitiesOut(
                capabilities=[],
                error_output=None
            )
        )
        # Manually set trace_id (might be a property)
        prepared_bot.trace_id = "mock-trace-id"
        
        # Mock the update_bot method
        completed_bot = ApplicationOut(
            typespec=TypespecOut(
                typespec_definitions=self.typespec_response,
                llm_functions=[
                    LLMFunction(name="createNote", description="Create a note", scenario="User creates a note"),
                    LLMFunction(name="searchNotes", description="Search notes", scenario="User searches notes")
                ],
                reasoning="This is a notes bot",
                error_output=None
            ),
            drizzle=DrizzleOut(
                drizzle_schema=self.drizzle_response,
                reasoning="This is a drizzle schema",
                error_output=None
            ),
            typescript_schema=TypescriptOut(
                typescript_schema=self.typescript_response,
                functions=[
                    TypescriptFunction(name="createNote", argument_type="Note", argument_schema="noteSchema", return_type="CreateNoteResponse"),
                    TypescriptFunction(name="searchNotes", argument_type="SearchOptions", argument_schema="searchOptionsSchema", return_type="SearchResults")
                ],
                reasoning="TypeScript types",
                error_output=None
            ),
            handlers={
                "createNote": HandlerOut(
                    handler=self.handler_response,
                    name="createNote",
                    argument_schema="Note",
                    error_output=None
                ),
                "searchNotes": HandlerOut(
                    handler=self.search_handler_response,
                    name="searchNotes",
                    argument_schema="SearchOptions",
                    error_output=None
                )
            },
            handler_tests={
                "createNote": HandlerTestsOut(
                    content=self.handler_test_response,
                    name="createNote",
                    error_output=None
                ),
                "searchNotes": HandlerTestsOut(
                    content=self.search_test_response,
                    name="searchNotes",
                    error_output=None
                )
            },
            capabilities=CapabilitiesOut(
                capabilities=[],
                error_output=None
            ),
            refined_description=RefineOut(
                refined_description="A bot that stores and searches notes",
                error_output=None
            ),
            gherkin=GherkinOut(
                gherkin=None,
                reasoning=None,
                error_output=None
            ),
            trace_id="mock-trace-id"
        )
        
        # Patch the application methods directly
        with patch.object(application, 'prepare_bot', return_value=prepared_bot):
            with patch.object(application, 'update_bot', return_value=completed_bot):
                # Test prepare_bot
                test_prepared_bot = application.prepare_bot(
                    ["Create a bot that stores and searches notes"],
                    langfuse_observation_id="mock-trace-id"
                )
                
                # Verify prepare_bot outputs
                self.assertIsNotNone(test_prepared_bot)
                self.assertIsNotNone(test_prepared_bot.typespec)
                self.assertIn("model Note", test_prepared_bot.typespec.typespec_definitions)
                self.assertIn("createNote", test_prepared_bot.typespec.typespec_definitions)
                self.assertIn("searchNotes", test_prepared_bot.typespec.typespec_definitions)
                
                # Test update_bot
                test_completed_bot = application.update_bot(
                    test_prepared_bot.typespec.typespec_definitions,
                    langfuse_observation_id="mock-trace-id"
                )
                
                # Verify update_bot outputs
                self.assertIsNotNone(test_completed_bot)
                self.assertIsNotNone(test_completed_bot.drizzle)
                self.assertIsNotNone(test_completed_bot.typescript_schema)
                self.assertIsNotNone(test_completed_bot.handlers)
                self.assertIn("createNote", test_completed_bot.handlers)
                self.assertIn("searchNotes", test_completed_bot.handlers)
                
                # Test interpolation by baking the application
                interpolator = Interpolator(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
                interpolator.bake(test_completed_bot, self.test_dir)
                
                # Verify expected files were created
                schema_path = os.path.join(self.test_dir, "app_schema", "src", "common", "schema.ts")
                drizzle_path = os.path.join(self.test_dir, "app_schema", "src", "db", "schema", "application.ts")
                create_handler_path = os.path.join(self.test_dir, "app_schema", "src", "handlers", "createNote.ts")
                search_handler_path = os.path.join(self.test_dir, "app_schema", "src", "handlers", "searchNotes.ts")
                
                self.assertTrue(os.path.exists(schema_path), f"{schema_path} should exist")
                self.assertTrue(os.path.exists(drizzle_path), f"{drizzle_path} should exist")
                self.assertTrue(os.path.exists(create_handler_path), f"{create_handler_path} should exist")
                self.assertTrue(os.path.exists(search_handler_path), f"{search_handler_path} should exist")


if __name__ == "__main__":
    unittest.main()