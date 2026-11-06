# quality-referee

裁判和檢查員分開的品質工具。裁判不認得任何語言，只執行設定檔寫的指令、讀檢查員交出的記分表，依門檻判定三道關：

1. 單元測試：`test.command` 結束碼 0 才算過。
2. CRAP：改到的函式，複雜度和覆蓋率算出來的 CRAP 不能超過門檻。
3. 抓錯檢查：把程式改壞一點，測試要抓得到。改到的行上，抓錯率和測到率要達到門檻。

各語言的量測做法放在「檢查員」裡。第一版只有 Go 的標準檢查員（`inspectors/go.py`）；其他語言，或專案想用自己的量法，寫一支照 [docs/合約.md](docs/合約.md) 交出記分表的腳本，換掉設定檔裡的指令就可以。

需求：Python 3.8 以上，只用標準函式庫。Go 檢查員另外需要 Go（第一次執行時用 `go install` 裝 gocyclo、gremlins，要網路）。Windows 上的 gate.sh 要用 Git for Windows 的 bash。

## 誰扮演什麼角色

把三道關想成一場比賽：規則和判定只有一套，量測的方式各場地自己決定。

| 角色 | 是誰 | 負責 | 不負責 |
|---|---|---|---|
| **裁判** | quality-referee（掛在專案的 `tools/referee/`） | 找出這次改到哪些行和函式；算 CRAP、抓錯率、測到率；比對排除清單；判定過或不過；寫報告；回傳結束碼 | 不認得任何語言，不跑測試，不呼叫任何量測工具 |
| **記分表** | [docs/合約.md](docs/合約.md) 定的兩種 JSON：函式表、改壞版本表 | 裁判和檢查員之間唯一的約定。格式不對，裁判直接以結束碼 2 停下 | — |
| **檢查員** | 一支指令：標準檢查員（例如 `inspectors/go.py`），或專案自己寫的腳本 | 照裁判給的資訊（`REFEREE_CONTEXT`）量測，把原始數字填進記分表 | 不判斷過不過，不算 CRAP，不標「改了也沒差」 |
| **主辦方** | 各專案 repo | 寫 `.referee.json`：用哪個檢查員、帶什麼參數、哪些目錄不算、門檻多少；維護排除清單；寫測試 | 不改裁判的判定規則 |
| **簽名的人** | 審 PR、按合併的人 | 看測試有沒有被刪或改鬆；逐項核准排除清單的 `reason`；決定門檻 | — |

各角色要做的事：

- **quality-referee 的維護者**：判定規則、記分表和報告的格式、標準檢查員都在這裡改，改完發新版本。記分表或報告的格式一改，合約的版本就要跟著升（例如 `referee.functions/1` 升成 `/2`），各專案的自訂檢查員才知道要配合。
- **專案 repo（主辦方）**：
  1. 用 submodule 掛上裁判，複製範本（見「安裝到專案」）。
  2. 在 `.referee.json` 選檢查員。標準檢查員能用就用，只調參數，例如 Go 的 `--coverage-scope module`；標準檢查員量不了這個專案時，自己寫一支，照合約交出記分表（見「自訂檢查員」）。
  3. 寫測試、補測試，讓三道關過得去；認為某個改壞版本「改了也沒差」時，寫進排除清單，交給人核准。
  4. 升級裁判時，改 submodule 指到的版本，再看 CHANGELOG：範本複製出去的檔案（例如 `.claude/hooks/gate.sh`）有改的話，要重新複製。
- **檢查員**（標準的或自訂的都一樣）：只回報量到什麼。函式的複雜度、起訖行、覆蓋率；每個改壞版本在哪一行哪一欄、改了什麼、有沒有被測試抓到。量測失敗時結束碼不是 0，裁判會停下並印出檢查員的輸出。
- **人**：裁判只判斷數字。測試寫得對不對、排除的理由成不成立，要人看。

兩種 JSON 不要搞混：**記分表**是檢查員填、給裁判讀的；**報告**（`referee.report/1`）是裁判寫、給人和 CI 讀的。檢查員不碰報告，所以不管專案用哪個檢查員，判定規則和報告格式都一樣，不同專案的分數可以互相比較。

