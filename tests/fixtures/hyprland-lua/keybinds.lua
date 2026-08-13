local programs = require("programs")
local mainMod = "SUPER"

hl.bind(mainMod .. " + T", hl.dsp.exec_cmd(programs.terminal))
hl.bind(mainMod .. " + Q", hl.dsp.window.close())
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(programs.fileManager))
hl.bind(mainMod .. " + F", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + CTRL + R", hl.dsp.exec_cmd("hyprctl reload"))

-- ponytail: bindr = release-only. Bind flag letters map 1:1 onto
-- HL.BindOptions fields (bindl -> locked=true, bindm -> mouse=true, both
-- confirmed via the official example file's mouse binds below), so
-- `release = true` for the "r" flag is a strong pattern-match, but I
-- couldn't load the Binds wiki page itself to see the literal field name.
hl.bind(mainMod .. " + SUPER_L", hl.dsp.exec_cmd("bash ~/.config/hypr/launcher.sh"), { release = true })

hl.bind(mainMod .. " + W", hl.dsp.exec_cmd(programs.browser))
hl.bind(mainMod .. " + C", hl.dsp.exec_cmd("code"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("hyprshot -m region -o ~/Pictures/Screenshots"))
hl.bind("CTRL + SHIFT + Escape", hl.dsp.exec_cmd("missioncenter"))
hl.bind(mainMod .. " + K", hl.dsp.exec_cmd("gitkraken"))
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd("localsend"))
hl.bind(mainMod .. " + N", hl.dsp.exec_cmd("notion-app"))
hl.bind(mainMod .. " + Escape", hl.dsp.exec_cmd("~/.config/hypr/scripts/special-off.sh"))
hl.bind(mainMod .. " + Z", hl.dsp.exec_cmd("/home/user/.local/bin/zed"))

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Switch workspaces mainMod + [0-9], move window mainMod + SHIFT + [0-9]
for i = 1, 10 do
    local key = i % 10 -- 10 maps to key 0
    hl.bind(mainMod .. " + " .. key,         hl.dsp.focus({ workspace = i }))
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end

-- Launch-or-focus + reveal each app's dedicated special workspace, in one
-- explicit bind. hl.dsp.* builds a dispatcher object; hl.dispatch() is what
-- actually runs it (confirmed: github.com/hyprwm/Hyprland discussion #14282).
-- Single-instance apps (vesktop/steam/spotify/claude-desktop) no-op on the
-- second exec_cmd, so it's safe to fire every press. The matching
-- windowrules.lua rule is what actually routes the window onto that
-- workspace once it opens.
hl.bind(mainMod .. " + M", function()
    hl.dispatch(hl.dsp.exec_cmd(programs.music))
    hl.dispatch(hl.dsp.workspace.toggle_special("magic"))
end)
hl.bind(mainMod .. " + SHIFT + M", hl.dsp.window.move({ workspace = "special:magic" }))
hl.bind(mainMod .. " + SHIFT + D", hl.dsp.window.move({ workspace = "special:minimized" }))
hl.bind(mainMod .. " + D", hl.dsp.workspace.toggle_special("minimized"))

hl.bind(mainMod .. " + V", function()
    hl.dispatch(hl.dsp.exec_cmd("vesktop"))
    hl.dispatch(hl.dsp.workspace.toggle_special("discord"))
end)
hl.bind(mainMod .. " + SHIFT + V", hl.dsp.window.move({ workspace = "special:discord" }))

hl.bind(mainMod .. " + G", function()
    hl.dispatch(hl.dsp.exec_cmd("steam"))
    hl.dispatch(hl.dsp.workspace.toggle_special("game"))
end)
hl.bind(mainMod .. " + SHIFT + G", hl.dsp.window.move({ workspace = "special:game" }))

-- Toggles special:assistant - matches the claude-to-assistant window rule
-- in windowrules.lua, same scratchpad pattern as magic/discord/game above.
hl.bind(mainMod .. " + ALT + space", function()
    hl.dispatch(hl.dsp.exec_cmd("claude-desktop"))
    hl.dispatch(hl.dsp.workspace.toggle_special("assistant"))
end)

-- volumebinds made by me
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("pamixer -i 5"))
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("pamixer -d 5"))
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("pamixer -t"))

-- Scroll through workspaces with mainMod + scroll
hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

-- Move/resize windows with mainMod + LMB/RMB drag
-- FIX (confirmed via /usr/share/hypr/stubs/hl.meta.lua): HL.BindOptions has no
-- `mouse` field - `mouse` only exists as a *reported* property on the returned
-- Keybind object (auto-detected from the "mouse:NNN" key string). The real
-- settable field is `drag`.
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { drag = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { drag = true })

-- Laptop multimedia keys
-- bindel = ,XF86AudioRaiseVolume, exec, wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+
-- bindel = ,XF86AudioLowerVolume, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
-- bindel = ,XF86AudioMute, exec, wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), { locked = true })
