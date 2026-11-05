"""假檢查員：把收到的 REFEREE_CONTEXT 複製一份，再把測試指定的記分表原樣當成輸出。

環境變數：
    FAKE_OUT_DIR       context 副本放哪裡（ctx-<關>.json）
    FAKE_SHEET_CRAP / FAKE_SHEET_MUTATION   要交出的記分表檔案
    FAKE_EXIT          設了就印一行訊息後以這個結束碼離開
    FAKE_NOWRITE       設了就結束碼 0 但不寫記分表
"""

import os
import shutil
import sys

gate = sys.argv[1]
shutil.copy(os.environ["REFEREE_CONTEXT"], os.path.join(os.environ["FAKE_OUT_DIR"], "ctx-{}.json".format(gate)))
if os.environ.get("FAKE_EXIT"):
    print("fake inspector boom")
    sys.exit(int(os.environ["FAKE_EXIT"]))
if os.environ.get("FAKE_NOWRITE"):
    sys.exit(0)
shutil.copy(os.environ["FAKE_SHEET_" + gate.upper()], os.environ["REFEREE_OUT"])