## 安裝到專案

用 git submodule 把這個 repo 掛在 `tools/referee/`，再把範本複製到專案裡。以 Go 專案為例，在專案根目錄：

```
git submodule add <這個 repo 的網址> tools/referee
cp tools/referee/templates/go/.referee.json .
cp tools/referee/templates/go/.referee-equivalents.json .
mkdir -p .claude/hooks .github/workflows
cp tools/referee/templates/go/.claude/settings.json .claude/
cp tools/referee/templates/go/.claude/hooks/gate.sh .claude/hooks/
cp tools/referee/templates/go/workflows/go.yml .github/workflows/referee.yml
```

用 Gitea 的話，workflow 放 `.gitea/workflows/referee.yml`。接著：

1. 打開 `.referee.json`，依專案調整（見下一節）。
2. 專案裡有掃整個 repo 的檢查（例如掃全部 `.md` 連結、掃全部原始碼風格的測試）時，**把 `tools/referee/` 加進豁免**。submodule 裡有這個工具自己的文件和程式，不是專案的內容。
3. 範本的 `.claude/settings.json` 把 `.referee.json`、`.referee-equivalents.json`、`.gitmodules`、`tools/referee/**`、`.github/**`、`.gitea/**`、`.claude/**` 設成 Claude Code 的編輯工具不能改，避免 AI 靠改門檻或設定讓檢查通過。專案原本已有 `.claude/settings.json` 時，合併 `permissions.deny` 和 `hooks.Stop`，不要整份覆蓋。
4. 其他人 clone 專案時要加 `--recurse-submodules`，或 clone 之後執行 `git submodule update --init`。

## 日常使用

```
python tools/referee/referee.py test
python tools/referee/referee.py crap --base origin/main
python tools/referee/referee.py mutation --base origin/main --json mutation.json
python tools/referee/referee.py check --base origin/main --skip mutation --json reports/
```

| 指令 | 做什麼 |
|---|---|
| `test [--json 檔]` | 第一關，執行 `test.command` |
| `crap [--base B] [--json 檔]` | 第二關。有 `--base` 只檢查改到的函式，沒給就檢查整個專案。超標的函式後面附改善方向：「要拆函式」或「覆蓋率要到 X%」 |
| `mutation [--base B] [--json 檔]` | 第三關。有 `--base` 只算改到的行 |
| `check [--base B] [--skip 關...] [--json 目錄]` | 依 `gates` 的順序跑，第一個沒過就停，印出「停在第 N 關」。`--json` 每一關寫一份：`test.json`、`crap.json`、`mutation.json` |

結束碼：0 通過，1 沒過門檻，2 量測失敗或設定有誤。沒啟用（不在 `gates` 裡）的關印「還沒啟用」並以 0 結束。

`--base` 比對的是「和 base 的共同祖先相比，這次改了哪些行」，含還沒 commit 的修改和還沒加入 git 的新檔案；改名的檔案只算真的改到的行。

## 設定檔 `.referee.json`

未知的鍵、型別不對都是結束碼 2，不會默默改用預設值。

| 鍵 | 預設 | 說明 |
|---|---|---|
| `version` | 必填 | 固定是 `1` |
| `base` | `origin/main` | `check` 沒給 `--base` 時的比較基準，gate.sh 也讀它 |
| `gates` | `["test", "crap", "mutation"]` | 要啟用的關，順序就是 `check` 的執行順序 |
| `sources` | `[]` | 原始碼樣式，例如 `["**/*.go"]`。有 `crap` 或 `mutation` 時至少要一個 |
| `tests` | `[]` | 測試檔樣式，例如 `["**/*_test.go"]`。符合的檔案不算原始碼 |
| `exclude` | `[]` | 整個跳過的目錄，例如 `["vendor/", "tools/"]` |
| `test.command` | 啟用 `test` 時必填 | 字串陣列，不經過 shell |
| `crap.threshold` | `12` | CRAP 上限 |
| `crap.inspector` | 啟用 `crap` 時必填 | 檢查員指令（字串陣列） |
| `mutation.kill_rate_threshold` | `80` | 抓錯率下限（%） |
| `mutation.reach_rate_threshold` | `50` | 測到率下限（%）。沒有這個門檻的話，新寫的程式完全沒有測試也能過關 |
| `mutation.exclude_mutators` | `[]` | 整類不檢查的改壞方式，名稱照檢查員回報的 `mutator` |
| `mutation.equivalents_file` | `.referee-equivalents.json` | 「改了也沒差」的排除清單 |
| `mutation.inspector` | 啟用 `mutation` 時必填 | 檢查員指令 |

