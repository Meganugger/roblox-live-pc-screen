-- Standalone-Luau spec for RlpsDecoder.parseBundle (vectors from the Python reference parser, identical errors).
local Decoder = require("./RlpsDecoder")
local V = require("./vectors")

local passed, failed = 0, 0
local function check(cond: boolean, name: string, detail: string?)
	if cond then
		passed += 1
	else
		failed += 1
		print("FAIL " .. name .. ": " .. (detail or ""))
	end
end

for _, case in V.bundles do
	local entries, err = Decoder.parseBundle(buffer.fromstring(case.data))
	if case.err then
		check(entries == nil and err == case.err, "bundle:" .. case.name, "got " .. tostring(err))
	else
		check(entries ~= nil and #entries == #case.entries, "bundle:" .. case.name, tostring(err))
		if entries then
			for i, e in case.entries do
				local g = entries[i]
				check(g ~= nil and g.tOffsetMs == e.t and g.offset == e.offset and g.length == e.length,
					"bundle:" .. case.name .. ":" .. i)
			end
		end
	end
end

print(string.format("SUMMARY passed=%d failed=%d", passed, failed))
