# run_gui_agent_loop.py — step-wise loop with snapshot after each action and re-plan on failure
import os
import json
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

from agent_llm import plan_actions
from executor_playwright import run_plan_stepwise
from snapshot_runtime import snapshot_page


def main(args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    first_prompt = (args.prompt or "").strip()
    email_value = (args.email or "").strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(args.start_url, wait_until="load")

        print("🤖 GUI Agent step-wise mode. Type 'exit' to quit.")

        round_id = 1
        user_prompt = first_prompt

        while True:
            # 1) 先拍 pre 快照
            label_pre = f"r{round_id}_pre"
            min_json, _, png = snapshot_page(page, out_dir, label=label_pre)
            print(f"[SNAPSHOT] {label_pre} -> {png} (elements: {len(min_json['elements_min'])})")

            # 2) 取得使用者指令
            if not user_prompt:
                user_prompt = input("\nYour instruction > ").strip()
            if user_prompt.lower() in {"exit", "quit"}:
                break
            if ("email" in user_prompt.lower()) and not email_value:
                email_value = input("Enter email to use: ").strip()

            # 3) 規劃
            plan = plan_actions(user_prompt, min_json, email_value=email_value)
            print("\n[PLAN]\n", json.dumps(plan, indent=2, ensure_ascii=False))

            # 4) 執行：每個 primitive action 後都拍快照
            step_counter = {"i": 0}
            def after_each(action: str, target):
                step_counter["i"] += 1
                lab = f"r{round_id}_a{step_counter['i']}"
                snapshot_page(page, out_dir, label=lab)
                print(f"[SNAPSHOT] after {action} -> {lab}")

            ok = run_plan_stepwise(
                page,
                min_json,
                plan,
                user_vars={"EMAIL": email_value},
                on_after_action=after_each,
            )

            # 5) 若失敗：以最新畫面重拍 & 重規劃一次（同一句指令）
            if not ok:
                min_json, _, _ = snapshot_page(page, out_dir, label=f"r{round_id}_recover")
                print("[INFO] Re-planning due to previous action failure...")
                plan = plan_actions(user_prompt, min_json, email_value=email_value)
                print("\n[PLAN-RETRY]\n", json.dumps(plan, indent=2, ensure_ascii=False))
                step_counter["i"] = 0
                ok = run_plan_stepwise(
                    page,
                    min_json,
                    plan,
                    user_vars={"EMAIL": email_value},
                    on_after_action=after_each,
                )

            # 6) 下一回合
            user_prompt = ""
            round_id += 1

        ctx.close()
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start_url", required=True, help="e.g. https://new.express.adobe.com/")
    ap.add_argument("--out_dir", default="runs/loop", help="directory to store snapshots")
    ap.add_argument("--prompt", default="", help="first instruction; later will prompt interactively")
    ap.add_argument("--email", default="", help="email to use when needed")
    args = ap.parse_args()
    main(args)
