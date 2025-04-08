import { defineConfig } from 'eslint/config';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import unusedImportsPlugin from 'eslint-plugin-unused-imports';

export default defineConfig([
  {
    // ignore patterns config
    ignores: ['node_modules/**', 'dist/**', 'build/**'],
    files: ['**/*.ts', '**/*.tsx', 'src/**/*.ts'],
    // using basic parser options without requiring the @eslint/js package
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: 'module',
    },
    // using plugins directly
    plugins: {
      '@typescript-eslint': tsPlugin,
      'unused-imports': unusedImportsPlugin,
      // custom plugin for renamed imports
      'no-renamed': {
        rules: {
          'no-import-rename': {
            create(context) {
              return {
                ImportSpecifier(node) {
                  if (
                    node.imported &&
                    node.local &&
                    node.imported.name !== node.local.name
                  ) {
                    context.report({
                      node,
                      message: 'Renamed imports are not allowed',
                    });
                  }
                },
              };
            },
          },
        },
      },
    },
    // providing rules directly
    rules: {
      'no-unused-vars': 'off',
      'unused-imports/no-unused-imports': 'error',
      'unused-imports/no-unused-vars': [
        'error',
        {
          vars: 'all',
          varsIgnorePattern: '^_',
          args: 'after-used',
          argsIgnorePattern: '^_',
        },
      ],
      // rule to prevent renamed imports
      'no-renamed/no-import-rename': 'error',
    },
  },
  {
    // custom rule to prevent uuid for user_id
    files: ['**/schema.ts', '**/schema/*.ts', '**/db/**/*.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'Property[key.name=/^user_?id$/i] CallExpression[callee.name="uuid"]',
          message:
            'UUID types are not allowed for user IDs. Use text() instead.',
        },
      ],
    },
  },
]);
