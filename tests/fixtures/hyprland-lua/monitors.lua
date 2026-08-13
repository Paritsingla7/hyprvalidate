-- ponytail: device{output=...} passthrough mapping is inferred by extending
-- the confirmed hl.device() key-passthrough pattern (name/sensitivity ->
-- name/output) - the wiki Devices page returned a JS-rendered shell over
-- WebFetch, not the actual text, so verify with `hyprctl devices` after reload.

hl.monitor({ output = "eDP-1", mode = "1920x1080@144", position = "0x0", scale = 1 })
-- hl.monitor({ output = "HDMI-A-1", mode = "1600x900", position = "auto", scale = 1 }) -- #2880x1800 1920x1200

hl.device({ name = "mouse-passthrough-(absolute)", output = "HDMI-A-1" })
hl.device({ name = "mouse-passthrough",             output = "HDMI-A-1" })
hl.device({ name = "pen-touchthrough",               output = "HDMI-A-1" })
