class RefereeError(Exception):
    """量測沒辦法完成，或設定、記分表有誤。訊息直接顯示給使用者，結束碼 2。"""

    exit_code = 2
