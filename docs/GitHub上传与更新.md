# GitHub 上传与后续更新

集中仓库：D:/ListingStudio。远程：https://github.com/pyxu3321/listing 。原来的三个目录保留，当前从它们同步源码。

## 这次如何整理

先 clone 已有空仓库，再把前三阶段的源码、测试、配置和说明复制到三个同名子目录。媒体、向量数据库、缓存、虚拟环境、运行结果和本地密钥不上传。根 .gitignore 继续排除这些文件；同步脚本使用文件白名单并扫描常见凭据格式和非空口令配置。

自动扫描无法代替人工核对，尤其是新加的配置。若需要共享完整50套演示数据，应另外准备数据包或对象存储，不要直接取消所有忽略规则。

## 每次更新（仍在原目录开发）

```powershell
cd D:\ListingStudio
python tools/sync_sources.py
git status --short
git diff
git add .
git diff --cached --stat
git commit -m "Describe the change"
git push
```

同步脚本默认源目录在 D:/ 下；其他路径可通过 --source-root 指定。它只复制，不删除仓库中的旧文件；原项目删文件后需核对并同步删除。不要同时修改原目录和仓库副本中的同一文件，否则下一次同步可能覆盖副本改动。

## 从头上传的常用步骤

若已有 GitHub 仓库，可以像这次一样先 `git clone <仓库地址>`，再复制源码、提交并推送。若已有本地源码目录，则通常使用：

```powershell
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/pyxu3321/listing.git
git push -u origin main
```

不要在已经初始化或已经设置 origin 的目录重复执行 init/remote add。用 `git remote -v` 与 `git branch -vv` 查看当前状态。本次工作分支采用 codex/ 前缀，具体分支以 `git branch --show-current` 为准，推送该分支即可。

首次 HTTPS 推送可能通过 Git Credential Manager 要求浏览器登录。请在自己的登录窗口完成，不要把密码或 token 放进代码、聊天或远程 URL。认证失败时先修复 GitHub 登录/仓库权限，再重试 push；不要强制推送覆盖他人的分支。

## 同事获取

```powershell
git clone https://github.com/pyxu3321/listing.git
cd listing
git branch -a
```

切换到 GitHub 上实际存在的开发分支。已 clone 的同事使用 `git pull` 获取更新。查看代码不需要运行模型；运行当前真实数据前端，还需要模型、素材和特征库，见根 README。

官方说明：https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
