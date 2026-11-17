# 更新記錄

## 未發布

只搬文件，程式、範本、判定規則都沒變。

- README 只留安裝、日常使用和設定檔範例，其餘搬到 `docs/`：`鎖定規則.md`、`Hook與CI.md`、`Go檢查員.md`、`CSharp檢查員.md`、`已知限制.md`、`驗證狀態.md`；「開發」搬到 `CONTRIBUTING.md`。下面舊版本寫的「見 README」，內容現在在這些檔案裡。
- 已知限制依主題分開：繞過檢查的改法併進 `鎖定規則.md` 的「還擋不住的」，量測工具的限制併進各檢查員文件的「限制」，`已知限制.md` 只留判定規則本身看不到的情況。重複的條目合併。
- README 依三位新讀者的試讀回饋改寫：三道關補上 CRAP、抓錯率、測到率的白話定義，註明第三關即 mutation testing，說明只檢查改到的；新增「支援的語言和工具」（含不用 Claude Code、不用 GitHub 時）；安裝步驟標出 Claude Code 專用的檔案，補上量現況、送第一個 PR、一次上一關、升級；新增「沒過時怎麼辦」；「誰扮演什麼角色」和文件索引移到後面。
- README 修正：C# 安裝說明寫「最後一行換成」，實際要換的是複製 workflow 的那一行。
- Stop hook 的觸發時機寫成「每次回覆結束時」，不再寫「結束對話時」（README、`Hook與CI.md`、`已知限制.md`）。
- README 依第二輪試讀回饋：C# 標明還在試驗階段；補 Stop hook 的白話說明、抓錯率和測到率的數字例子、其他語言怎麼起手；`python` 的說明統一寫在「需求」；「把規則鎖起來」縮成一段加連結，副作用補上 CODEOWNERS 也鎖 `CLAUDE.md`；新增「擋不住什麼」摘要；「誰扮演什麼角色」移到 `CONTRIBUTING.md`。
- `docs/合約.md`：context 範例的 `exclude` 改成 `tools/referee/`；報告範例的 `referee_version` 改成 `0.4.0`。
- 範本 `CLAUDE.md`、`CODEOWNERS`：「結束對話時」改成「每次回覆結束時」；`CLAUDE.md` 的手動指令註明只有 `python3` 的機器要換。只改措辭，已經複製到專案裡的不用重新複製。
- `驗證狀態.md` 改成表格，驗證過程的細節（PR 編號、各次的數字）不再保留。
- `.referee.json` 每個鍵的說明和排除清單的範例併進 `docs/合約.md`，README 不再重複一份。
- `docs/合約.md` 設定檔範例的 `exclude` 從 `tools/` 改成 `tools/referee/`，跟 v0.4.0 的範本一致。

## v0.4.0

把規則鎖起來：CI 的設定檔改讀 base 的版本、CODEOWNERS 範本，以及審查時找到的幾個繞過方式。判定規則、記分表和報告的格式都沒變。

- 四個指令新增 `--config-from <分支或 commit>`：設定檔改讀那個 commit 上的 `.referee.json`，工作目錄裡改過的設定這次不採用，並印出來。只有那個 commit 上確定沒有設定檔（第一次導入）才改用工作目錄的。排除清單照樣讀工作目錄的，比那個 commit 多了幾項會印出來。
- workflow 範本：三個步驟都加 `--config-from`；`--base` 和 `--config-from` 都改用 `github.event.pull_request.base.sha`，不用分支名稱。之前 CI 讀的是 PR 自己的設定檔，在 PR 裡把門檻改鬆就會過。
- 新增 CODEOWNERS 範本（`templates/<語言>/CODEOWNERS`），README 新增「把規則鎖起來」。
- 改到的行：`git diff` 加 `--text --no-textconv`。之前在 `.gitattributes` 加一行 `*.go -diff`，git 就不輸出改到的行，第二、三關都回報「這次沒有改到」而通過。
- `--base`、`--config-from` 給的名稱同時是分支和 tag 時，以結束碼 2 停下。git 會優先解析 tag，推一個叫 `origin/main` 的 tag 就能換掉比較基準。
- 範本的 `exclude` 從 `tools/` 改成 `tools/referee/`。之前把程式搬到 `tools/` 底下任何目錄就不受檢查。
- `.referee.json` 是目錄時以結束碼 2 停下，不再印 traceback。
- **升級注意**：workflow 和 `.referee.json` 是複製到專案裡的，要自己改：workflow 照新範本加上 `--config-from` 並改用 base 的 commit；`exclude` 的 `tools/` 改成 `tools/referee/`（專案自己在 `tools/` 底下有別的程式要排除的話，逐一列出）。新的 `CODEOWNERS` 照 README 複製並設定分支保護。

