# Stop hook 和 CI

範本裡的 `.claude/hooks/gate.sh` 和 workflow 做什麼。怎麼複製到專案，見 [README](../README.md) 的「安裝到專案」。

## Claude Code 的 Stop hook

`.claude/hooks/gate.sh` 在 Claude Code 每次回覆結束時（Stop hook）跑第一、二關（`check --base <base> --skip mutation`）。沒過就以結束碼 2 擋下結束，把訊息交回 AI 繼續修。行為：

- base 讀 `.referee.json` 的 `base`，環境變數 `REFEREE_BASE` 可以覆蓋。
- 讀不到 `.referee.json`（檔案不在，或不是合法的 JSON），擋下。
- 找不到 base（例如還沒 fetch），放行，CI 會再擋一次。
- 這次沒有改任何東西，放行。
- 有改東西但 `tools/referee/referee.py` 不在（submodule 沒抓），擋下並提示 `git submodule update --init`。
- 沒過時依「停在第 N 關」給訊息：第一關是測試失敗，第二關是 CRAP 超標，結束碼 2 是量測失敗。

抓錯檢查太慢，不放在 hook 裡，交給 CI。

## CI

`workflows/go.yml`（`templates/go/` 底下，複製成 `.github/workflows/referee.yml`）在 PR 進 main 時跑三關：`fetch-depth: 0` 和 `submodules: true` 抓完整歷史和工具，setup-go、setup-python，再依序執行 `test`、`crap --base <base 的 commit>`、`mutation --base <base 的 commit>`，三個都帶 `--config-from <base 的 commit>`。基準用的是 PR 事件裡 base 的 commit（`github.event.pull_request.base.sha`），不是分支名稱。submodule 的網址是這個 runner 抓不到的私有 repo 時，要在 checkout 步驟加存取權杖。

`workflows/csharp.yml` 一樣，只是把 setup-go 換成 setup-dotnet（範本寫 `10.0.x`，改成專案用的版本；專案有 `global.json` 的話改用 `global-json-file: global.json`）。
