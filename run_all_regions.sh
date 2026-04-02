#!/bin/bash
# 全エリアの求人モニタリングを順番に実行するスクリプト
# 毎朝 09:00 に LaunchAgent から自動実行される

PYTHON=/usr/bin/python3
SCRIPT=/Users/mitsuhashitomohiro/staffing_monitor/monitor.py
LOG=/Users/mitsuhashitomohiro/staffing_monitor/auto_run.log

echo "===== 自動実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"

REGIONS=(
    "北海道"
    "宮城県"
    "埼玉県"
    "千葉県"
    "神奈川県"
    "東京都"
    "愛知県"
    "大阪府"
    "広島県"
    "福岡県"
)

for REGION in "${REGIONS[@]}"; do
    echo "----- $REGION 開始: $(date '+%H:%M:%S') -----" >> "$LOG"
    "$PYTHON" "$SCRIPT" "$REGION" >> "$LOG" 2>&1
    echo "----- $REGION 完了: $(date '+%H:%M:%S') -----" >> "$LOG"
    echo "" >> "$LOG"
done

echo "===== 全エリア完了: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"

# HTMLレポートを再生成（最新データを反映）
echo "----- HTMLレポート生成開始: $(date '+%H:%M:%S') -----" >> "$LOG"
"$PYTHON" /Users/mitsuhashitomohiro/staffing_monitor/build_html.py >> "$LOG" 2>&1
echo "----- HTMLレポート生成完了: $(date '+%H:%M:%S') -----" >> "$LOG"
