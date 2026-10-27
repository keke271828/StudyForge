# StudyForge 发布与下载

当前对外版本为 **0.0.1 初版**。项目介绍和使用说明见仓库根目录的 README，发布正文见 `docs/Release-0.0.1.md`。

## 下载与安装

打开 [Releases](https://github.com/keke271828/StudyForge/releases/latest)，下载 `StudyForge-Setup-0.0.1.exe`，按安装器提示操作。源码包 `StudyForge-source-0.0.1.zip` 用于运行或修改源码。

两个 `.sha256.txt` 文件用于核对下载完整性。安装器未做商业代码签名；Windows 提示未知发布者时，请先核对下载来源。AI 账号、密钥和额度需要自行准备。

## 维护发布

- 产品版本以 `package.json`、`pyproject.toml` 和 `studyforge.__version__` 为准，桌面安装包和后端版本必须一致。
- 发布标签为 `v0.0.1`，标题为 `StudyForge 0.0.1`，正文使用中英对应的初版介绍、功能和使用方法。
- 源码提交到仓库；安装器、源码 ZIP 和校验文件作为 Release 附件，不提交构建目录、用户学习数据或密钥。
- 先创建草稿，上传后核对每个附件的大小和 SHA-256，再发布并检查匿名访问。
- 自动安装需要正式更新源和发布者签名。当前请使用 Release 中的安装包。

---

# StudyForge publishing and downloads

The public product version is **0.0.1, the initial release**. See the repository README for the introduction and instructions, and `docs/Release-0.0.1.md` for release text.

Download `StudyForge-Setup-0.0.1.exe` from [Releases](https://github.com/keke271828/StudyForge/releases/latest) and follow the installer. `StudyForge-source-0.0.1.zip` is for running or modifying the source. Use the matching `.sha256.txt` files to check integrity. The installer is not commercially code-signed. Supply your own AI account, keys, and quota.

Keep desktop, Python package, and backend versions consistent. Use tag `v0.0.1`, title `StudyForge 0.0.1`, and bilingual initial-release information. Commit source only; attach installers, source archives, and checksums to the Release. Never include learning data, credentials, or build folders. Verify every asset's size and SHA-256 in a draft before publishing and testing anonymous access. Automatic installation is not enabled; use the Release installer.
