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
        // WS-15: the gaps in the hand-rolled list. `react/no-danger` is not
        // available (the plugin is not a dependency, and adding one is not
        // worth it for six selectors), so the list below is the control —
        // and a control with holes is a comment, not a control.
        {
          // `Function("…")` without `new` is the same constructor.
          selector: "CallExpression[callee.name='Function']",
          message: "The Function constructor is forbidden.",
        },
        {
          // `window.eval("…")` is `eval` with extra steps.
          selector:
            "MemberExpression[object.name='window'][property.name='eval']",
          message: "eval is forbidden.",
        },
        {
          selector:
            "MemberExpression[object.name='document'][property.name='write']",
          message:
            "document.write injects markup. Backend text is untrusted data: render it as plain text.",
        },
        {
          selector: "MemberExpression[property.name='createContextualFragment']",
          message:
            "createContextualFragment builds markup. Backend text is untrusted data: render it as plain text.",
        },
        {
          selector: "CallExpression[callee.name='DOMParser']",
          message:
            "DOMParser is only allowed when the result is never inserted as markup.",
        },
        {
          selector: "JSXAttribute[name.name='srcDoc']",
          message:
            "srcDoc is a markup sink. Backend text is untrusted data: render it as plain text.",
        },
        {
          selector: "JSXAttribute[name.name='srcdoc']",
          message:
            "srcdoc is a markup sink. Backend text is untrusted data: render it as plain text.",
        },
        {
          // A string timer is evaluated as code.
          selector:
            "CallExpression[callee.name='setTimeout'][arguments.0.type='Literal']",
          message: "A string timer is evaluated as code. Pass a function.",
        },
        {
          selector:
            "CallExpression[callee.name='setInterval'][arguments.0.type='Literal']",
          message: "A string timer is evaluated as code. Pass a function.",
        },
        {
          // An inline event handler attribute is a code sink.
          selector:
            "CallExpression[callee.object.name='element'][callee.property.name='setAttribute'][arguments.0.value=/^on/i]",
          message:
            "An inline event handler is a code sink. Use React's own event props.",
        },
      ],
    },
  },
])
