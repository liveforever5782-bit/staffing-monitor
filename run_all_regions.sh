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

# HTMLレポートを再生成（最新データを反映・全10エリア）
echo "----- HTMLレポート生成開始: $(date '+%H:%M:%S') -----" >> "$LOG"
"$PYTHON" /Users/mitsuhashitomohiro/staffing_monitor/build_html.py 北海道 宮城県 東京都 埼玉県 千葉県 神奈川県 愛知県 大阪府 広島県 福岡県 >> "$LOG" 2>&1
echo "----- HTMLレポート生成完了: $(date '+%H:%M:%S') -----" >> "$LOG"

# 最終の10エリア版HTMLを GitHub Pages へ公開（monitor.py の個別pushを最終状態で上書き）
echo "----- GitHub最終プッシュ開始: $(date '+%H:%M:%S') -----" >> "$LOG"
cd /Users/mitsuhashitomohiro/staffing_monitor || exit 1
DATE_STR=$(date '+%Y-%m-%d')
git add monitoring_report.html >> "$LOG" 2>&1
# 差分がある場合のみコミット（--allow-empty は使わない）
if ! git diff --cached --quiet; then
    git commit -m "final 10-area update ${DATE_STR}" >> "$LOG" 2>&1
    git push >> "$LOG" 2>&1
    echo "✅ 最終10エリア版をGitHubへプッシュしました" >> "$LOG"
else
    echo "ℹ️  HTMLに差分なし（すでに最新）" >> "$LOG"
fi
echo "----- GitHub最終プッシュ完了: $(date '+%H:%M:%S') -----" >> "$LOG"
