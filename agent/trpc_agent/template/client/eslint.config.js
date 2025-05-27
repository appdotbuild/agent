import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const noEmptySelectValue = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Disallow empty string values in Select.Item components',
    },
    messages: {
      emptySelectValue: 'Select.Item value prop cannot be an empty string',
    },
  },
  create(context) {
    return {
      JSXAttribute(node) {
        if (
          node.name?.name === 'value' &&
          node.parent?.name?.name === 'Select.Item' &&
          node.value?.type === 'Literal' &&
          node.value.value === ''
        ) {
          context.report({
            node,
            messageId: 'emptySelectValue',
          });
        }
      },
    };
  },
};

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'custom': {
        rules: {
          'no-empty-select-value': noEmptySelectValue,
        },
      },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      'custom/no-empty-select-value': 'error',
    },
  },
  {
    files: ['**/components/ui/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
)
