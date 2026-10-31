-- Standalone-Luau spec for RlpsView: camera framing distance, visibility rule, viewer-mode parsing.
local View = require("./RlpsView")
local H = require("./spec_helpers")

local T = H.counter()

local function near(a: number, b: number, eps: number?): boolean
	return math.abs(a - b) <= (eps or 1e-9)
end

-- framing: the screen exactly fills the usable height (or width) at margin 1
do
	local t = math.tan(math.rad(70) / 2)
	-- 16x9 screen, 70° vertical fov, 16:9 viewport, full height usable: height and width limits coincide
	local d = View.fitDistance(16, 9, 70, 16 / 9, 1, 1)
	T.check(near(d, 4.5 / t), "16:9 screen in a 16:9 view: limited by both axes equally", tostring(d))
	-- a 4:3 viewport is narrower: the width decides
	local d43 = View.fitDistance(16, 9, 70, 4 / 3, 1, 1)
	T.check(near(d43, 8 / (t * 4 / 3)) and d43 > d, "4:3 viewport: width limits, camera further away", tostring(d43))
	-- cinema bars use 16 % of the height: the camera steps back so the screen fits the remaining 84 %
	local dc = View.fitDistance(16, 9, 70, 16 / 9, 0.84, 1)
	T.check(near(dc, 4.5 / (t * 0.84)), "cinema bars", tostring(dc))
	-- margin 0.95 leaves 5 %
	T.check(near(View.fitDistance(16, 9, 70, 16 / 9, 1, 0.95), d / 0.95), "margin")
	-- degenerate inputs stay finite
	local z = View.fitDistance(16, 9, 0, 0, 0, 0)
	T.check(z == z and z < math.huge, "clamped degenerate inputs", tostring(z))
end

-- visibility
do
	T.check(View.visible(20, 5, 10, 9, 300), "in front, facing the screen")
	T.check(not View.visible(20, -5, 10, 9, 300), "behind the screen (face turned away)")
	T.check(not View.visible(20, 0, 10, 9, 300), "edge-on")
	T.check(not View.visible(20, 5, -30, 9, 300), "screen entirely behind the camera")
	T.check(View.visible(20, 5, -5, 9, 300), "screen partly beside/behind the camera still counts")
	T.check(not View.visible(301, 5, 10, 9, 300), "too far")
end

-- modes
do
	local all = View.parseModes(nil)
	T.check(all.fullscreen and all.cinema and all.mini, "default: every mode")
	local some = View.parseModes(" Cinema, MINI ")
	T.check(some.cinema and some.mini and not some.fullscreen, "case-insensitive subset")
	T.eq(next(View.parseModes("")), nil, "empty string disables the viewer controls")
	T.eq(next(View.parseModes("party,hack")), nil, "unknown words ignored")
end

T.summary()
