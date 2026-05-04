基于 Node.js 20、Tailwind CSS v3.4.19、Vite v7.2.4

Tailwind CSS 已按 shadcn 主题完成配置

初始化路径：/mnt/agents/output/app

组件（40+）：
  accordion、alert-dialog、alert、aspect-ratio、avatar、badge、breadcrumb、
  button-group、button、calendar、card、carousel、chart、checkbox、collapsible、
  command、context-menu、dialog、drawer、dropdown-menu、empty、field、form、
  hover-card、input-group、input-otp、input、item、kbd、label、menubar、
  navigation-menu、pagination、popover、progress、radio-group、resizable、
  scroll-area、select、separator、sheet、sidebar、skeleton、slider、sonner、
  spinner、switch、table、tabs、textarea、toggle-group、toggle、tooltip

用法：
  import { Button } from '@/components/ui/button'
  import { Card, CardHeader, CardTitle } from '@/components/ui/card'

目录结构：
  src/sections/        页面区块（section）
  src/hooks/           自定义 hook
  src/types/           类型定义
  src/App.css          应用专属样式
  src/App.tsx          根 React 组件
  src/index.css        全局样式
  src/main.tsx         前端渲染入口
  index.html           Webapp HTML 入口
  tailwind.config.js   Tailwind 主题/插件配置
  vite.config.ts       Vite 构建与开发服务器配置
  postcss.config.js    PostCSS 处理工具配置
