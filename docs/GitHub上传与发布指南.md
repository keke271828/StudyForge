# 把 StudyForge 上传到 GitHub：第一次操作指南

本次版本：0.4.5。当前电脑的项目目录是：

```text
C:\Users\Lenovo\Documents\ChatGPT\codex workspace
```

## 先分清要上传的东西

| 你想做什么 | 放在哪里 | 本次文件 |
| --- | --- | --- |
| 保存、继续修改软件的代码 | GitHub 仓库的 Code 页面 | 上面这个项目目录，按 `.gitignore` 排除生成文件 |
| 让自己或别人下载并安装 | 仓库的 Releases 页面 | `dist/StudyForge-Setup-0.4.5.exe` |
| 方便下载当前源码快照 | Releases 附件，可选 | `dist/StudyForge-source-0.4.5.zip` |
| 核对下载文件是否完整 | 与安装包一起放 Releases | `dist/StudyForge-Setup-0.4.5.exe.sha256.txt` |

安装包很大，直接放 Releases；不要把它拖到 Code 页的“Upload files”里。普通 Git 仓库会阻止超过 100 MiB 的文件，Release 单个附件必须小于 2 GiB。当前限制见 [普通文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) 和 [Release 附件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

## 第一步：上传源码（推荐用 GitHub Desktop）

1. 在 [GitHub 官网](https://github.com/) 注册或登录账号。
2. 从 [GitHub Desktop 官网](https://desktop.github.com/) 安装客户端，打开后登录同一个账号。
3. 在客户端菜单选择 **File → Add local repository…**。
4. 点击 **Choose…**，选中本文开头的 `codex workspace` 文件夹，再点 **Add repository**。当前目录已有本地 Git 仓库，不需要重新创建。若你操作的是解压后的源码副本且没有 Git 仓库，则按客户端提示选择 **Create a repository here**。
5. 左侧 **Changes** 是待上传文件。在下方 **Summary** 填写 `StudyForge 0.4.5`，点击 **Commit to master** 或 **Commit to main**，以实际显示的分支名为准。这个操作只是保存到本机 Git 历史。
6. 点击上方 **Publish repository**。仓库名称填 `StudyForge`，描述可填“本地 AI 学习工作台”。
7. 如果主要是自己备份和继续开发，保留 **Keep this code private**。如果你明确要向所有人公开代码，再取消勾选。
8. 点击 **Publish Repository**，等上传完成。用客户端 **Repository → View on GitHub** 打开网页，确认能看到 `package.json`、`studyforge`、`desktop`、`web` 等代码。

GitHub 官方步骤：[添加本地仓库](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop)、[发布现有项目](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop)。

本目录已配置忽略构建产物、`node_modules`、本地模型、导出样例、环境密钥文件及数据库。真正的学习资料、聊天、画像和手机证书保存在用户数据目录，也不在源码压缩包内。准备公开时，仍应浏览一次 Changes，确认没有自己后来另放进去的私人文件；忽略规则不能识别所有可能的个人内容。

本次源码上传清单与检查结果在 `build/github-source-0.4.5-manifest.json`。不要把 `build` 或整个 `dist` 文件夹提交进仓库。

## 第二步：发布安装包

1. 打开刚才的 GitHub 仓库网页。
2. 点击 **Releases → Draft a new release**（没有 Release 时，也可能显示 **Create a new release**）。
3. 在 **Choose a tag** 输入 `v0.4.5`，选择创建新标签；**Target** 选刚才上传源码的分支，通常是 `master` 或 `main`。
4. **Release title** 填 `StudyForge 0.4.5`。
5. 打开本机 `docs/Release-0.4.5.md`，复制里面的发布说明到描述框。
6. 在页面下方附件区加入：
   - `dist/StudyForge-Setup-0.4.5.exe`
   - `dist/StudyForge-Setup-0.4.5.exe.sha256.txt`
   - `dist/StudyForge-source-0.4.5.zip`（可选）
   - `dist/StudyForge-source-0.4.5.zip.sha256.txt`（如果上传源码包，建议一并加入）
7. 等所有附件上传完成，再点 **Publish release**。想先检查可以点 **Save draft**。
8. 发布后，在 **Assets** 下点击安装包名称即可下载。把这一页链接分享出去，别人就能找到安装包。私有仓库只有获授权的人能访问，若要公开下载需要公开仓库或另外的公开发布仓库。

官方说明：[创建 Release 并上传附件](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。GitHub 自动产生的 “Source code (zip)” 是代码，不是 Windows 安装器；需要安装的人应下载 `StudyForge-Setup-0.4.5.exe`。

## 以后如何更新

- **代码变了**：在 GitHub Desktop 填 Summary → Commit → Push origin。
- **有了新安装器**：例如 0.4.6，创建 `v0.4.6` 的新 Release，上传新文件，保留旧版便于回退。
- **软件内自动更新**：目前还没有绑定正式更新源。仅上传 Release 不会自动启用软件内更新；要另行配置可访问的更新地址、版本清单和发布者签名。当前无需为了上传 GitHub 而填写不存在的地址或关闭签名校验。

## 在自己电脑上安装本版

先在 Windows 右下角托盘中右键 StudyForge，选择退出，再双击 `dist/StudyForge-Setup-0.4.5.exe`，安装到原位置。本版安装配置不会主动删除用户数据目录；重要学习数据仍建议自行备份。手机页面由电脑提供，电脑更新后刷新手机网页即可，通常无需重装或重新配对。

源码快照未包含 CUDA DLL、本地检索模型和第三方运行环境。它用于保存代码；从源码运行或重新打包需按 README 准备依赖，不能直接把源码 zip 当安装器。发布时请保留依赖组件自带的许可证；本项目自身的开源许可证尚未由你指定，上传到私有仓库不要求现在选择开源许可证。
