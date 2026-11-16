# 品質檢查

這個專案用 quality-referee 做三道品質檢查，工具掛在 `tools/referee/`（git submodule）。結束對話時 `.claude/hooks/gate.sh` 會自動跑第一、二關，第三關在 CI 跑。

- 改程式要附測試。測試的正確答案照需求寫，不能從程式的輸出抄來。
- 不刪除、註解掉、跳過測試，不把斷言改鬆。
- 不修改 `.referee.json`、`.referee-equivalents.json`、`.gitmodules`、`tools/referee/`、CI 設定、`.claude/`。認為門檻或排除清單該調整時，寫出理由交給人決定。
- 檢查沒過時，照訊息標的方向修：「要拆函式」就拆，「覆蓋率要到 X%」就補測試。
- 專案還沒有測試、要替舊程式補測試，或測試寫不出來時，照 `tools/referee/docs/AI導入指引.md` 做。

手動執行：

```
python tools/referee/referee.py check --base origin/main --skip mutation
python tools/referee/referee.py mutation --base origin/main
```
