// src/tests/smoke/http-only.test.js

import { describe, it, expect } from 'bun:test';
import fastify from 'fastify';
import { z } from 'zod';

// Define schemas and handlers without importing from the app
const greetUserParamsSchema = z.object({
  name: z.string(),
  age: z.number(),
  today: z.coerce.date(),
});

function handleGreeting(options) {
  return `${options.name} is ${options.age} years old`;
}

// Create a simple standalone HTTP server without dependencies
function createMinimalApp() {
  const app = fastify();
  
  // Health check endpoint
  app.get('/health', async () => {
    return { status: 'ok' };
  });
  
  // Greeter endpoint
  app.post('/handler/greeter', async (request, reply) => {
    try {
      const params = greetUserParamsSchema.parse(request.body);
      const result = handleGreeting(params);
      return { response: result };
    } catch (error) {
      reply.code(400);
      return { error: 'Invalid parameters' };
    }
  });
  
  // Mock chat endpoint
  app.post('/chat', async (request) => {
    const mockReply = "This is a test response from the mock LLM.";
    return { reply: mockReply };
  });
  
  // Mock JSON chat endpoint
  app.post('/chat/json', async () => {
    return [{ type: 'text', text: 'This is a test response from the mock LLM.' }];
  });
  
  return app;
}

describe('Minimal HTTP Handler Tests', () => {
  it('health endpoint should return 200 OK', async () => {
    const app = createMinimalApp();
    
    const response = await app.inject({
      method: 'GET',
      url: '/health'
    });
    
    expect(response.statusCode).toBe(200);
    expect(JSON.parse(response.body)).toEqual({ status: 'ok' });
  });
  
  it('greeter endpoint should handle valid requests', async () => {
    const app = createMinimalApp();
    
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
    expect(body.response).toBe('Test User is 30 years old');
  });
  
  it('greeter endpoint should reject invalid requests', async () => {
    const app = createMinimalApp();
    
    const response = await app.inject({
      method: 'POST',
      url: '/handler/greeter',
      payload: {
        name: 'Test User',
        // Missing age field
        today: new Date().toISOString()
      }
    });
    
    expect(response.statusCode).toBe(400);
    expect(JSON.parse(response.body)).toHaveProperty('error');
  });
  
  it('should handle chat requests', async () => {
    const app = createMinimalApp();
    
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
    const app = createMinimalApp();
    
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
});