-- Dynamic-cursors plugin config. Config schema confirmed from
-- github.com/VirtCode/hypr-dynamic-cursors README.
--
-- ponytail: the `hyprpm reload -n` startup command lives in autostart.lua's
-- single hl.on("hyprland.start", ...) block (first line there), NOT here -
-- whether multiple files each calling hl.on() for the same event stack or the
-- last one silently wins is unconfirmed, so there's exactly one registration
-- for that event across the whole config, full stop.
--
-- This guard itself is a real ordering assumption: it depends on the plugin
-- already being registered into `hl.plugin` by the time this script runs
-- (i.e. hyprpm's own plugin-loading happens before/independently of the lua
-- config script executing, not as a result of the exec_cmd above). Verify by
-- checking `hyprctl plugins list` after reload - if dynamic-cursors settings
-- aren't applied, this guard evaluating false at parse time is the reason.
if hl.plugin.dynamic_cursors then
    hl.config({ plugin = { dynamic_cursors = {
        enabled   = true,
        mode      = "stretch",   -- stretch, rotate, tilt, none

        shake = {
            enabled   = true,
            threshold = 5.0,
            base      = 4.0,
            speed     = 5.0,
            influence = 1.0,
            limit     = 1.0,
            timeout   = 1500,
        },

        hyprcursor = {
            enabled    = true,
            resolution = -1,
            -- ponytail: README's own example sets nearest = 1 (number) where
            -- the old .conf used a bool (false). Kept the bool; try 0 if the
            -- plugin rejects it.
            nearest    = false,
        },
    }}})
end
