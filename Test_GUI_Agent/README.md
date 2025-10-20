# GUI Agent — Stepwise Web Automation Framework

This project is a modular framework that combines **Playwright**, **OpenAI LLMs**, and **accessibility-aware DOM snapshots** to create a reasoning-capable GUI Agent that can interact with real web interfaces step-by-step.

## 📂 Project Structure
- run_gui_agent_loop.py     — Main loop: snapshot, plan, execute, replan
- executor_playwright.py    — Executes each action (click, type, wait)
- agent_llm.py              — Uses OpenAI LLM to plan actions from user prompts
- snapshot_runtime.py       — Captures DOM + AX Tree with minimal JSON

## ⚙️ Setup
```bash
conda create -n agentlab_env python=3.10
conda activate agentlab_env
pip install -r requirements.txt
playwright install chromium
```
Then set your OpenAI API key:
```bash
export OPENAI_API_KEY="sk-xxxxxx"
```

## 🚀 Example Run
```bash
python run_gui_agent_loop.py   --start_url "https://new.express.adobe.com/"   --out_dir "runs/adobe_test"   --prompt "Enter my email and click Continue"   --email "zoelee19991226@gmail.com"
```

## 📦 Output
Each run saves screenshots and DOM+AX JSON snapshots to `runs/<session>/`.

## 🧰 Requirements
See `requirements.txt`.
