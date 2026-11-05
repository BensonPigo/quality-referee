#!/usr/bin/env bash
# Claude Code 的 Stop hook：AI 要結束時，自動跑第一、二關（check --skip mutation）。
# 沒過就以結束碼 2 結束，Claude Code 會擋下結束，把錯誤訊息交給 AI 繼續修。
#
# 抓錯檢查太慢，不放在這裡，交給 CI。
#
# 沒有讀 stop_hook_active 提早放行：放行的話，AI 修完第二次就不會再被檢查。
# AI 卡住時不會無限循環，Claude Code 在連續被擋 8 次、中間沒有任何工具呼叫時，會自動放行。

cat >/dev/null # 丟掉 Claude Code 傳進來的 JSON，這裡用不到

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Windows 的 python3 可能是開啟 Microsoft Store 的空殼，要真的能執行才用
if python3 -c '' 2>/dev/null; then py=python3; else py=python; fi

# 比較基準讀 .referee.json 的 base，環境變數 REFEREE_BASE 可以覆蓋
base="${REFEREE_BASE:-$("$py" -c 'import json; print(json.load(open(".referee.json", encoding="utf-8")).get("base", "origin/main"))')}"

# 找不到 base（例如還沒 fetch）就不檢查，CI 還會再擋一次
git merge-base "$base" HEAD >/dev/null 2>&1 || exit 0

# 這次沒有改到任何檔案，例如只是回答問題，就不用檢查
if git diff --quiet "$(git merge-base "$base" HEAD)" && [ -z "$(git ls-files --others --exclude-standard)" ]; then
	exit 0
fi

# 工具是用 git submodule 掛進來的，clone 時沒加 --recurse-submodules 就會是空目錄。
# 這時候放行的話，hook 等於沒裝，所以擋下來，請 AI 或開發者把工具抓下來
if [ ! -f tools/referee/referee.py ]; then
	echo '找不到 tools/referee/referee.py：品質工具是用 git submodule 掛進來的，請執行 git submodule update --init 再繼續。' >&2
	exit 2
fi

# 一次呼叫 check，依 .referee.json 的 gates 依序跑；mutation 太慢，這裡略過
out=$("$py" tools/referee/referee.py check --base "$base" --skip mutation 2>&1)
code=$?
[ "$code" -eq 0 ] && exit 0

# check 最後會印「停在第 N 關」，用它判斷是哪一關沒過
stop=$(grep -o '停在第 [0-9] 關' <<<"$out" | tail -n 1)
case "$code:$stop" in
2:*) msg='品質量測失敗（結束碼 2），不是門檻沒過。請依下面的訊息排除問題。' ;;
1:'停在第 1 關') msg='第一關沒過：單元測試失敗。請修正程式，不要刪除或註解掉測試。' ;;
1:'停在第 2 關') msg='第二關沒過：CRAP 超過門檻。依照每個函式後面標的方向拆函式或補測試，不要修改門檻。' ;;
*) msg='品質檢查沒過。請依下面的訊息修正，不要修改門檻。' ;;
esac
printf '%s\n\n%s\n' "$msg" "$(tail -n 60 <<<"$out")" >&2
exit 2
