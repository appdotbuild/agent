import { describe, it, expect, beforeAll, afterAll } from 'bun:test';
import { getUserId } from '../../common/chat';

interface GreetUsersOutput {
  users: { name: string; age: number }[];
}

const usersToList = (name: string, age: number): GreetUsersOutput => {
  return { users: [{ name, age }] };
};

describe('usersToList', () => {
  it('should return a list of users', () => {
    expect(usersToList('John', 25)).toEqual({
      users: [{ name: 'John', age: 25 }],
    });
  });
});

describe('getUserId', () => {
  const originalTestUserId = process.env['TEST_USER_ID'];

  beforeAll(() => {
    // Setup test environment
    process.env['TEST_USER_ID'] = 'test_user_123';
  });

  afterAll(() => {
    // Restore original environment
    if (originalTestUserId) {
      process.env['TEST_USER_ID'] = originalTestUserId;
    } else {
      delete process.env['TEST_USER_ID'];
    }
  });

  it('should get user ID from test environment', () => {
    expect(getUserId()).toBe('test_user_123');
  });

  it('should get user ID from string parameter', () => {
    expect(getUserId('direct_user_id')).toBe('direct_user_id');
  });

  it('should get user ID from Telegram-like context', () => {
    const mockTelegramCtx = {
      from: { id: 987654321 },
      message: { text: 'hello' }
    };
    expect(getUserId(mockTelegramCtx)).toBe('987654321');
  });
});
