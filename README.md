# quality-referee

裁判和檢查員分開的品質工具。裁判不認得任何語言，只執行設定檔寫的指令、讀檢查員交出的記分表，依門檻判定單元測試、CRAP、抓錯檢查三道關。

目前狀態：R1，只有裁判核心和合約，還沒有任何語言的檢查員。完整的介面定義在 [docs/合約.md](docs/合約.md)。

## 用法

Python 3.8 以上，只用標準函式庫。在專案根目錄放 `.referee.json`（格式見合約），然後：

```
python referee.py test
python referee.py crap --base origin/main
python referee.py mutation --base origin/main --json mutation.json
python referee.py check --base origin/main --skip mutation --json reports/
```

結束碼：0 通過，1 沒過門檻，2 量測失敗或設定有誤。

## 測試

```
python -m unittest
```

端到端測試在暫存 git repo 裡用 `tests/fake_inspector.py` 當檢查員，不需要任何語言的量測工具。
