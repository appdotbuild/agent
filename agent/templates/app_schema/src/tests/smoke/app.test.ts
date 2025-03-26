import { describe, it, expect, beforeAll, afterAll, mock } from 'bun:test';
import { z } from 'zod';
import type { Server } from 'fastify';
import getPort from 'get-port';

// Mock the environment
mock.module('../../env', () => ({
  env: {
    APP_DATABASE_URL: 'mock-db-url',
    APP_PORT: 3001,
    RUN_MODE: 'http-server',
    LOG_RESPONSE: false,
    NODE_ENV: 'test'
  }
}));

// Mock the LLM client
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

mock.module('../../common/llm', () => ({
  client: {
    messages: {
      create: async () => mockClientResponse
    }
  },
  // Pass through the types
  ContentBlock: {},
  TextBlock: {},
  ImageBlock: {},
  ToolUseBlock: {},
  ToolResultBlock: {},
  MessageParam: {}
}));

// Mock the database operations
mock.module('../../common/crud', () => ({
  getHistory: async () => [],
  putMessageBatch: async () => undefined
}));

// Now import the server module after mocking
import { launchHttpServer } from '../../http-server';

describe('Application Smoke Test', () => {
  let app: Server;

  beforeAll(async () => {
    app = await launchHttpServer();
    expect(app).toBeDefined();
  });

  afterAll(async () => {
    if (app) {
      await app.close();
    }
  });

  it('should respond to health check', async () => {
    const response = await app.inject({
      method: 'GET',
      url: '/health'
    });

    expect(response.statusCode).toBe(200);
    expect(JSON.parse(response.body)).toEqual({ status: 'ok' });
  });

  it('should handle chat requests', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/chat',
      payload: {
        user_id: 'test-user',
        message: 'Hello, this is a test message'
      }
    });

    expect(response.statusCode).toBe(200);
    const body = JSON.parse(response.body);
    expect(body).toHaveProperty('reply');
    expect(body.reply).toContain('This is a test response from the mock LLM');
  });

  it('should handle JSON chat requests', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/chat/json',
      payload: {
        user_id: 'test-user',
        message: 'Hello, this is a test message for JSON response'
      }
    });

    expect(response.statusCode).toBe(200);
    const body = JSON.parse(response.body);
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeGreaterThan(0);
  });
  
  it('should handle tool requests', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/handler/greeter',
      payload: {
        name: 'Test User',
        age: 30,
        today: new Date().toISOString()
      }
    });

    expect(response.statusCode).toBe(200);
    const body = JSON.parse(response.body);
    expect(body).toHaveProperty('response');
    expect(body.response).toBe('Test User is 30 years old');
  });
});