`sources`、`tests`、`exclude` 的比對規則（`*`、`**/`、目錄比對）寫在 [docs/合約.md](docs/合約.md)。裁判拿到記分表後會再依這三項篩一次，檢查員多交的項目不影響結果。

### 排除清單

`.referee-equivalents.json` 是陣列，每一項是一個人判斷過、改了也沒差的改壞版本：

```json
[{"file": "shipping/fee.go", "mutator": "CONDITIONALS_BOUNDARY", "line_text": "if total >= 1000 {",
  "reason": "...", "approved_by": "...", "column": 11}]
```

必填 `file`、`mutator`、`line_text`（該行去頭尾空白後的原文）、`reason`、`approved_by`；選填 `function`（只供顯示）、`column`（同一行同一種改法有好幾個時，只排除那一欄）。那一行被改了，項目就對不上，要重新判斷。沒用到的項目會印在報告裡。

## Claude Code 的 Stop hook

`.claude/hooks/gate.sh` 在 AI 要結束對話時跑第一、二關（`check --base <base> --skip mutation`）。沒過就以結束碼 2 擋下結束，把訊息交回 AI 繼續修。行為：

- base 讀 `.referee.json` 的 `base`，環境變數 `REFEREE_BASE` 可以覆蓋。
- 找不到 base（例如還沒 fetch），放行，CI 會再擋一次。
- 這次沒有改任何東西，放行。
- 有改東西但 `tools/referee/referee.py` 不在（submodule 沒抓），擋下並提示 `git submodule update --init`。
- 沒過時依「停在第 N 關」給訊息：第一關是測試失敗，第二關是 CRAP 超標，結束碼 2 是量測失敗。

抓錯檢查太慢，不放在 hook 裡，交給 CI。

## CI

`workflows/go.yml`（複製成 `.github/workflows/referee.yml`）在 PR 進 main 時跑三關：`fetch-depth: 0` 和 `submodules: true` 抓完整歷史和工具，setup-go、setup-python，再依序執行 `test`、`crap --base origin/<base_ref>`、`mutation --base origin/<base_ref>`。submodule 的網址是這個 runner 抓不到的私有 repo 時，要在 checkout 步驟加存取權杖。

## 自訂檢查員

不用 Go，或 Go 專案想用自己的量法：在專案裡寫一支腳本，把 `crap.inspector`（或 `mutation.inspector`）換成它的指令。腳本從環境變數 `REFEREE_CONTEXT` 讀 context，把記分表寫到 `REFEREE_OUT`，量完結束碼 0。函式表和改壞版本表的欄位、context 內容、路徑比對規則，都在 [docs/合約.md](docs/合約.md)，`referee/paths.py` 和 `referee/sheets.py` 是參考實作。記分表不合格式時，裁判以結束碼 2 停下並指出哪一項哪個欄位錯。

## Go 檢查員

`inspectors/go.py`，在 go.mod 所在的專案根目錄由裁判啟動：

```
python tools/referee/inspectors/go.py functions|mutants [--coverage-scope package|module] [--workers N]
```

- `--coverage-scope package|module`（預設 package）：module 時，別的套件的測試跑到的程式也算覆蓋率；抓錯檢查改用 gremlins 的 `--integration --coverpkg`，每個改壞的版本跑整個模組的測試。
- `--workers N`：gremlins 同時跑幾個，沒給就用 gremlins 的預設值。只對 `mutants` 有用，`functions` 不跑 gremlins。
- gocyclo、gremlins（都是 v0.6.0）第一次執行時用 `go install` 裝到 `REFEREE_TOOLS_DIR`（預設 `~/.cache/quality-referee`），之後直接執行，斷網也能量。
- 要跳過的目錄寫在 `.referee.json` 的 `exclude`，檢查員從 context 讀，不用在 `inspector` 指令再寫一次。
- 記分表的 `tools` 寫兩個工具的版本，`settings` 寫實際生效的設定（`functions` 只有 `coverage_scope`，`mutants` 有 `coverage_scope` 和 `workers`），會進 JSON 報告。

