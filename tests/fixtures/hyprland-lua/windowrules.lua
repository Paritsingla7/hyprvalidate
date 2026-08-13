hl.window_rule({
    name  = "suppress-maximize-events",
    match = { class = ".*" },
    suppress_event = "maximize",
})

hl.window_rule({
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },
    no_focus = true,
})

hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },
    move  = "20 monitor_h-120",
    float = true,
})

-- ponytail: `workspace = "..."` field on these is inferred from the
-- match/move/float key-passthrough pattern confirmed above, not directly
-- shown in the example config I fetched.
hl.window_rule({
    name  = "spotify-to-magic",
    match = { class = "Spotify" },
    workspace = "special:magic",
})

hl.window_rule({
    name  = "vesktop-to-discord",
    match = { class = "vesktop" },
    workspace = "special:discord",
})

hl.window_rule({
    name  = "code-to-code",
    match = { class = "code" },
    workspace = "special:code",
})

-- Special workspace, matching the toggle_special("assistant") bind in
-- keybinds.lua - same scratchpad convention as magic/discord/game below.
hl.window_rule({
    name  = "claude-to-assistant",
    match = { class = "claude-desktop" },
    workspace = "special:assistant",
})

hl.window_rule({
    name  = "steam-to-game",
    match = { class = "steam" },
    workspace = "special:game",
})

hl.window_rule({
    name  = "whatsapp-to-hidden",
    match = { class = "whatsapp-linux-app" },
    workspace = "minimized",
})

hl.window_rule({
    name  = "teams-to-hidden",
    match = { class = "teams-for-linux" },
    workspace = "minimized",
})

hl.window_rule({
    name  = "google-to-minimized",
    match = { class = "google-apps-desktop" },
    workspace = "minimized",
})
