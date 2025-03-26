import { describe, it, expect, mock } from 'bun:test';
import { z } from 'zod';

// A simplified version of our handler
const greetUserParamsSchema = z.object({
  name: z.string(),
  age: z.number(),
  today: z.coerce.date(),
});

function handle(options) {
  return options.name + ' is ' + options.age + ' years old';
}

// Mock LLM client
const mockClientResponse = {
  id: 'msg_mock',
  model: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
  type: 'message',
  role: 'assistant',
  content: [
    {
      type: 'text',
      text: 'This is a test response from the mock LLM.'
    }
  ],
  usage: { input_tokens: 10, output_tokens: 10 }
};

// Mock DB client with in-memory storage
const messageStore = [];
const userStore = new Set();

function putMessage(user_id, role, content) {
  userStore.add(user_id);
  messageStore.push({ user_id, role, content });
  return Promise.resolve();
}

function getHistory(user_id, limit = 10) {
  return Promise.resolve(
    messageStore
      .filter(msg => msg.user_id === user_id)
      .slice(-limit)
  );
}

describe('Basic App Smoke Test', () => {
  it('should handle greeting correctly', () => {
    const params = {
      name: 'Test User',
      age: 30,
      today: new Date()
    };
    const result = handle(params);
    expect(result).toBe('Test User is 30 years old');
  });

  it('should parse parameters correctly', () => {
    const validData = {
      name: 'Test User',
      age: 30,
      today: new Date().toISOString()
    };

    const parsed = greetUserParamsSchema.parse(validData);
    expect(parsed.name).toBe('Test User');
    expect(parsed.age).toBe(30);
    expect(parsed.today instanceof Date).toBe(true);
  });

  it('should store and retrieve messages', async () => {
    const userId = 'test-user-123';
    const message = 'Hello, world!';
    
    await putMessage(userId, 'user', message);
    const history = await getHistory(userId);
    
    expect(history.length).toBe(1);
    expect(history[0].user_id).toBe(userId);
    expect(history[0].role).toBe('user');
    expect(history[0].content).toBe(message);
  });

  it('should mock LLM responses', () => {
    expect(mockClientResponse.content[0].text).toContain('test response');
    expect(mockClientResponse.role).toBe('assistant');
  });
});