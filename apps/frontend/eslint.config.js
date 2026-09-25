import js from '@eslint/js';
import globals from 'globals';
import pluginVue from 'eslint-plugin-vue';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
  {
    ignores: ['dist/', 'node_modules/', 'coverage/'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
      globals: {
        ...globals.browser,
      },
    },
    rules: {
      // 宽松配置：存量代码暂不强制，后续逐步收紧
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'warn',
      // Vue 模板中使用的 ref 会被该规则误判
      'no-useless-assignment': 'off',
      'no-empty': 'warn',
      'vue/no-unused-vars': 'warn',
      'vue/require-default-prop': 'warn',
      'vue/multi-word-component-names': 'off',
    },
  },
  prettier,
);