## v0.3.0

第三關新增「每個函式至少抓到一個改壞的版本」、門檻加上界線、gate.sh 不再因為設定檔壞掉而放行、新增給 AI 的導入指引。記分表的格式沒變；報告升成 `referee.report/2`。

- 第三關：改到的每個函式（沒有 `--base` 時是全部函式），只要有算進比例的改壞版本、卻一個都沒被抓到，就判沒過並列出來。抓錯率和測到率是整體的比例，一個函式完全沒有測試時可能照樣過門檻（實際遇過：11 個改壞版本全部沒被測試跑到，測到率剛好 50%）。函式的範圍取自 `crap.inspector`，第三關會先執行它一次；沒有設定時不做這項檢查。沒有門檻可以調。
- 報告 `referee.report/2`：`mutation` 區塊多了 `undetected_functions`。讀報告的程式要認得新的 `schema` 字串。
- 排除清單：有 `--base` 時，沒改到的行上對得上清單的改壞版本也標成 `EQUIVALENT`（之前只標改到的行；計數和比例不受影響，新規則要用）。
- Go 檢查員：因為 build constraint 在這個平台不編譯的檔案不再產生改壞的版本。之前 gremlins 會產生，全部算成「測試沒跑到」，拉低測到率，補測試也救不了。

- `.referee.json`：`crap.threshold` 必須大於 0、不能超過 30；`mutation.kill_rate_threshold`、`mutation.reach_rate_threshold` 必須在 0 到 100 之間；`gates` 至少要啟用一關。超出範圍是結束碼 2。
- `gate.sh`：讀不到 `.referee.json`（檔案不在，或不是合法的 JSON）時擋下。之前會因為讀不到 base 而放行，弄壞設定檔就等於關掉檢查。
- 新增 `docs/AI導入指引.md`：AI 替專案建立三道關的步驟，包含從零建立測試、替舊程式補測試、測試寫不出來時怎麼回報程式結構的問題。
- 指引依一次實測（全新的 AI 只拿到 skill，替一個沒有測試的 .NET 電商服務建立三道關）修正：補測試時 `check --base` 一定通過，改以不帶 `--base` 的結果為準；函式只有一部分測得到時怎麼做；靜態狀態怎樣測不算硬測；不用條件不成立的案例湊覆蓋率。
- 範本新增 `CLAUDE.md` 和 `.claude/skills/referee-onboard/`（兩個語言一模一樣），都指向上面的指引。
- README：`gates` 的順序不影響 `check` 的執行順序（之前寫錯，實際一直是固定 test → crap → mutation）；補上沒有改壞版本時不判定、比例是整體計算、沒有測試的專案第一關會通過。
- 加上 `LICENSE`（MIT）。
- **升級注意**：第三關可能出現新的 FAIL：改到的函式沒有任何改壞版本被抓到。用 Go 檢查員的 package 範圍、測試放在別的套件的專案，要改用 `--coverage-scope module`。`crap.threshold` 設超過 30 的專案，升級後會以結束碼 2 停下，要先把門檻調到 30 以內。`gate.sh` 是複製到專案裡的，要重新複製一次；`CLAUDE.md` 和 skill 是新檔案，照 README「安裝到專案」複製。

## v0.2.1

依 macOS 上 C# 檢查員試點的回饋修正。判定規則、合約、報告的 JSON 格式都沒變。

- `test`：最後印判定行「PASS：測試指令結束碼 0」或「FAIL：測試指令結束碼 N，單元測試沒過」，跟 `crap`、`mutation` 一致。之前只印測試指令自己的輸出，要看結束碼才知道過不過。
- 「檢查員設定」那一行，沒指定的值（例如沒帶 `--workers`）印成「預設」，不再印「null」。JSON 報告裡照舊是 `null`。
- README：範本是點開頭的檔案，要用 `ls -a` 看；C# 已知限制加上 Stryker.NET 會把同一個位置編得過的改壞版本一起標成無效；驗證狀態加上 macOS。
## v0.2.0

新增 C# 標準檢查員（SDK 風格、.NET 6 以上的專案）。合約、裁判的判定規則、Go 檢查員都沒變。

