# Cloud GPU Checker

[English](README.md)

`Cloud GPU Checker` 是一个通过 SSH 查看远程 GPU 实验状态的小工具。

它最初是我为了自己盯云端实验写的。很多时候我们会习惯看 `nvidia-smi`，但它只能告诉你 GPU 忙不忙，却回答不了更关键的问题：

- 当前到底在跑什么实验
- 当前是哪个模型、哪个 horizon
- 哪些子实验已经结束了
- 结果目录里有没有 `MSE / MAE`
- 这一批实验大概还要多久

这个工具会把远程进程、launcher 日志、子实验日志和结果目录拼起来看，给出更接近“实验语义”的状态，而不是只有系统监控信息。

## 这个工具的亮点

对我来说，最有价值的其实就两点：

- 能看当前状态
- 能估算剩余时间

也就是说，你打开之后不只是知道“机器还活着”，而是能更快判断：

- 当前有没有真的在训练
- 正在跑第几个子实验
- 已经完成了多少
- 这一批还要不要继续等

## 截图

### GUI 界面

GUI 版支持保存多个实例配置，来回切换比较方便。

![GUI 界面](assets/screenshots/gui-overview.png)

### 状态结果

输出结果重点展示当前任务、当前模型、已完成部分和大致剩余时间。

![状态结果](assets/screenshots/status-report.png)

## 主要功能

- 通过 SSH 连接远程 Linux 服务器
- 读取实验日志和结果目录
- 显示当前任务、模型和 horizon
- 列出已经完成的子实验，以及已有的 `MSE / MAE`
- 估算当前子实验和整批实验的剩余时间
- 同时提供 CLI 和 Windows GUI
- 支持多个实例配置保存与切换

## 适合什么场景

- 长时间跑 baseline
- 多 horizon 的时间序列实验
- 单卡串行排队的 ablation 实验
- 想判断“是真在训练，还是只是显存挂着”
- 本地一台机器同时管理多个云实例

## 仓库结构

- `cloud_status_core.py`: 核心状态采集与结果格式化逻辑
- `check_cloud_experiment_status.py`: CLI 入口
- `check_cloud_experiment_status.ps1`: PowerShell 启动脚本
- `cloud_gpu_checker_gui.py`: GUI 入口
- `yun_gpu_checker_config.example.json`: 示例配置
- `docs/CSDN_post.md`: 对外分享用的中文文章草稿

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

1. 把 `yun_gpu_checker_config.example.json` 复制成 `yun_gpu_checker_config.json`
2. 填好你的 SSH 信息和实验目录
3. 运行 CLI 或 GUI 版本

## CLI 用法

```bash
python check_cloud_experiment_status.py --config yun_gpu_checker_config.json
```

## PowerShell 用法

```powershell
powershell -ExecutionPolicy Bypass -File .\check_cloud_experiment_status.ps1
```

## GUI 用法

```bash
python cloud_gpu_checker_gui.py
```

## Windows EXE 打包

如果你想分发给不直接跑 Python 的用户，可以用 PyInstaller 打包：

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name "Cloud GPU Checker" cloud_gpu_checker_gui.py
```

生成的可执行文件会在 `dist/` 目录下。

## 示例配置

```json
{
  "last_profile": "Example-Server",
  "profiles": {
    "Example-Server": {
      "host": "example.com",
      "port": "22",
      "user": "root",
      "password": "",
      "key_path": "",
      "run_root": "/workspace/experiments/project",
      "launcher_log": "/workspace/experiments/project/launcher.log",
      "log_root": "/workspace/experiments/project/logs",
      "plan_script": "/workspace/project/scripts/run_baseline.sh"
    }
  }
}
```

## 说明

- 不要提交真实密码或私钥
- 能用 `key_path` 就尽量不用密码
- GUI 会把 `yun_gpu_checker_config.json` 写到程序同目录
- 这个工具更适合用于日志和目录结构比较稳定的实验项目

## 为什么开源

它本来只是我自己盯云端实验时用的一个小帮手。用了一段时间之后，我发现它确实能解决一个很常见但又很烦的问题：机器明明在跑，但你并不知道实验到底进行到哪一步了。

所以我把它单独整理出来，做成了一个可独立使用的小仓库。如果你也经常在云端跑实验，应该会比只看 `nvidia-smi` 更顺手。

## License

MIT