範本的 `crap.inspector` 沒有帶 `--coverage-scope`，用 package 範圍。專案的測試分散在別的套件時，兩個 inspector 都加 `"--coverage-scope", "module"`。

## 已知限制

- module 範圍的抓錯檢查會跑到被排除套件的測試。gremlins v0.6.0 的 `--integration` 一律從模組根目錄跑 `go test ./...`，`exclude` 裡的套件測試照樣會跑。排除的套件只要有一個測試失敗，檢查就以結束碼 2 停下（gremlins 執行失敗）。quality-tools v2.4.0 也一樣，用 package 範圍可以避開。
- 根目錄有 Go 套件時，gremlins 對根目錄的套件（`.`）一律跑 `./...`，不論範圍是 package 還是 module，都會跑到所有套件的測試，包含 `exclude` 裡的。同理，非根目錄的套件底下有被排除的子套件時，子套件的測試也會被跑到。
- `.claude/settings.json` 的 `Edit(...)` 規則只擋 Claude Code 的編輯工具，擋不住 AI 用 Bash 改檔，而且只在這個 repo 開的對話生效，在別的目錄開的對話改這個 repo 的檔案不受限制。要確保門檻不被改，要靠 CI 和 CODEOWNERS 之類的審查。
- 整個專案掃描式的測試（掃全部文件、全部原始碼）會掃到 `tools/referee/`，要照上面的安裝步驟加豁免。

## 開發

```
python -m unittest                    # 單元測試和端到端測試（用假檢查員，不需要 Go）
python selftest.py go                 # Go 範例專案的全部情境（含 gate.sh），要 Go 和網路（第一次裝 gocyclo、gremlins）
python selftest.py go --only 排除     # 只跑名稱含「排除」的情境
python dev/parity_qt.py sample        # 和 quality-tools v2.4.0 對照範例專案的 CRAP 表和抓錯計數
python dev/parity_qt.py bethere       # 同上，對 BeThere 的暫存複本，抓錯計數要 45 分鐘左右
python dev/walkthrough_bethere.py     # 照這份 README，在 BeThere 的暫存複本上掛 submodule、複製範本、走一遍
```

selftest 的 gate.sh 情境把這個 repo 的 `git ls-files` 複製到範例的 `tools/referee/`（像 submodule 一樣），再照「安裝到專案」的步驟複製範本，所以只有已經加入 git 的檔案會被複製。

## 驗證狀態

已驗證：

- 單元測試、selftest 的 Go 範例情境（含 gate.sh 情境）：本機 Windows（Git for Windows 的 bash），以及每次推送和 PR 時的 GitHub Actions（`.github/workflows/selftest.yml`，ubuntu-latest）。
- 和 quality-tools v2.4.0 對照：Go 範例專案的 CRAP 表和抓錯計數（package、module 兩種範圍）；BeThere 整個專案的 CRAP 表（module 範圍，329 列）和 `internal/rundown` 的抓錯計數。
- 照這份 README 在 BeThere 的暫存 clone 掛上工具：第一、二關通過；改壞一個測試時 gate.sh 擋下。
- BeThere 實際導入（v0.1.0，module 範圍）：以 readbody-split 合併前的 main 當 base 跑 `check`，三關通過（改到 30 個函式；抓錯檢查 47 個改壞版本全抓到，排除清單用上 1 筆）。
- Claude Code 實際觸發 Stop hook：在 BeThere 的對話裡改壞一個測試，結束回覆時 gate.sh 擋下，訊息是「第一關沒過」。

還沒驗證：

- `templates/go/workflows/go.yml` 還沒在 runner 上跑過，本機只確認 YAML 能解析、結構正確（沒有 actionlint）。第一次在專案的 runner 上跑時，submodule 的存取權杖可能要調整。範本用的 actions 是 v7（Node 24），Gitea 的 act_runner 支不支援還沒確認。
- macOS 上還沒跑過。
