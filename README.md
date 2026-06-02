# 地端 Agent — Learn From Claude Code

> 將 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 教程改寫成使用地端模型的版本。
> 原版使用 Anthropic Claude API；本版使用 **gemma-4 + vllm**，不需要任何 API key。

---

## 簡介

本教程適合已了解 LLM 與 RAG 基礎、想進一步學習如何打造 **AI Agent** 的開發者。

**Agent = LLM + Harness**

- **LLM**：負責推理、規劃、決策
- **Harness**：負責工具執行、記憶管理、任務追蹤、context 壓縮

本教程從最小的 agent loop 開始，逐步疊加 harness 元件，每個檔案對應一個概念。

---

## 環境需求

| 元件 | 說明 |
|------|------|
| Python 3.10+ | |
| vllm | 推論引擎，提供 OpenAI-compatible API |
| gemma-4-26B-A4B-it-AWQ-4bit | 地端模型 |
| API 位址 | `http://localhost:8999/v1` |

安裝 Python 依賴：

```bash
pip install -r requirements.txt
```

設定環境變數（複製 `.env` 並視需要修改）：

```bash
# .env
BASE_URL=http://localhost:8999/v1
MODEL_ID=google/gemma-4-26B-A4B-it-AWQ-4bit
API_KEY=none
```

---

## 與原版的差異

原版使用 Anthropic SDK，本版改用 OpenAI SDK 以對接 vllm：

| | 原版 (Anthropic) | 本版 (OpenAI/vllm) |
|--|--|--|
| Client | `Anthropic(base_url=...)` | `OpenAI(base_url=..., api_key="none")` |
| Tool 格式 | `input_schema: {...}` | `{"type":"function","function":{"parameters":{...}}}` |
| Stop 判斷 | `stop_reason == "tool_use"` | `finish_reason == "tool_calls"` |
| Tool result | `{"type":"tool_result", ...}` | `{"role":"tool", "tool_call_id":...}` |
| System prompt | 獨立參數 | messages 第一條 `{"role":"system"}` |

---

## 教程結構

```
agents/
  s01_agent_loop.py      # 最小 agent loop
  s02_tool_use.py        # 多工具 dispatch
  s03_todo_write.py      # Todo 任務追蹤
  s04_subagent.py        # 子 agent context 隔離
  s05_skill_loading.py   # 兩層 skill 按需載入
  s06_context_compact.py # 三層 context 壓縮 + todo 整合

skills/
  git/SKILL.md           # Git 操作指南
  pdf/SKILL.md           # PDF 處理指南
```

---

## S01 — Agent Loop

**概念**：Agent 的核心是一個 while loop，不斷呼叫 LLM 直到它決定停止。

```
while finish_reason == "tool_calls":
    response = LLM(messages, tools)
    執行工具
    將結果放回 messages
```

```bash
python agents/s01_agent_loop.py
```

---

## S02 — Tool Use

**概念**：Loop 不需要改，只需增加工具。用 dispatch map 路由工具呼叫。

工具：`bash` / `read_file` / `write_file` / `edit_file`

```bash
python agents/s02_tool_use.py
```

---

## S03 — Todo List

**概念**：讓 LLM 自己維護一份 todo 清單，追蹤多步驟任務的進度。  
若 LLM 超過 3 輪沒更新 todo，自動注入提醒。

```
[x] #1: 讀取需求
[>] #2: 實作功能   ← 進行中
[ ] #3: 寫測試
```

```bash
python agents/s03_todo_write.py
```

---

## S04 — Subagent

**概念**：子任務用全新的 context 執行，完成後只回傳摘要給主 agent。  
避免子任務的執行細節污染主 agent 的思維。

```
主 agent (context 保持乾淨)
    └── task("分析檔案") ──► 子 agent (fresh context)
                                 執行 → 回傳摘要
                                 context 丟棄
```

```bash
python agents/s04_subagent.py
```

---

## S05 — Skill Loading

**概念**：按需載入專業知識，避免 system prompt 過度膨脹。

- **Layer 1**（system prompt）：只放 skill 名稱 + 一行描述（~100 tokens/skill）
- **Layer 2**（tool_result）：LLM 呼叫 `load_skill("git")` 時才載入完整內容

新增 skill：在 `skills/<name>/SKILL.md` 放 YAML frontmatter + 內容即可。

```bash
python agents/s05_skill_loading.py
```

---

## S06 — Context Compact

**概念**：三層壓縮讓 agent 能無限執行，同時用 todo 保持任務連續性。

| 層 | 觸發 | 動作 |
|----|------|------|
| micro_compact | 每輪自動 | 舊 tool result 換成佔位符 |
| auto_compact | tokens 超過門檻 | LLM 摘要對話，替換 messages |
| compact tool | LLM 主動呼叫 | 同 auto，可指定保留重點 |

**關鍵設計**：`TodoManager` 存在 Python 記憶體，不在 `messages[]` 裡，因此 compact 壓縮對話時 todo 清單完全不受影響，agent 醒來後能繼續未完成的任務。

```bash
python agents/s06_context_compact.py
```

---

## 簡報

`slides.md` / `slides.pdf` — 本教程的投影片（Marp 格式）

重新產生 PDF：

```bash
CHROME_PATH=$(which chromium) marp slides.md --pdf --allow-local-files --no-sandbox
```

---

## 參考資料

- 原版教程：[shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)
- vllm：[github.com/vllm-project/vllm](https://github.com/vllm-project/vllm)
- Gemma 4：[google/gemma-4](https://huggingface.co/google/gemma-4)
