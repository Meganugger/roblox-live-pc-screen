-- Standalone-Luau spec for RlpsBase64 against Python base64.b64decode(validate=True) verdicts (vectors.luau).
-- Contract: canonical bodies decode to the same bytes; anything Python rejects is rejected; non-canonical input that
-- Python tolerates is either rejected (stricter is allowed) or decoded to exactly Python's bytes.
local Base64 = require("./RlpsBase64")
local V = require("./vectors")

local passed, failed = 0, 0
for i, case in V.base64 do
	local name = "base64#" .. i .. " " .. string.format("%q", string.sub(case.s, 1, 16))
	local out, err = Base64.decode(case.s)
	if case.err then
		if out ~= nil then
			failed += 1
			print("FAIL " .. name .. ": accepted input Python rejects")
		else
			passed += 1
		end
	elseif out == nil then
		if case.canonical then
			failed += 1
			print("FAIL " .. name .. ": rejected canonical input: " .. tostring(err))
		else
			passed += 1
		end
	elseif buffer.tostring(out) ~= case.out then
		failed += 1
		print("FAIL " .. name .. ": decoded bytes differ from Python")
	else
		passed += 1
	end
end
print(string.format("SUMMARY passed=%d failed=%d", passed, failed))
