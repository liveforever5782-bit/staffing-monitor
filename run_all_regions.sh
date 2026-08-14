#!/bin/bash
# 全エリアの求人モニタリングを順番に実行するスクリプト
# 毎朝 09:00 に LaunchAgent から自動実行される

PYTHON=/usr/bin/python3
SCRIPT=/Users/mitsuhashitomohiro/staffing_monitor/monitor.py
LOG=/Users/mitsuhashitomohiro/staffing_monitor/auto_run.log
REPO=/Users/mitsuhashitomohiro/staffing_monitor

echo "===== 自動実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"

# ── HEAD.lock 安全削除 ──────────────────────────────────────
# 前回のgitプロセスがクラッシュしてHEAD.lockが残留すると
# 以降のgit commit/pushが全て失敗し続ける問題への対策
LOCK_FILE="$REPO/.git/HEAD.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null) ))
    if [ "$LOCK_AGE" -gt 300 ]; then
        echo "⚠️  HEAD.lock検出（${LOCK_AGE}秒前に作成）→ 削除して続行" >> "$LOG"
        rm -f "$LOCK_FILE"
    else
        echo "⚠️  HEAD.lock検出（${LOCK_AGE}秒前 ← 5分以内のため保持）" >> "$LOG"
    fi
fi
# ────────────────────────────────────────────────────────────

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

# ── HEAD.lock 再チェック（各エリアのmonitor.pyが残す場合への備え） ──
if [ -f "$LOCK_FILE" ]; then
    echo "⚠️  最終プッシュ前にHEAD.lockを再検出 → 削除" >> "$LOG"
    rm -f "$LOCK_FILE"
fi

# 最終の10エリア版HTMLを GitHub Pages へ公開（monitor.py の個別pushを最終状態で上書き）
echo "----- GitHub最終プッシュ開始: $(date '+%H:%M:%S') -----" >> "$LOG"
cd "$REPO" || exit 1
DATE_STR=$(date '+%Y-%m-%d')
git add monitoring_report.html >> "$LOG" 2>&1
# 差分がある場合のみコミット（--allow-empty は使わない）
if ! git diff --cached --quiet; then
    if git commit -m "final 10-area update ${DATE_STR}" >> "$LOG" 2>&1; then
        if git push >> "$LOG" 2>&1; then
            echo "✅ 最終10エリア版をGitHubへプッシュしました" >> "$LOG"
        else
            echo "❌ git push失敗（ネットワークまたは認証エラー）" >> "$LOG"
        fi
    else
        echo "❌ git commit失敗（HEAD.lockまたはその他のエラー）" >> "$LOG"
    fi
else
    echo "ℹ️  HTMLに差分なし（すでに最新）" >> "$LOG"
fi
echo "----- GitHub最終プッシュ完了: $(date '+%H:%M:%S') -----" >> "$LOG"
