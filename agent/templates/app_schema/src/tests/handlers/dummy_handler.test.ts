interface GreetUsersOutput {
    users: { name: string, age: number }[];
};

const usersToList = (name: string, age: number): GreetUsersOutput => {
    return { users: [{ name, age }] };
}

import { test, expect } from "bun:test";

test('usersToList', () => {
    expect(usersToList('John', 25)).toEqual({ users: [{ name: 'John', age: 25 }] });
});