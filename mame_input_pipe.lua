local PIPE = [[\\.\pipe\mame_input]]
local dev = manager.machine.natkeyboard

emu.register_frame(function()
    local f = io.open(PIPE, "r")
    if not f then return end

    local key = f:read("*l")
    f:close()

    if key and key ~= "" and dev then
        key = key:gsub("%s+$", "")
        if key:find("{") then
            key = dev:post_coded(key)
        else
            key = dev:post(key)
        end
    end
end)
