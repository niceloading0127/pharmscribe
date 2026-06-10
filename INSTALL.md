# 安装与快速上手 / Install & Quick Start

## 依赖 Dependencies
```bash
brew install yt-dlp ffmpeg
pip3 install python-docx --break-system-packages
```
免费本地引擎(可选 / for the free local engine):安装 [Ollama](https://ollama.com)，然后 `ollama pull qwen2.5`。

## 作为命令行工具 / As a CLI
```bash
alias pharmscribe="python3 /路径/scripts/pharmscribe.py"
pharmscribe ingest "https://www.youtube.com/watch?v=VIDEO_ID" --engine local
pharmscribe query --target CYP3A4
pharmscribe videos
```

## 作为 Claude Code 技能 / As a Claude Code skill
把整个文件夹放进 `~/.claude/skills/`，重启 Claude Code 即可。
Place the folder in `~/.claude/skills/` and restart Claude Code.
