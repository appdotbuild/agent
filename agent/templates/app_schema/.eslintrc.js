// flat config with CommonJS syntax for ESLint 9.x
/** @type {import('eslint').Linter.FlatConfig[]} */
module.exports = [
// ignore patterns config
{
    ignores: ["node_modules/**", "dist/**", "build/**"]
},
// typescript files config
{
    files: ["**/*.ts", "**/*.tsx", "src/**/*.ts"],
    // using basic parser options without requiring the @eslint/js package
    languageOptions: {
    parser: require("@typescript-eslint/parser"),
    ecmaVersion: 2022,
    sourceType: "module",
    },
    // using plugins directly
    plugins: {
    "@typescript-eslint": require("@typescript-eslint/eslint-plugin"),
    // custom plugin for renamed imports
    "no-renamed": {
        rules: {
        "no-import-rename": {
            create(context) {
            return {
                ImportSpecifier(node) {
                if (node.imported && node.local &&
                    node.imported.name !== node.local.name) {
                    context.report({
                    node,
                    message: "Renamed imports are not allowed"
                    });
                }
                }
            };
            }
        }
        }
    }
    },
    // providing rules directly
    rules: {
    // typescript rules - added directly
    "@typescript-eslint/no-unused-vars": ["error", {
        "vars": "all",
        "args": "after-used",
        "ignoreRestSiblings": false
    }],
    // rule to prevent renamed imports
    "no-renamed/no-import-rename": "error"
    }
}
];