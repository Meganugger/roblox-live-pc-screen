--!strict
-- RLPS view math (pure Luau, no Roblox APIs, so the standalone specs can test it): how far a camera must stand to
-- frame a screen, and the rules RlpsClient uses to skip redrawing screens nobody can see.

local View = {}

-- Distance from a flat w x h screen at which a camera with vertical field of view `vfovDeg` and viewport aspect
-- `aspect` (width / height) shows the whole screen, using only `usable` of the viewport height (cinema bars) and
-- leaving `margin` (e.g. 0.95 = 5 %) around it.
function View.fitDistance(w: number, h: number, vfovDeg: number, aspect: number, usable: number, margin: number): number
	local t = math.tan(math.rad(math.clamp(vfovDeg, 1, 120)) / 2)
	local byHeight = (h / 2) / (t * math.max(usable, 0.05))
	local byWidth = (w / 2) / (t * math.max(aspect, 0.1))
	return math.max(byHeight, byWidth) / math.clamp(margin, 0.1, 1)
end

-- Whether a screen face can be seen from a camera, from plain dot products:
--   facing  = normal · (camera - face centre)  (≤ 0: the camera is behind the screen, its face is not visible)
--   ahead   = look · (face centre - camera)    (< -radius: the whole screen is behind the camera)
-- plus the distance limit.
function View.visible(distance: number, facing: number, ahead: number, radius: number, maxDistance: number): boolean
	return distance <= maxDistance and facing > 0 and ahead >= -radius
end

-- Parse the server's ViewerModes attribute ("fullscreen,cinema,mini"; anything else ignored) into a set.
function View.parseModes(raw: unknown): { [string]: boolean }
	local set: { [string]: boolean } = {}
	local text = if typeof(raw) == "string" then raw :: string else "fullscreen,cinema,mini"
	for word in string.gmatch(string.lower(text), "%a+") do
		if word == "fullscreen" or word == "cinema" or word == "mini" then
			set[word] = true
		end
	end
	return set
end

return View
