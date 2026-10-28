> ## 声明
>
> **一个新手小白用Codex纯 vibe coding 搓出来东西，由于缺乏基本代码素养和工具常识，所以有大量可以优化的东西，有很多地方是没有达到最初的预期的，但本人会在不断学习中改进这个项目，对这个项目感兴趣的大佬们也可以在这个项目基础上再版，有什么问题也欢迎直接指出，我会不定期优化。** 
>
> Bug、卡顿、崩溃、兼容性问题、生成失败、莫名其妙的报错，以及我还没发现的问题，都可能存在。能在一台电脑上跑起来，不代表换一台电脑也能正常工作；有测试和检查，也不等于没有漏洞或不会丢数据。**目前无法对代码质量、稳定性、兼容性和数据安全作出保证。重要资料请自己保留原件并做好备份。**
>
>

# StudyForge 0.0.1

**一个把学习资料、AI 讨论、讲解文档和练习整理到一起的 Windows 本地学习工作台。**

你可以把PDF教材、讲义、图片、音视频或网页链接放进项目让AI通读，选定自己要学的范围，再围绕资料提问、整理笔记、生成讲解和做练习，搭配费曼学习法和AI根据不会的知识点出举一反三的题进行复习。
## 目录

- [这个项目想做什么](#这个项目想做什么)
- [主要功能](#主要功能)
- [安装与使用条件](#安装与使用条件)
- [第一次使用](#第一次使用)
- [把资料真正用起来](#把资料真正用起来)
- [练习、批改与学习记录](#练习批改与学习记录)
- [用手机连接电脑](#用手机连接电脑)
- [数据、隐私与文件权限](#数据隐私与文件权限)
- [实际限制和常见问题](#实际限制和常见问题)
- [从源码运行](#从源码运行)
- [开源许可](#开源许可)
- [反馈问题](#反馈问题)

## 这个项目想做什么

让AI系统性地辅助学习，而非像在网页端提问那样的碎片化学习，构建自己的知识框架，让Agent把知识体系拆成一个个紧密联系的知识点，通过学习这些知识点构建一整个体系。

将正在使用的教材作为讲解背景和参考资料，让AI参考教材的讲解方式和进度来回答问题，避免像网页端一样证明某个定理时使用了用户还没有学到的知识，当然，这项功能的作用远不止于此。

AI会通过判断用户知识的掌握程度来建立用户画像，里面包含了用户尚未完全掌握的知识点和没有完全掌握的原因，并根据这些原因调整回答用户问题的策略，比如：某一知识点因概念混淆而出错，那么就会着重加强对概念的区分和定义的讲解。

搭配费曼学习法等经典的方法来加深对知识的理解，并通过AI出的举一反三的题来巩固。

学习时，经常会同时打开教材、聊天窗口、笔记和作业文件。聊到一半要重新贴资料，生成的讲解散落在文件夹里，过几天也不容易找到当时的问题和上下文。

StudyForge 想把这些事情放在同一个地方：按课程或主题存放材料，在各个对话里保留学习过程，把讨论整理成文件，再通过作答和追问发现自己还没理解的部分。

比较适合拿来尝试的场景包括：

- 学一门课时，围绕讲义或教材逐段提问。
- 阅读一篇文章，梳理概念、论证、证据和条件。
- 对一个知识点大致了解后，再挑重点深入学习。
- 把零散讨论整理成便于保存、打印或继续修改的讲解文件。
- 根据选定资料做练习，回看自己的作答和批改。
- 在电脑上处理任务，再用手机继续阅读、提问和下载成果。

使用过程中仍然需要你判断资料是否可靠、问题是否说清楚、解释是否合理。

## 主要功能

### 项目、资料和独立对话

一个项目可以对应一门课、一本书或一个学习主题。项目内可以建立多个对话，例如在“数学分析”项目下分别讨论“极限”和“连续性”。

同一项目可以共用资料，每个对话分别选择要引用的内容并保留自己的聊天记录。支持项目与对话的改名、排序、固定和管理；删除的项目先进入回收站，可在彻底删除前恢复。

### 多种资料导入与按范围阅读

支持的资料类型包括：

| 类型 | 常见格式或内容 |
| --- | --- |
| 文档与文本 | PDF、DOCX、PPTX、TXT、Markdown、HTML、CSV、JSON、TeX |
| 图片 | PNG、JPEG、WebP 等，可进行文字和画面识别 |
| 音视频 | 常见本地音视频文件；按可用条件处理字幕、语音转录和抽取画面 |
| 网页 | 保存网页链接，再读取能够正常访问的正文 |
| 思维导图与卡片 | XMind、FreeMind、OPML、Anki APKG 等 |
| 编程与计算资料 | 常见源代码、Jupyter Notebook、MATLAB、Mathematica 等可解析文件 |

支持某种格式，表示软件有对应的读取入口，不代表所有复杂排版、扫描件、加密文件或特殊文件都能正确解析。原文件、识别结果和来源位置需要结合起来看。

你可以只解析 PDF 的几页，也可以只使用选中的一段文字。想先熟悉资料时，可以通读并查看阅读笔记；讨论具体问题时，可以回到原文的相应位置。

### AI 导师与不同学习方式

在工作台选择服务、模型和学习模式，围绕当前资料交流。可以针对某一句话、一个公式或一条知识联系继续追问。

| 模式 | 适合怎样的需求 |
| --- | --- |
| 概览 | 先了解主题、主要问题、核心观点和范围 |
| 精学 | 逐步理解概念、推理、构造动机、计算方法和使用条件 |
| 研究 | 围绕问题比较论证、材料、证据与尚不确定的地方 |

也可以调整讲解风格、语言、详细程度和模型支持的推理强度。具体要求直接写在当前对话中，例如“先解释为什么想到这一步”“只使用这些资料”“这次不出题”。

### 讲解文档与其他成果

讨论之后，可以生成独立的讲解文件，并在“成果文档”中查看、下载、改名或管理。

支持 Word、PDF、Markdown、HTML、演示文稿、思维导图、Anki 卡片，以及代码或计算类成果等不同用途的输出。不同输出有各自的适用范围，代码、笔记本和计算文件还需要相应环境才能运行。

文档生成可以选择不同的审查强度。更强的审查通常需要更多模型处理和等待时间，仍然可能漏掉问题。先用一小段资料确认效果，再决定是否处理长篇内容。

### 练习、批改与针对性补讲

可以根据资料生成题单、编程作业或理解检查，完整提交作答后查看解析、批改和补讲。需要时可以复习原题，或继续做同难度、新情境的练习。

软件会尝试结合你的实际作答判断困难；信息不足时，可能先询问你的思路。AI 的批改和归因也可能出错，遇到疑点应回看原题、原作答和依据。

### 全局书库、知识结构与学习路线

全局书库用于保存可以跨项目参考的 PDF 教材，按章节建立阅读记录，并在后续讨论中查找相关内容。

知识结构帮助查看概念与联系；学习路线用于安排想广泛了解、重点精学或独立探究的主题。AI 整理出来的关系仍需要核对，“已整理”表示有了阅读结果，并不表示你已经掌握。

### 学习画像、任务与界面

学习画像汇总知识疑问、作答、自评、困难和教学偏好，可以查看依据、纠正不准确的记录，或移出无关内容。

任务区显示排队、执行、暂停和失败状态。部分任务支持保留已完成步骤后继续；独立任务可以有限并行，但同时运行更多任务不一定更快。

界面可以调整主题、背景、字体和阅读空间，也有专注、放大对话、全屏和通知等入口。

## 安装与使用条件

### 安装版

1. 打开 [Releases 下载页面](https://github.com/keke271828/StudyForge/releases/latest)，下载 Windows 安装器（`.exe`）。
2. 如果同名校验文件一并提供，可以用 SHA-256 检查下载是否完整。
3. 双击安装器并按提示安装，再从桌面或开始菜单打开 StudyForge。
4. 没有看到窗口时，检查 Windows 右下角托盘，点击 StudyForge 图标恢复。

安装包面向 **Windows x64**。其他操作系统的安装和兼容性没有在这里作保证。安装器未做商业代码签名，Windows 可能显示未知发布者，请先确认文件来源。

### 还需要准备什么

- 至少一个你有调用权限的 AI 服务账号或 API 密钥。
- 使用在线模型、网页读取或下载相关资源时，需要可用的网络。
- 扫描页和图片识别需要相应的识别能力或支持图片的模型。
- 本地语音识别、检索等功能可能需要额外模型资源，首次准备会更慢。
- 编程作业的隔离运行需要 Docker 和相应语言环境；查看或讨论代码不等于已经完成实际运行。

安装软件不会自动提供 AI 服务额度。服务方的可用模型、权限和计费情况以你自己的账号为准。

## 第一次使用

### 1. 先连接一种 AI 服务

打开 **设置与联动 → 模型与语音**。第一次先配置一种自己已经有调用权限的服务即可。

| 连接方式 | 基本操作 |
| --- | --- |
| DeepSeek | 填写 API 密钥，保存设置，再点击“检测 DeepSeek 连接” |
| 本机 Codex | 先安装并登录 Codex CLI，再到“运行与更新 → 运行环境”确认可用，在工作台选择 Codex |
| OpenAI 兼容接口 | 在 AI 服务管理中添加服务，填写接口地址、模型调用名和密钥，保存并检测 |
| Gemini API | 添加相应类型的服务，填写密钥与模型信息，保存并检测 |
| Gemini · Google 账号 | 按软件入口完成官方 Gemini CLI 的安装与账号授权，再检测是否可用 |

API 地址是服务提供的调用接口，普通聊天网站的网页地址通常不能直接填进去。模型名称也需要使用服务接受的调用名。

配置完成后，回到工作台选择服务和模型，先发一句不带资料的简单问题，确认能得到回复。短问题都无法回复时，先处理连接问题，再导入大份资料。

### 2. 创建项目与对话

点击左侧 **“＋ 新建学习项目”**，例如命名为“数学分析”。进入项目后，为当前话题建立或选择一个对话。

继续学习时打开原来的项目和对话。新建一个同名项目不会自动找回之前的记录，新对话也不会自动选中上一段对话用过的所有资料。

### 3. 先用一小份资料走通流程

1. 点击 **“＋ 文件”** 或将文件拖入资料区，网址使用“网址”入口。
2. 如果是 PDF，点 **“范围”**，先选择一页；其他文档可选择需要的一段原文。
3. 解析完成后，在当前对话勾选对应的范围资料。
4. 发出一个具体问题，检查导师是否引用了正确内容。
5. 确认效果后，再尝试通读、生成文档或处理更长材料。

这样更容易分清问题出在账号连接、资料解析，还是模型回答本身。

## 把资料真正用起来

### 上传、解析、通读和生成分别做什么

| 动作 | 实际作用 |
| --- | --- |
| 上传 / 保存链接 | 把文件或网址加入项目，先保存下来 |
| 解析 | 从指定范围提取可供后续使用的文字、图片或转录等内容 |
| 勾选 / 引用 | 告诉当前对话，这次需要使用哪些资料 |
| 通读 | 让 AI 对选定范围整理阅读笔记和知识线索 |
| 发送 | 在聊天区得到导师回复 |
| 生成讲解 | 制作可阅读、下载和保存的成果文件 |

只上传文件，导师不会自动通读整本书。取消勾选只改变本次引用，不会删除文件；想读一页时，也要检查有没有同时勾选已经全文解析的整本书。

PDF 页码从文件的第 1 页开始计算，可能与纸质书印刷页码不同。范围如 `3-5,8` 表示文件第 3、4、5、8 页。识别出的公式、表格和画面内容，尤其需要对照原页检查。

### 怎样提问更有帮助

尽量说清楚：看的是哪部分、已经理解到哪里、具体在哪一步接不上。下面的写法可以直接修改后使用：

> 请只根据我选中的资料讲解。先说明这个概念在解决什么问题，再解释关键推理，尤其是为什么想到这一步。给一个小例子，把适用条件说清楚。这次只讲解，不出题。

> 我能跟着算出结果，但不理解这里为什么要引入这个辅助量。请从这一步的目标讲起，接回原来的证明。

> 请对照这段原文检查你的说法，区分原文明确写了什么、你推导了什么，以及目前无法确认的部分。

也可以使用回答旁的“针对原句追问”，选中一句话或一个公式，再补上自己的问题。选中原句只是在准备引用，核对草稿后点击发送才会请导师回答。

### 生成并管理成果

1. 选择资料，在当前对话写明这次的讲解要求。
2. 展开讲解与生成选项，选择内容、格式和审查方式。
3. 只需要讲解时，取消“同步生成举一反三习题”。
4. 点击“生成讲解”，到 **“成果文档”** 查看进度。
5. 完成后阅读或下载。成果也会出现在本项目资料快选中，可勾选后继续讨论。

满意的导师回答也可以通过回答旁的入口保存为成果。

“暂停”用于保留进度后继续；“取消”用于停止本次任务，两者含义不同。有些阶段需要等当前请求结束才会暂停。失败时先看错误详情；出现“重试未完成步骤”时，可接续原任务，不必反复新建相同任务。

### 整本教材可以放入全局书库

打开 **“全局书库”**，放入 PDF 教材，识别或修正目录，选择章节并核对页码，再安排阅读。

“优先开始”会进入任务队列；“空闲时再读”会先让聊天和文档任务使用 AI。教材章节依赖较强时，可以按顺序阅读。

书库可以跟随工作台模型，也可以在“阅读模型”中另作选择。已启动的任务保留启动时的设置。后续在工作台引用章节或检索阅读结果时，重要结论仍要回查原页。

## 练习、批改与学习记录

在 **“练习与作业”** 中生成或打开题单，完成后提交；也可以使用工作台的 **“提交作业”** 入口。完整提交后，再查看解析和批改。

- 有争议的评分，结合原题与原作答复核。
- 错因不明确时，按提示说明自己的思路，再继续补讲。
- 想检查是否会独立运用，可以按需发起理解检查或新情境练习。
- 编程任务要区分模型点评、静态检查与实际运行结果，未运行的代码不能算作运行通过。
- 作业中途恢复时，优先使用原记录中的继续或重试入口，避免把另一份题单的成绩混进来。

**学习画像是辅助记录，不是对能力的定论。** 你可以查看来源和时间，纠正不准确的判断，调整自评或移出无关记忆。读过、听懂、做对一题和长期独立掌握是不同的事情。

## 用手机连接电脑

手机使用浏览器访问电脑提供的页面，任务仍由电脑运行。目前软件内的连接说明以安卓操作为主。

1. 电脑顶部点击 **“连接手机”**，启用连接，使用本次显示的地址或二维码。
2. 按窗口提示在手机上安装并信任电脑提供的 CA 证书，再打开 HTTPS 页面。
3. 输入配对码，在电脑上批准该设备。
4. 配对完成后，选择项目和对话，即可聊天、上传资料、查看任务和下载成果。

第一次可以先让电脑和手机使用同一 Wi-Fi。跨网络访问可按软件提示配置 Tailscale，让两端加入同一个私人网络。

电脑需要保持开机，连接服务也需要开启。证书解决 HTTPS 信任问题，不能解决错误地址、网络隔离或电脑睡眠。手机关闭页面后，电脑已启动的任务可以继续；重新打开后再查看结果。

## 数据、隐私与文件权限

### 本机保存与在线处理

资料副本、聊天记录和成果主要保存在电脑本机，默认数据目录为：

```text
%LOCALAPPDATA%\StudyForge
```

如果自定义过数据目录，请以实际配置为准。

调用在线 AI 时，相关提问、所选资料片段和必要上下文会发送给你选择的服务。启用后台学习记忆整理后，相关学习片段也可能提交给当时选择的模型处理。“数据保存在本机”不代表全部处理都能离线完成，也不代表资料不会发送给外部模型。

在软件内保存的 API 密钥使用系统凭据管理机制。第三方服务如何处理已发送内容，需要你了解并接受该服务自身的规则。

### 备份

保留重要资料原件，并定期导出需要的成果。备份软件数据时，先从托盘完全退出 StudyForge，再复制实际数据目录；只复制安装目录不能替代学习数据备份。

账号凭据不一定包含在目录备份里，换电脑后可能需要重新登录或填写密钥。请不要把这个试验性软件作为重要资料的唯一存放位置。

### AI 文件操作权限

普通提问和引用资料不需要给 AI 开放整台电脑。

- **只读**：在授权范围读取，不修改文件。
- **需要审批**：需要批准的操作先显示请求，再由你决定。
- **完全访问**：在授权范围内按工具规则执行修改，需要你自行判断可接受的范围。

联网查询、网页视频读取和图片生成还有相应的工具设置，勾选能力不会自动提供账号、密钥或访问权限。

软件也提供 VS Code Codex、DeepSeek Harness 等外部工作台的 MCP 联动入口，可在“设置与联动”中按说明配置。它们属于可选功能，不影响先在本软件中走通普通学习流程。

## 实际限制和常见问题

### 先接受这些限制

- **模型可能讲错、漏条件、误解问题，审查也可能漏检。** 有来源位置不等于每句话都已经被证实。
- **扫描件、公式、表格、口音和视频画面可能识别错误。** 视频处理依据可获得的字幕、转录和抽取画面，不能保证逐帧理解完整视频。
- **长材料、语音识别、文档生成和多轮核查会耗时。** 速度受到硬件、网络、模型服务、资料长度和并行任务数影响。
- **不同服务并不具备完全相同的能力。** 能正常聊天，不等于支持图片、工具或相同的推理选项。
- **成果格式支持不代表已在所有目标软件和设备上验证。** 下载后的代码、笔记本、导图或演示文稿需要自行打开和检查。
- **项目本身也有成熟度限制。** 某些问题需要保留现场排查，反复点击生成、重试或重新安装不一定有帮助。

### 按现象排查

| 现象 | 先检查什么 |
| --- | --- |
| 没有窗口 | 看 Windows 托盘中是否已有 StudyForge，点击图标恢复 |
| AI 不回复或连接超时 | 检测服务连接，核对密钥、模型调用名、额度和网络；先试不带资料的短问题 |
| 提示 429 / 请求过多 | 减少并行任务，按服务提示等待，避免连续立即重试 |
| 上传后导师仍说没有资料 | 检查是否已解析，并在当前项目、当前对话勾选了相应范围 |
| 网页或视频读不到 | 确认有权访问、页面验证已完成；可尝试电脑端浏览器读取，或提供本地文件与字幕 |
| 生成慢或内存占用高 | 看任务处于哪一步，先处理小范围，减少并行与不需要的附加任务 |
| 任务失败但进度到了 100% | 以任务最终状态和实际成果为准，展开错误详情，不把进度条当作成功交付 |
| 找不到旧聊天或成果 | 回原项目、原对话，加载更早消息，检查成果项目筛选与回收站 |
| 手机一直加载 | 确认电脑和连接服务运行、地址正确；跨网络时检查两端 Tailscale 状态 |

软件内可以按 **F1** 或打开操作指南，查看更细的配置和处理说明。

### 检查软件更新

在“设置与联动 → 运行与更新 → 软件更新”点击“立即检查”，可查看官方 GitHub 最新正式版本及发布说明。高级更新地址留空即可；源码版也能使用。可以保存检查间隔，并自行选择是否在发现较新版本后自动下载安装包。下载支持进度显示、取消、失败重试和完整性校验；完成后打开安装包所在文件夹，先从托盘完全退出软件，再手动运行安装器。当前未启用自动重启安装。

## 从源码运行

只想使用软件时，可以直接下载安装器。运行或修改源码时，需要 Python 3.12 或更新版本，以及 Node.js 22 或更新版本。

1. 下载或克隆本仓库，进入项目根目录。
2. 运行 `setup_studyforge.cmd`，安装 Python 与 Node 依赖。
3. 安装完成后，运行 `start_studyforge_source.cmd` 明确打开源码版。

`start_studyforge.cmd` 会优先打开已有的 `dist/win-unpacked/StudyForge.exe`。需要明确运行当前源码时，安装依赖后在项目根目录执行：

```bash
npm start
```

需要自行构建 Windows x64 安装包时，先完成上面的依赖安装，再执行：

```powershell
python -m pip install pyinstaller
npm run build:win
node scripts/check_windows_release.cjs
```

安装包输出到 `dist/`。可选 CUDA 运行组件不属于项目自有源码；未准备该组件时可构建使用 CPU 语音识别的安装包，详细组件说明见 `THIRD_PARTY_NOTICES.md`。

目录大致分工：

| 目录 | 内容 |
| --- | --- |
| `desktop/` | Electron 桌面入口与窗口、运行环境等功能 |
| `studyforge/` | Python 后端、资料处理、AI 调用与成果生成 |
| `web/` | 工作台、手机页面与软件内操作指南 |
| `scripts/` | 构建和辅助脚本 |
| `integrations/` | 可选的 Codex 与 DSH 连接脚本和配置模板 |
| `tests/` | 现有测试用例 |
| `docs/` | 专项说明与开发记录，按需查阅 |

## 开源许可

Copyright (C) 2026 keke271828。

StudyForge 的自有代码与文档完整采用 [GNU Affero General Public License v3.0](LICENSE)（`AGPL-3.0-only`）开源，源码和构建脚本均在本仓库中公开。你可以使用、学习、修改和分发，也可以商用；分发时需遵守许可证并提供相应源码。如果你修改软件并让用户通过网络与它交互，需要按许可证向这些用户提供该修改版本的相应源码。项目不另加“仅供学习”或“禁止商用”等限制，完整条款见 `LICENSE`。

第三方库、字体和运行时保留各自的许可，AI 服务、模型与用户导入的学习资料也遵循各自的条款；项目许可证不会替代这些授权。详见 [第三方组件与许可](THIRD_PARTY_NOTICES.md)。

## 反馈问题

可以在 [GitHub Issues](https://github.com/keke271828/StudyForge/issues) 中反馈。比起只写“不能用”，下面的信息更有助于定位：

```text
我想完成什么：
用了安装版还是源码版：
Windows 版本：
AI 服务与模型：
资料类型、大小和所选范围：
我依次点击或输入了什么：
预期结果：
实际现象或完整错误：
是否每次都能复现：
截图或最小复现材料：
```

提交前请删掉 API 密钥、令牌、账号凭据和私人资料。能够用一页脱敏文档或一个小例子复现的问题，通常更容易排查。

欢迎直接指出功能、交互、文档和讲解中的问题。这个项目还有很多不足，具体的反馈将帮助这个项目走得越来越远，在此谢谢各位。

---

> ## Before you use it
>
> **This is something a complete beginner put together with Codex through pure vibe coding. I lack basic programming knowledge and familiarity with development tools, so there is a lot that could be improved, and many parts have not turned out the way I originally intended. I will keep learning and improving the project. Developers who are interested are welcome to build their own versions on top of it. Please point out any problems directly; I will make improvements from time to time.**
>
> Bugs, slowdowns, crashes, compatibility issues, failed generation, inexplicable error messages, and problems I have not discovered yet are all possible. Working on one computer does not mean it will work on another. Having tests and checks does not rule out vulnerabilities or data loss. **I cannot guarantee code quality, stability, compatibility, or data safety. Keep the original copies of important materials and make your own backups.**

# StudyForge 0.0.1

**A local learning workspace for Windows that brings study materials, AI discussions, explanatory documents, and practice together.**

Add textbooks, lecture notes, images, audio, video, or web pages to a project, choose the parts you want to study, and use them to ask questions, organize notes, generate explanations, and practice. Materials and learning records are stored on your computer. AI capabilities come from the model services you configure yourself.

## Contents

- [What this project is trying to do](#what-this-project-is-trying-to-do)
- [Main features](#main-features)
- [Installation and requirements](#installation-and-requirements)
- [Getting started](#getting-started)
- [Working with your materials](#working-with-your-materials)
- [Practice, feedback, and learning records](#practice-feedback-and-learning-records)
- [Connecting your phone](#connecting-your-phone)
- [Data, privacy, and file access](#data-privacy-and-file-access)
- [Practical limitations and common problems](#practical-limitations-and-common-problems)
- [Running from source](#running-from-source)
- [Open-source license](#open-source-license)
- [Reporting problems](#reporting-problems)

## What this project is trying to do

Studying often means keeping a textbook, a chat window, notes, and assignment files open at the same time. You may need to paste the same material into a conversation again, generated explanations end up scattered across folders, and a few days later it can be hard to find the original question and context.

StudyForge tries to bring these activities into one place: organize materials by course or topic, keep the learning process in separate conversations, turn discussions into documents, and use your answers and follow-up questions to identify what you have not yet understood.

Some situations you might try it in:

- Work through lecture notes or a textbook one section at a time.
- Read an article and untangle its concepts, arguments, evidence, and conditions.
- Get an overview of a topic, then choose particular parts to study in depth.
- Turn scattered discussions into explanations you can save, print, or edit.
- Practice using selected materials, then review your answers and feedback.
- Run tasks on your computer and continue reading, asking questions, or downloading results on your phone.

You still need to judge whether the materials are reliable, whether your question is clear, and whether an explanation makes sense. Producing a large collection of documents does not mean you have understood them.

## Main features

### Projects, materials, and separate conversations

A project can represent a course, a book, or a study topic. Each project can contain several conversations: for example, separate discussions about limits and continuity within a mathematical analysis project.

Conversations in the same project can use shared materials, while each conversation keeps its own selected references and chat history. Projects and conversations can be renamed, sorted, pinned, and managed. Deleted projects first go to the recycle bin and can be restored before permanent deletion.

### Multiple material types and reading selected ranges

Supported material types include:

| Type | Common formats or content |
| --- | --- |
| Documents and text | PDF, DOCX, PPTX, TXT, Markdown, HTML, CSV, JSON, TeX |
| Images | PNG, JPEG, WebP, and others, with text and image recognition |
| Audio and video | Common local media files; subtitles, speech transcription, and sampled frames are processed where available |
| Web pages | Save a link, then read the body of a page that can be accessed |
| Mind maps and flashcards | XMind, FreeMind, OPML, Anki APKG, and others |
| Programming and computational materials | Common source code, Jupyter Notebook, MATLAB, Mathematica, and other readable files |

Supporting a format means there is an input path for it. It does not guarantee correct parsing of every complex layout, scanned page, encrypted file, or unusual document. Compare the original file, extracted content, and source locations.

You can parse only a few PDF pages or use a selected passage. To get familiar with material first, run a reading task and inspect its notes. When discussing a specific issue, return to the relevant part of the original.

### An AI tutor and different approaches to learning

Choose a service, model, and learning mode in the workspace, then discuss the current materials. You can follow up on a particular sentence, formula, or connection between concepts.

| Mode | What it is for |
| --- | --- |
| Overview | Understand a topic, its main questions, core ideas, and scope |
| In-depth study | Work through concepts, reasoning, why a method was chosen, calculations, and conditions of use |
| Research | Compare arguments, materials, evidence, and unresolved questions |

You can also adjust explanation style, language, detail, and the reasoning level supported by the model. State specific requirements in the current conversation, such as “explain why this step was chosen,” “use only these materials,” or “do not include exercises this time.”

### Explanatory documents and other outputs

After a discussion, generate a separate explanatory document and view, download, rename, or manage it in **成果文档** (Outputs).

Outputs cover Word, PDF, Markdown, HTML, presentations, mind maps, Anki flashcards, code, and computational files. Each format has its own uses. Code, notebooks, and computational files still need the appropriate environment to run.

Document generation offers different review levels. More extensive review usually takes additional model processing and waiting time, and it can still miss mistakes. Check the results with a short passage before processing a long document.

### Practice, feedback, and targeted explanations

Generate problem sets, programming assignments, or understanding checks from your materials. After submitting a complete set of answers, review the solutions, feedback, and follow-up explanations. You can revisit the original problems or try exercises at the same difficulty or in a new context.

The software tries to identify difficulties using your actual answers. If there is not enough information, it may ask how you approached a problem first. AI grading and its explanations of your mistakes can also be wrong; revisit the original question, your answer, and the supporting material when in doubt.

### A shared library, knowledge structures, and learning plans

The shared library stores PDF textbooks that can be referenced across projects. Read selected chapters, keep reading records, and find relevant content in later discussions.

Knowledge structures help you inspect concepts and their connections. Learning plans let you organize topics for broad exploration, in-depth study, or independent inquiry. AI-generated connections still need checking. “Organized” means reading results exist, not that you have mastered the content.

### Learning profiles, tasks, and interface settings

The learning profile brings together subject questions, answers, self-assessments, difficulties, and teaching preferences. You can inspect the evidence, correct inaccurate records, and remove unrelated content.

The task area shows queued, running, paused, and failed tasks. Some tasks can continue from completed steps. Independent tasks can run with limited concurrency, but running more tasks at once does not necessarily make them faster.

You can adjust the theme, background, fonts, and reading area. Focus mode, an expanded conversation view, full screen, and notifications are also available.

## Installation and requirements

### Installer

1. Open the [Releases download page](https://github.com/keke271828/StudyForge/releases/latest) and download the Windows installer (`.exe`).
2. If a matching checksum file is provided, use SHA-256 to check the download's integrity.
3. Run the installer and follow its instructions, then open StudyForge from the desktop or Start menu.
4. If no window appears, check the Windows system tray and click the StudyForge icon to restore it.

The installer targets **Windows x64**. Installation and compatibility on other operating systems are not guaranteed here. The installer has no commercial code-signing certificate, so Windows may show an unknown-publisher warning. Check where the file came from before running it.

### What else you need

- At least one AI service account or API key that you are authorized to use.
- A working network connection for online models, web access, and related downloads.
- Suitable recognition capabilities or an image-capable model for scanned pages and images.
- Additional model resources may be needed for local speech recognition, retrieval, and similar features. Initial setup can take longer.
- Isolated execution of programming assignments needs Docker and the appropriate language environment. Viewing or discussing code does not mean it has actually been run.

Installing the app does not provide AI service credits. Available models, permissions, and pricing depend on your own service account.

## Getting started

### 1. Connect one AI service first

Open **设置与联动 → 模型与语音** (Settings and integrations → Models and voice). Start with one service you already have permission to use.

| Connection | Basic setup |
| --- | --- |
| DeepSeek | Enter the API key, save the settings, then click “检测 DeepSeek 连接” (Test DeepSeek connection) |
| Local Codex | Install and sign in to Codex CLI first, check availability under “运行与更新 → 运行环境” (Runtime and updates → Runtime environment), then choose Codex in the workspace |
| OpenAI-compatible API | Add a service in AI service management, enter the endpoint, model identifier, and key, then save and test it |
| Gemini API | Add the corresponding service type, enter the key and model details, then save and test it |
| Gemini · Google account | Follow the app's setup flow to install the official Gemini CLI and authorize your account, then test availability |

An API endpoint is the service's calling interface. The URL of an ordinary chat website usually cannot be used in its place. The model name must also be an identifier accepted by that service.

After setup, return to the workspace, select the service and model, and send a simple question without any materials attached. If even that fails, fix the connection before importing large files.

### 2. Create a project and conversation

Click **“＋ 新建学习项目”** (New learning project) in the left sidebar. For example, name it “Mathematical Analysis,” then create or select a conversation for the current topic.

Return to the original project and conversation to continue studying. Creating a new project with the same name does not recover previous records, and a new conversation does not automatically select everything referenced in the previous one.

### 3. Try the full workflow with a small sample

1. Click **“＋ 文件”** (Add file) or drag a file into the materials area. Use the URL input for a web link.
2. For a PDF, click **“范围”** (Range) and start with one page. For other documents, choose a passage you need.
3. After parsing, select that range's material in the current conversation.
4. Ask a specific question and check that the tutor is using the right content.
5. Once that works, try reading tasks, document generation, or longer materials.

This makes it easier to distinguish account and connection problems from parsing problems or issues with the model's answer.

## Working with your materials

### Uploading, parsing, reading, and generating are different actions

| Action | What it does |
| --- | --- |
| Upload / save a link | Add a file or URL to the project and store it |
| Parse | Extract text, images, transcriptions, or other usable content from the selected range |
| Select / reference | Tell the current conversation which materials to use |
| Read through | Ask AI to organize reading notes and knowledge cues from the selected range |
| Send | Receive a tutor response in the conversation |
| Generate an explanation | Create an output file you can read, download, and keep |

Uploading a file does not automatically make the tutor read the entire book. Deselecting a file changes the current references without deleting it. If you want to study one page, also check that you have not selected a copy of the whole book that was previously parsed in full.

PDF page numbers count from the first page of the file and may differ from printed page numbers. A range such as `3-5,8` means file pages 3, 4, 5, and 8. Recognized formulas, tables, and image content particularly need comparison with the original page.

### Asking more useful questions

Try to explain which passage you mean, what you already understand, and the exact step where you lose the thread. Adapt these examples to your own question:

> Use only my selected materials. First explain what problem this concept addresses, then walk through the key reasoning, especially why this step was chosen. Give a small example and state the conditions under which it applies. Explain only; do not include exercises this time.

> I can follow the calculation, but I do not understand why this auxiliary quantity is introduced. Start with what this step is trying to achieve, then connect it back to the original proof.

> Check your explanation against this passage. Separate what the source explicitly says, what you have derived, and what cannot currently be confirmed.

You can also use **“针对原句追问”** (Ask about a specific passage) beside a response, select a sentence or formula, and add your question. Selecting a passage prepares a reference; the tutor is called only after you check the draft and send it.

### Generating and managing outputs

1. Select the materials and state the requirements for this explanation in the current conversation.
2. Expand the explanation and generation options, then choose the content, format, and review level.
3. If you only want an explanation, turn off **“同步生成举一反三习题”** (Generate additional practice exercises).
4. Click **“生成讲解”** (Generate explanation) and check progress in **“成果文档”** (Outputs).
5. Read or download the completed result. It also appears in the project's quick material selection, where you can select it for further discussion.

A tutor response you want to keep can also be saved as an output using the controls beside it.

Pausing keeps progress for later continuation; canceling stops the current task. Some stages must finish the current request before they can pause. When a task fails, read the error details first. If **“重试未完成步骤”** (Retry unfinished steps) is available, continue the original task rather than repeatedly creating the same task again.

### Using the shared library for textbooks

Open **“全局书库”** (Shared library), add a PDF textbook, identify or correct its table of contents, choose chapters and check page ranges, then schedule reading.

**“优先开始”** (Start with priority) puts the work into the queue. **“空闲时再读”** (Read when idle) gives chat and document tasks priority. If chapters depend heavily on earlier ones, read them in sequence.

The library can follow the workspace model or use a separate choice under **“阅读模型”** (Reading model). Tasks already started retain their original settings. When referencing chapters or searching reading results later, return to the original pages for important conclusions.

## Practice, feedback, and learning records

Generate or open a problem set in **“练习与作业”** (Practice and assignments), complete it, and submit your answers. You can also use **“提交作业”** (Submit assignment) in the workspace. Review the solutions and feedback after submitting the complete assignment.

- Recheck disputed scores against the original question and your submitted answer.
- If the reason for a mistake is unclear, explain your approach when prompted, then continue the follow-up explanation.
- To check whether you can apply something independently, start an understanding check or practice in a new context when needed.
- Distinguish model commentary, static checks, and actual execution in programming tasks. Code that has not been run has not passed a runtime test.
- When recovering an assignment task, use the continue or retry controls in its original record so results from a different assignment are not mixed in.

**The learning profile is a supporting record, not a final verdict on your ability.** You can inspect sources and dates, correct inaccurate judgments, adjust self-assessments, and remove unrelated memories. Reading something, understanding an explanation, answering one question correctly, and retaining independent mastery over time are different things.

## Connecting your phone

Your phone uses a browser to access a page served by your computer. The computer still runs the tasks. The app's connection instructions currently focus on Android.

1. Click **“连接手机”** (Connect phone) at the top of the desktop app, enable the connection, and use the current address or QR code.
2. Follow the dialog's instructions to install and trust the computer's CA certificate on your phone, then open the HTTPS page.
3. Enter the pairing code and approve the device on your computer.
4. Select a project and conversation to chat, upload materials, check tasks, or download outputs.

For the first attempt, put the computer and phone on the same Wi-Fi network. For access across networks, follow the app's Tailscale instructions and connect both devices to the same private network.

The computer must stay on and its connection service must remain enabled. The certificate handles HTTPS trust; it cannot fix a wrong address, network isolation, or a sleeping computer. Tasks already started on the computer can continue after the phone page closes. Open the page again to check the results.

## Data, privacy, and file access

### Local storage and online processing

Material copies, conversations, and outputs are mainly stored on your computer. The default data directory is:

```text
%LOCALAPPDATA%\StudyForge
```

If you have configured a different data directory, use that location instead.

When calling an online AI service, relevant questions, selected material excerpts, and necessary context are sent to the service you choose. If background learning-memory organization is enabled, relevant learning excerpts may also be sent to the model selected for those records. Local storage does not mean all processing is offline or that content will never be sent to an external model.

API keys saved through the app use the system credential-management mechanism. You need to understand and accept the chosen service's own rules for handling content sent to it.

### Backups

Keep original copies of important materials and export the outputs you need. Before backing up the app's data, fully exit StudyForge from the system tray, then copy the actual data directory. Copying the installation folder alone does not back up your learning data.

Account credentials may not be included in a directory backup, so you may need to sign in again or re-enter keys after moving to another computer. Do not use this experimental app as the only storage location for important materials.

### AI access to files

Ordinary questions and references to selected materials do not require giving AI access to the entire computer.

- **“只读” — Read-only:** read within the authorized scope without changing files.
- **“需要审批” — Approval required:** operations that require approval are presented for you to decide.
- **“完全访问” — Full access:** allow changes within the authorized scope under the tool rules; decide what scope you are comfortable granting.

Web searches, web-video access, and image generation have their own tool settings. Enabling a capability does not provide an account, key, or access permission.

Optional MCP integrations for external workspaces, including VS Code Codex and DeepSeek Harness, are available under **“设置与联动”** (Settings and integrations). They are not required to complete the ordinary learning workflow inside this app.

## Practical limitations and common problems

### Keep these limitations in mind

- **A model can give a wrong explanation, omit conditions, or misunderstand a question, and review can miss those mistakes.** A source location does not mean every statement has been verified.
- **Scans, formulas, tables, accents, and video frames can be recognized incorrectly.** Video processing uses available subtitles, transcriptions, and sampled frames; it does not guarantee frame-by-frame understanding of an entire video.
- **Long materials, speech recognition, document generation, and multiple reviews take time.** Speed depends on hardware, network conditions, the model service, material length, and concurrent tasks.
- **Different services do not have identical capabilities.** Working chat does not imply support for images, tools, or the same reasoning options.
- **Format support does not mean outputs have been verified in every target application or on every device.** Open and check downloaded code, notebooks, mind maps, or presentations yourself.
- **The project itself has maturity limitations.** Some problems need investigation while their details are still available. Repeatedly generating, retrying, or reinstalling may not help.

### Troubleshooting by symptom

| Symptom | What to check first |
| --- | --- |
| No window appears | Look for StudyForge in the Windows system tray and click its icon |
| AI does not reply or the connection times out | Test the service connection, check the key, model identifier, quota, and network; try a short question without materials |
| 429 / too many requests | Reduce concurrent tasks and wait as instructed by the service rather than retrying immediately |
| The tutor says there are no materials after upload | Check that the material has been parsed and its range selected in the current project and conversation |
| A web page or video cannot be read | Confirm you have access and have completed any page verification; try desktop browser reading or supply a local file and subtitles |
| Generation is slow or memory usage is high | Check the current stage, try a smaller range, and reduce concurrency or unnecessary extra tasks |
| A task fails even though progress reached 100% | Use the final task status and actual output as the result; read the error details rather than treating the progress bar as successful delivery |
| Old conversations or outputs seem missing | Return to the original project and conversation, load older messages, and check project filters and the recycle bin |
| The phone page keeps loading | Confirm the computer and connection service are running and the address is correct; check Tailscale on both devices for access across networks |

Press **F1** or open the in-app guide for more detailed setup and troubleshooting instructions.

### Checking for updates

Open 设置与联动 → 运行与更新 → 软件更新 (Settings and integrations → Runtime and updates → Software updates) and choose 立即检查 (Check now). Leave the advanced update URL empty to use official GitHub releases. Source builds can check and download too. You can save a check interval and opt into automatic downloads of newer versions. Downloads show progress, support cancellation and retries, and verify file integrity. Open the completed file's folder, fully exit the tray app, then run the installer manually. Automatic restart and installation are not enabled.

## Running from source

To use the app, you can download the installer. Running or modifying the source requires Python 3.12 or newer and Node.js 22 or newer.

1. Download or clone this repository and enter the project root.
2. Run `setup_studyforge.cmd` to install the Python and Node dependencies.
3. After setup completes, run `start_studyforge_source.cmd` to explicitly open the source build.

If `dist/win-unpacked/StudyForge.exe` exists, `start_studyforge.cmd` opens that executable first. To explicitly run the current source, install the dependencies and run this command from the project root:

```bash
npm start
```

To build a Windows x64 installer, complete the dependency setup above, then run:

```powershell
python -m pip install pyinstaller
npm run build:win
node scripts/check_windows_release.cjs
```

The installer is written to `dist/`. Optional CUDA runtime components are not project-owned source code. Without those components, you can build an installer that uses CPU speech recognition. See `THIRD_PARTY_NOTICES.md` for component details.

A rough guide to the directories:

| Directory | Contents |
| --- | --- |
| `desktop/` | Electron desktop entry point, windows, runtime integration, and related functions |
| `studyforge/` | Python backend, material processing, AI calls, and output generation |
| `web/` | Desktop workspace, phone pages, and the in-app guide |
| `scripts/` | Build and helper scripts |
| `integrations/` | Optional Codex and DSH connection scripts and configuration templates |
| `tests/` | Existing tests |
| `docs/` | Topic-specific documentation and development records |

## Open-source license

Copyright (C) 2026 keke271828.

StudyForge's own code and documentation are fully licensed under the [GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-only`). The complete project source and build scripts are public in this repository. You may use, study, modify, and distribute the project, including commercially, subject to the license and its corresponding-source requirements. If you modify the program and let users interact with that version over a network, you must offer those users its Corresponding Source as required by the license. The project adds no separate “educational use only” or “non-commercial use” restrictions. See `LICENSE` for the full terms.

Third-party libraries, fonts, and runtimes retain their own licenses. AI services, models, and imported study materials also remain subject to their respective terms; the project license does not replace those permissions. See [Third-party components and licenses](THIRD_PARTY_NOTICES.md).

## Reporting problems

Report issues through [GitHub Issues](https://github.com/keke271828/StudyForge/issues). The following details are more useful for diagnosis than simply saying “it does not work”:

```text
What I was trying to do:
Installer or source build:
Windows version:
AI service and model:
Material type, size, and selected range:
Steps I took or input I entered:
Expected result:
Actual behavior or full error:
Does it happen every time?
Screenshots or minimal reproduction materials:
```

Remove API keys, tokens, account credentials, and private content before submitting. Problems reproducible with one redacted page or a small example are usually easier to investigate.

Please point out problems with the features, interface, documentation, or explanations. This project still has many shortcomings. Your specific feedback will help it grow and go further. Thank you, everyone.
