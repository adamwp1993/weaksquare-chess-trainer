import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  { ignores: ["dist", "dist-mock", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // ARCHITECTURE §3 decision 14: no browser storage, ever.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Persist through the bridge (set_setting)." },
        { name: "sessionStorage", message: "Persist through the bridge (set_setting)." },
        { name: "indexedDB", message: "Persist through the bridge (set_setting)." },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "localStorage" },
        { object: "window", property: "sessionStorage" },
        { object: "window", property: "indexedDB" },
        { object: "document", property: "cookie" },
      ],
    },
  },
);
