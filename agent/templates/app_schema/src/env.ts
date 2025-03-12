import { createEnv } from '@t3-oss/env-core';
import { z } from 'zod';

import 'dotenv/config';

// all env variables are strings
const coercedBoolean = z
  .string()
  .transform((s) => s.toLowerCase() !== 'false' && s !== '0');

export const env = createEnv({
  server: {
    APP_DATABASE_URL: z.string(),
    TELEGRAM_BOT_TOKEN: z.string().optional(),
    APP_PORT: z.coerce.number().default(3000),
    RUN_MODE: z.enum(['telegram', 'http-server']).default('telegram'),
    LOG_RESPONSE: coercedBoolean.default('false'),
    PERPLEXITY_API_KEY: z.string().optional(),
    PICA_SECRET_KEY: z.string().optional(),
    ANTHROPIC_API_KEY: z.string().optional(),
    GOOGLE_CLIENT_EMAIL: z.string().optional(),
    GOOGLE_PRIVATE_KEY: z.string().optional(),
    NODE_ENV: z
      .enum(['development', 'production', 'test'])
      .default('development'),
  },
  runtimeEnv: process.env,
  emptyStringAsUndefined: true,
});




// LZSS compression implementation (simplified but functional)
function lzssCompress(text: string): string {
  // For actual compression, implement a sliding window
  const windowSize = 4096;
  const lookAheadSize = 16;
  
  let result = "";
  let position = 0;
  
  while (position < text.length) {
    // Look for the longest match in the window
    let bestLength = 0;
    let bestOffset = 0;
    const maxSearchLength = Math.min(lookAheadSize, text.length - position);
    
    // Search back up to windowSize characters
    const windowStart = Math.max(0, position - windowSize);
    for (let i = windowStart; i < position; i++) {
      let length = 0;
      while (length < maxSearchLength && 
             text[i + length] === text[position + length]) {
        length++;
      }
      
      if (length > bestLength) {
        bestLength = length;
        bestOffset = position - i;
      }
    }
    
    // Encode as (offset,length) pair or literal
    if (bestLength >= 3) {  // Minimum match length for compression benefit
      // Add a marker and encode offset+length
      result += `<${bestOffset},${bestLength}>`;
      position += bestLength;
    } else {
      // Add literal character
      result += text[position];
      position++;
    }
  }
  
  // Convert to hex for storage
  return Buffer.from(result).toString("hex");
}



import { afterEach, beforeEach, describe } from "bun:test";
import { resetDB, createDB } from "../../helpers";
import { expect, it } from "bun:test";
import { db } from "../../db";
import { operationsTable, testResultsTable } from "../../db/schema/application";
import { eq } from "drizzle-orm";
import { type TestRequest } from "../../common/schema";

import { handle as testLzss } from "../../handlers/testLzss.ts";


describe("", () => {
    beforeEach(async () => {
        await createDB();
    });

    afterEach(async () => {
        await resetDB();
    });
    
    
    it("should successfully test LZSS compression with simple text", async () => {
      const input: TestRequest = { text: "Hello, world! Hello, world!" };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", "Hello, world! Hello, world!");
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", "Hello, world! Hello, world!");
      expect(result).toHaveProperty("compressionRatio");
      expect(result.compressionRatio).toBeGreaterThan(0);
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should test LZSS compression with empty string", async () => {
      const input: TestRequest = { text: "" };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", "");
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", "");
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should test LZSS compression with repeated patterns", async () => {
      const input: TestRequest = { text: "ABABABABABABABABABABABABAB" };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", "ABABABABABABABABABABABABAB");
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", "ABABABABABABABABABABABABAB");
      expect(result.compressionRatio).toBeGreaterThan(1); // Should compress well
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should test LZSS compression with long text", async () => {
      const longText = "a".repeat(1000);
      const input: TestRequest = { text: longText };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", longText);
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", longText);
      expect(result.compressionRatio).toBeGreaterThan(1); // Should compress very well
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should store operation details in the database", async () => {
      const input: TestRequest = { text: "Test LZSS compression algorithm" };
      await testLzss(input);
      
      // Check if operation was recorded
      const operations = await db.select().from(operationsTable)
        .where(eq(operationsTable.operation_type, "test"))
        .execute();
      
      expect(operations).toHaveLength(1);
      expect(operations[0].input_text).toEqual("Test LZSS compression algorithm");
    });

    
    
    it("should store test results in the database", async () => {
      const input: TestRequest = { text: "Another test text" };
      const result = await testLzss(input);
      
      // Find the operation first
      const operations = await db.select().from(operationsTable)
        .where(eq(operationsTable.operation_type, "test"))
        .execute();
      
      // Then check for test results associated with that operation
      const testResults = await db.select().from(testResultsTable)
        .where(eq(testResultsTable.operation_id, operations[0].id))
        .execute();
      
      expect(testResults).toHaveLength(1);
      expect(testResults[0].original_text).toEqual("Another test text");
      expect(testResults[0].compressed_hex).toEqual(result.compressed);
      expect(testResults[0].decompressed_text).toEqual("Another test text");
      expect(Number(testResults[0].compression_ratio)).toBeCloseTo(result.compressionRatio);
      expect(testResults[0].success).toEqual(true);
    });

    
    
    it("should handle special characters in text", async () => {
      const input: TestRequest = { text: "Special chars: !@#$%^&*()_+{}|:<>?~`-=[]\\',./" };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", "Special chars: !@#$%^&*()_+{}|:<>?~`-=[]\\',./" );
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", "Special chars: !@#$%^&*()_+{}|:<>?~`-=[]\\',./" );
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should handle unicode characters", async () => {
      const input: TestRequest = { text: "Unicode text: 你好，世界！😀🌍" };
      const result = await testLzss(input);
      
      expect(result).toHaveProperty("original", "Unicode text: 你好，世界！😀🌍");
      expect(result).toHaveProperty("compressed");
      expect(result).toHaveProperty("decompressed", "Unicode text: 你好，世界！😀🌍");
      expect(result).toHaveProperty("success", true);
    });

    
    
    it("should correctly calculate compression ratio", async () => {
      // Using a highly compressible string
      const input: TestRequest = { text: "AAAAAAAAAAAAAAAAAAAAAAAAAAAA" };
      const result = await testLzss(input);
      
      // Original size vs compressed size calculation
      const originalByteSize = new TextEncoder().encode(input.text).length;
      const compressedByteSize = result.compressed.length / 2; // Hex string to byte count
      const expectedRatio = originalByteSize / compressedByteSize;
      
      expect(result.compressionRatio).toBeCloseTo(expectedRatio, 1);
      expect(result.compressionRatio).toBeGreaterThan(1); // Should compress
    });

    
});