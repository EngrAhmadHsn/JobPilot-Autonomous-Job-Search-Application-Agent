import js from "@eslint/js"
import globals from "globals"
import reactHooks from "eslint-plugin-react-hooks"
import reactRefresh from "eslint-plugin-react-refresh"
import tseslint from "typescript-eslint"
import { defineConfig, globalIgnores } from "eslint/config"

export default defineConfig([
  globalIgnores(["dist", "coverage", "playwright-report", "test-results"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      "react-refresh/only-export-components": "off",
      // WS-13: every string the backend returns is untrusted data — job
      // descriptions, tailored text, confirmation text, insights. The
      // console renders them as plain text and never as markup, and this
      // rule is what keeps that true as the code grows. It is a lint error
      // rather than a convention so that "no HTML injection path" is
      // enforced by the toolchain, not by memory.
      "no-restricted-syntax": [
        "error",
        {
          selector: 'JSXAttribute[name.name="dangerouslySetInnerHTML"]',
          message:
            "Backend text is untrusted data: render it as plain text. dangerouslySetInnerHTML is forbidden.",
        },
        {
          selector: "MemberExpression[property.name='innerHTML']",
          message:
            "Backend text is untrusted data: render it as plain text. innerHTML is forbidden.",
        },
        {
          selector: "MemberExpression[property.name='outerHTML']",
          message:
            "Backend text is untrusted data: render it as plain text. outerHTML is forbidden.",
        },
        {
          selector: "MemberExpression[property.name='insertAdjacentHTML']",
          message:
            "Backend text is untrusted data: render it as plain text. insertAdjacentHTML is forbidden.",
        },
        {
          selector: "CallExpression[callee.name='eval']",
          message: "eval is forbidden.",
        },
        {
          selector: "NewExpression[callee.name='Function']",
          message: "The Function constructor is forbidden.",
        },
      ],
    },
  },
])
