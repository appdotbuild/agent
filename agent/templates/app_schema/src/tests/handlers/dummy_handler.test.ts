import { describe, it, expect } from 'bun:test';

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
