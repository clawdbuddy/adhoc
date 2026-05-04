# React + TypeScript + Vite

本模板提供一个最小可用的 React on Vite 配置，启用了 HMR 与若干 ESLint 规则。

目前 Vite 官方提供两个 React 插件：

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react)：使用 [Babel](https://babeljs.io/)（在 [rolldown-vite](https://vite.dev/guide/rolldown) 下使用 [oxc](https://oxc.rs)）实现 Fast Refresh。
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc)：使用 [SWC](https://swc.rs/) 实现 Fast Refresh。

## React Compiler

模板默认未启用 React Compiler（会影响 dev 与 build 的性能）。如需启用，参考[官方文档](https://react.dev/learn/react-compiler/installation)。

## 拓展 ESLint 配置

如果是开发生产应用，建议把 lint 配置切换为带类型信息的规则：

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // 其它配置...

      // 用以下规则替换 tseslint.configs.recommended
      tseslint.configs.recommendedTypeChecked,
      // 或者使用更严格的规则
      tseslint.configs.strictTypeChecked,
      // 可选：附加风格规则
      tseslint.configs.stylisticTypeChecked,

      // 其它配置...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // 其它选项...
    },
  },
])
```

也可以安装 [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) 与 [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) 启用 React 专用 lint 规则：

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // 其它配置...
      // 启用 React lint 规则
      reactX.configs['recommended-typescript'],
      // 启用 React DOM lint 规则
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // 其它选项...
    },
  },
])
```
