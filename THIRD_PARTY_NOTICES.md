# 第三方组件与许可

项目自有代码与文档的授权见根目录 `LICENSE`。

StudyForge 的项目许可证不会替代第三方组件的许可证。复制或分发相关组件时，请保留它们原有的版权声明、许可证与必要说明。下表列出仓库自带的网页组件和许可证选择中需要注意的依赖；完整依赖以 `package-lock.json`、`pyproject.toml` 以及实际安装包内各组件的授权文件为准。

| 组件 | 许可与来源 | 仓库中的说明 |
| --- | --- | --- |
| KaTeX 与其字体 | MIT；https://github.com/KaTeX/KaTeX | `web/vendor/katex-LICENSE` |
| Marked | MIT；https://github.com/markedjs/marked | `web/vendor/marked-LICENSE` |
| DOMPurify | 随仓库保留的 Apache-2.0 许可；https://github.com/cure53/DOMPurify | `web/vendor/dompurify-LICENSE` |
| PyMuPDF / MuPDF | GNU AGPL v3 或 Artifex 商业授权；https://pymupdf.io/licensing | 项目直接声明了 `pymupdf` 依赖；当前构建环境版本为 PyMuPDF 1.28.2 |
| imageio-ffmpeg / FFmpeg | Python 包为 BSD-2-Clause；当前 FFmpeg 7.1 可执行文件声明 GPL-3.0-or-later | [FFmpeg 许可原文](third_party/ffmpeg/COPYING.GPLv3)；[FFmpeg 7.1 上游源码](https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz)；[Windows 构建来源](https://www.gyan.dev/ffmpeg/builds/) |

PyMuPDF 与 MuPDF 的当前组件版本均为 1.28.2，可从 [PyMuPDF 上游](https://github.com/pymupdf/PyMuPDF)和 [MuPDF 上游](https://github.com/ArtifexSoftware/mupdf)取得源码及构建资料。Python 包的 BSD 许可不替代随包 FFmpeg 可执行文件声明的 GPL 许可；该可执行文件的版权属于 FFmpeg 开发者，GPLv3 原文随本仓库和安装包一并提供。

Windows 安装包还包含 Electron、Python 和后端依赖；如提供可选 NVIDIA CUDA 运行组件，它们遵循自己的授权条款。`imageio-ffmpeg` 包与其中的 FFmpeg 可执行文件也可能采用不同许可证。不要将项目许可证理解为对所有运行时和第三方二进制文件的统一重新授权。

AI 服务、账号、模型权重和用户上传的教材等内容不因 StudyForge 开源而获得额外使用或分发授权。

---

# Third-party components and licenses

The bundled PyMuPDF and MuPDF components are version 1.28.2; their upstream source repositories are linked above. The `imageio-ffmpeg` Python package is BSD-2-Clause, while the bundled FFmpeg 7.1 executable declares GPL-3.0-or-later and is copyright the FFmpeg developers. Its GPLv3 text is included in `third_party/ffmpeg/COPYING.GPLv3`; the table links to the FFmpeg 7.1 source archive and the Windows build provider.

See the root `LICENSE` for the license of the project's own code and documentation.

StudyForge's project license does not replace third-party licenses. Preserve the copyright, license, and required notices of any components you copy or distribute. The table above identifies bundled web components and a dependency relevant to the project license. Refer to `package-lock.json`, `pyproject.toml`, and the license files included with the actual installed components for the complete dependency set.

The Windows installer also contains Electron, Python, and backend dependencies. Optional NVIDIA CUDA runtime components have their own terms. The `imageio-ffmpeg` Python package and its bundled FFmpeg executable may have different licenses. The project license does not relicense all runtimes and third-party binaries.

AI services, accounts, model weights, and imported textbooks or other study materials remain subject to their respective rights and terms.