- `inspectors/csharp.py functions`：內附的 Roslyn 工具依原始碼算複雜度（規則和 gocyclo 一樣），`dotnet test` 加 coverlet 依行算每個函式的覆蓋率。
- `inspectors/csharp.py mutants`：Stryker.NET 5.0.0，有改到的檔案時只改壞那些檔案；測試一開始就失敗時以結束碼 2 停下。
- 工具都放在 `REFEREE_TOOLS_DIR`，在帶隔離設定檔的目錄建置和安裝，不受專案的 `Directory.Build.*`、中央套件管理、`global.json`、`NuGet.config` 影響，也不在 `tools/referee/` 底下留下檔案。
- 專案範本 `templates/csharp/`：`.referee.json`、`.referee-equivalents.json`、`.claude/settings.json` 和 `gate.sh`（跟 Go 的一模一樣）、GitHub Actions 的三關 workflow（setup-dotnet）。
- selftest 加上 C# 範例專案；`selftest.py` 支援多個語言（`{csharp_inspector}`、範例資料裡的 `crap_settings_line`、`hostile_tools_dir`、`crap_snapshot`）。selftest 的 CI 加上 setup-dotnet。
- C# 的已知限制見 README。

## v0.1.3

- 加上 `.gitattributes`：`*.sh` 一律以 LF 取出。之前在 Windows 上 `core.autocrlf=true` 時，submodule 裡的 `gate.sh` 會是 CRLF，照 README 用 `cp` 複製到專案後，bash 可能因為 `$'
'` 執行失敗。
- `gate.sh`：`&&` 和 `[` 之間補一個空格（v0.1.2 漏掉，不影響執行）。
- **升級注意**：v0.1.2 在 Windows 上用 `cp` 複製過 `gate.sh` 的專案，確認檔案是 LF（`git ls-files --eol .claude/hooks/gate.sh` 的 `w/` 要是 `lf`）。升到 v0.1.3 後重新複製一次即可。

## v0.1.2

- `gate.sh`：判斷有沒有改東西的 `git diff` 不再把警告（例如 Windows 上 `core.autocrlf=true` 時的「LF will be replaced by CRLF」）混進交給 AI 的訊息。
- **升級注意**：`gate.sh` 是複製到專案裡的，升級 submodule 不會更新它。要重新執行 `cp tools/referee/templates/go/.claude/hooks/gate.sh .claude/hooks/`。
- README 的驗證狀態：BeThere 實際導入的三關結果，以及 Claude Code 實際觸發 Stop hook，改列為已驗證。

## v0.1.1

- `crap` 不加 `--base`（整個專案）時，超標的函式後面也附改善方向（「要拆函式」或「覆蓋率要到 X%」），跟 `--base` 和 JSON 報告一致。
- Go 檢查員的 `functions` 不再把 `workers` 寫進 `settings`：量 CRAP 不跑 gremlins，`--workers` 不生效，之前沒帶時會顯示「workers null」。

## v0.1.0

第一版。

- 裁判核心：讀 `.referee.json`，執行設定檔指定的檢查員指令，讀記分表，判定單元測試、CRAP、抓錯檢查三道關；`test`、`crap`、`mutation`、`check` 四個指令，文字和 JSON 報告（`referee.report/1`）。
- 合約：檢查員的呼叫方式（`REFEREE_OUT`、`REFEREE_CONTEXT`）、函式表（`referee.functions/1`）、改壞版本表（`referee.mutants/1`）、路徑比對規則，寫在 `docs/合約.md`。
- Go 標準檢查員 `inspectors/go.py`：gocyclo、gremlins 的結果轉成記分表，參數 `--coverage-scope`、`--workers`。
- 排除清單沿用 quality-tools v2.4.0 的格式（含 `column`）。改名的檔案只算真的改到的行。
- 專案範本 `templates/go/`：`.referee.json`、`.referee-equivalents.json`、Claude Code 的 Stop hook（`gate.sh`）和 `settings.json`、GitHub Actions 的三關 workflow。
- 開發用：`selftest.py`（Go 範例專案的全部情境，含 gate.sh）、`dev/parity_qt.py`（和 quality-tools v2.4.0 對照）、`dev/walkthrough_bethere.py`（照 README 在 BeThere 的暫存複本上走一遍）、`.github/workflows/selftest.yml`。

已知限制見 README。workflow 還沒在 runner 上跑過。
