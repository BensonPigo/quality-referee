package checkout

import "testing"

// ❌ 第二課練習 4 的假測試：只呼叫、不檢查答案。
// 覆蓋率 100%、CRAP 全部 PASS，但什麼錯都抓不到。
func TestCheckout_NoCheck(t *testing.T) {
	Checkout(nil, NonMember, "")
	Checkout([]Item{{500, 0, false}, {300, 1, false}}, NonMember, "")
	Checkout([]Item{{2000, 2, false}}, Member, "")
	Checkout([]Item{{500, 1, false}}, VIP, "")
	Checkout([]Item{{1000, 1, true}}, Member, "")
	Checkout([]Item{{1200, 1, false}}, NonMember, "SAVE100")
	Checkout([]Item{{500, 1, false}}, NonMember, "HALFSHIP")
}
